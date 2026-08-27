#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP.calibration.compare_modes

Runs Baseline / Fuzzy / AHP / Meta-Adaptive through the EXACT SAME
protocol (protocol.py's IS -> Calibration -> LOCK -> Purge -> OOS folds,
same coin, same bars, same purge gap) so their OOS numbers are actually
comparable — the shipped RSP/multi_coin_meta_test.py runs each scenario
once over the FULL dataset with no IS/OOS split at all, which is exactly
the "compare on identical protocol" gap the brief calls out.

Then runs an ablation: starting from a risk-only Baseline, add exactly one
component at a time (Fuzzy rules, then AHP scoring instead of rules, then
Meta-Controller blending) so any profit delta can be attributed to the
specific component that produced it, not to "the whole bundle of changes
that happened to ship together" (the same trap noted in this repo's own
CALIBRATION FIX comments in settings.py / multi_coin_meta_test.py).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import param_registry as reg
from .protocol import CalibrationProtocolPlan, materialize_tf
from .optimizer import calibrate_on_is, run_one
from .scoring import WindowScore, aggregate_oos, golden_rule_gate, Verdict
from .robustness import run_robustness_suite, RobustnessReport


MODES_TO_COMPARE = [reg.MODE_BASELINE, reg.MODE_FUZZY, reg.MODE_AHP, reg.MODE_META]


@dataclass
class ModeResult:
    mode: str
    fold_is_scores: List[float] = field(default_factory=list)
    fold_oos_windows: List[WindowScore] = field(default_factory=list)
    locked_params_by_fold: List[Dict] = field(default_factory=list)
    oos_agg: Optional[WindowScore] = None
    verdict: Optional[Verdict] = None
    robustness: Optional[RobustnessReport] = None


def run_mode_across_folds(bars_by_tf: Dict, base_tf: str, plan: CalibrationProtocolPlan,
                           mode: str, coin_id: Optional[str], min_history: int,
                           n_calibration_passes: int = 2) -> ModeResult:
    result = ModeResult(mode=mode)
    for fold_idx, (is_split, oos_split) in enumerate(plan.calibration_windows):
        is_bars = materialize_tf(bars_by_tf, base_tf, is_split)
        oos_bars = materialize_tf(bars_by_tf, base_tf, oos_split)

        calib = calibrate_on_is(is_bars, mode, coin_id, base_tf=base_tf, min_history=min(min_history, len(is_bars.get(base_tf, [])) or min_history),
                                 n_passes=n_calibration_passes, fold_label=f"fold{fold_idx}")
        result.fold_is_scores.append(calib.final_is_score)
        result.locked_params_by_fold.append(calib.locked_params)

        # LOCK -> single OOS evaluation, never re-optimized.
        oos_min_hist = min(min_history, max(10, len(oos_bars.get(base_tf, [])) - 1)) if len(oos_bars.get(base_tf, [])) else min_history
        oos_summary = run_one(oos_bars, mode, coin_id, calib.locked_params, base_tf, oos_min_hist)
        result.fold_oos_windows.append(WindowScore.from_summary(f"OOS_fold{fold_idx}", oos_summary))

        if fold_idx == len(plan.calibration_windows) - 1:
            # robustness suite runs once, on the most-recent (most-calibrated) fold's
            # locked params + OOS bars — cheapest fold to run it on that's still
            # representative of "what would actually ship".
            result.robustness = run_robustness_suite(oos_bars, mode, coin_id, calib.locked_params,
                                                       oos_summary, base_tf, oos_min_hist)

    result.oos_agg = aggregate_oos(result.fold_oos_windows)
    return result


def compare_all_modes(bars_by_tf: Dict, base_tf: str, plan: CalibrationProtocolPlan,
                       coin_id: Optional[str] = None, min_history: int = 200,
                       n_calibration_passes: int = 2, parallel: bool = False) -> Dict[str, ModeResult]:
    results: Dict[str, ModeResult] = {}
    if parallel:
        # The 4 modes are fully independent (each mutates module-level
        # settings via apply_overrides/temporary_override, then restores
        # them) — safe to run as SEPARATE PROCESSES (each gets its own
        # memory, so no shared-state race), NOT threads. On a machine with
        # >=4 cores this is close to a 4x wall-clock reduction for the mode
        # comparison stage, which is normally the single biggest chunk of
        # a full run.
        import concurrent.futures as cf
        with cf.ProcessPoolExecutor(max_workers=min(4, len(MODES_TO_COMPARE))) as ex:
            futures = {ex.submit(run_mode_across_folds, bars_by_tf, base_tf, plan, mode,
                                  coin_id, min_history, n_calibration_passes): mode
                       for mode in MODES_TO_COMPARE}
            for fut in cf.as_completed(futures):
                mode = futures[fut]
                results[mode] = fut.result()
    else:
        for mode in MODES_TO_COMPARE:
            results[mode] = run_mode_across_folds(bars_by_tf, base_tf, plan, mode, coin_id,
                                                    min_history, n_calibration_passes)

    baseline_oos_windows = results[reg.MODE_BASELINE].fold_oos_windows
    for mode in MODES_TO_COMPARE:
        r = results[mode]
        # use the LAST fold's IS composite score for the golden-rule IS side —
        # matches "the calibration that actually shipped" rather than an
        # average across an evolving anchored-window search. Only the final
        # composite score is stored per fold (not a full WindowScore), so
        # synthesize a minimal stand-in exposing just what golden_rule_gate
        # actually reads (net_return_pct, composite_score()).
        class _ISShim:
            def __init__(self, score, net):
                self._score = score
                self.net_return_pct = net
            def composite_score(self):
                return self._score
        is_shim = _ISShim(r.fold_is_scores[-1] if r.fold_is_scores else 0.0,
                           r.fold_oos_windows[-1].net_return_pct if r.fold_oos_windows else 0.0)
        r.verdict = golden_rule_gate(is_shim, r.fold_oos_windows, baseline_oos_windows)
    return results


@dataclass
class AblationStep:
    label: str
    engine_flags: Dict
    oos_agg: WindowScore
    delta_net_vs_previous: float
    verdict: Verdict


def run_ablation(bars_by_tf: Dict, base_tf: str, plan: CalibrationProtocolPlan,
                  baseline_locked_risk_params: Dict, coin_id: Optional[str] = None,
                  min_history: int = 200) -> List[AblationStep]:
    """
    Incremental component activation, all on top of the SAME locked risk
    parameters (from Baseline's calibration), so the only thing changing
    step to step is exactly one decision-layer component:
        risk-only Baseline
          -> + Fuzzy rules
          -> + AHP scoring (replaces rules)
          -> + Meta-Controller blending (replaces static rules/ahp choice)
    Each step's OOS is measured on the SAME OOS folds as the others.
    """
    from RSP.config import settings

    ablation_specs = [
        ("baseline_risk_only", {"FUZZY_BACKTEST_ENABLED": False, "META_CONTROLLER_ENABLED": False}),
        ("plus_fuzzy_rules", {"FUZZY_BACKTEST_ENABLED": True, "META_CONTROLLER_ENABLED": False,
                               "OPPORTUNITY_SCORING_METHOD": "rules"}),
        ("plus_ahp_instead_of_rules", {"FUZZY_BACKTEST_ENABLED": True, "META_CONTROLLER_ENABLED": False,
                                        "OPPORTUNITY_SCORING_METHOD": "ahp"}),
        ("plus_meta_controller", {"FUZZY_BACKTEST_ENABLED": True, "META_CONTROLLER_ENABLED": True,
                                   "OPPORTUNITY_SCORING_METHOD": "rules"}),
    ]

    steps: List[AblationStep] = []
    prev_net = None
    baseline_oos_windows_for_verdict = None
    for label, flags in ablation_specs:
        oos_windows: List[WindowScore] = []
        for is_split, oos_split in plan.calibration_windows:
            oos_bars = materialize_tf(bars_by_tf, base_tf, oos_split)
            n_bars = len(oos_bars.get(base_tf, []))
            if n_bars < 5:
                continue
            oos_min_hist = min(min_history, max(3, n_bars - 1))
            restore = reg.apply_overrides(baseline_locked_risk_params) if baseline_locked_risk_params else (lambda: None)
            try:
                with settings.temporary_override(flags):
                    from RSP.backtest_engine.backtest_engine import run_backtest
                    summary = run_backtest(oos_bars, base_tf=base_tf, min_history=oos_min_hist, coin_id=coin_id)
            finally:
                restore()
            oos_windows.append(WindowScore.from_summary(f"{label}_oos", summary))

        agg = aggregate_oos(oos_windows)
        delta = 0.0 if prev_net is None else round(agg.net_return_pct - prev_net, 3)
        if label == "baseline_risk_only":
            baseline_oos_windows_for_verdict = oos_windows
            verdict = Verdict(True, "پایه‌ی مقایسه (Baseline risk-only) — همیشه نگه داشته می‌شود.")
        else:
            class _ISShim:
                def __init__(self, net): self.net_return_pct = net; self._s = 0.0
                def composite_score(self): return self._s
            verdict = golden_rule_gate(_ISShim(agg.net_return_pct), oos_windows, baseline_oos_windows_for_verdict)
        steps.append(AblationStep(label=label, engine_flags=flags, oos_agg=agg,
                                   delta_net_vs_previous=delta, verdict=verdict))
        prev_net = agg.net_return_pct
    return steps
