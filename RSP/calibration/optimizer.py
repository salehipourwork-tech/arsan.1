#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP.calibration.optimizer

Coordinate-ascent search over param_registry's grids, run ONLY on the
Train/IS + Calibration slice of each fold. Never touches OOS or the Final
Holdout while searching (that would defeat the entire point).

Why coordinate ascent and not a black-box optimizer: the engine is
rule-based (documented limitation in RSP/walk_forward/walk_forward.py —
"Train" here means indicator warm-up, not a fittable model), each
evaluation is a full run_backtest() (slow: recomputes indicators from
scratch per bar), and the registry mixes floats/ints/tuples/dicts/bools.
A small, explicit, auditable coordinate search — one parameter's grid at
a time, keep whatever improves the IS composite score, move to the next
parameter, repeat for a couple of passes — is transparent (every accepted
step is individually reviewable) and cheap enough to actually run,
matching how RSP/fuzzy_core/fuzzy_calibration_wf.py already does small
explicit grids rather than a black box.

LOCK step: once a pass completes for a fold, the resulting parameter dict
is frozen (`locked_params`) and handed to protocol.py's OOS window for a
single, un-optimized evaluation. Nothing here ever re-touches locked
params after that point for that fold.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import itertools

from RSP.config import settings
from RSP.backtest_engine.backtest_engine import run_backtest

from . import param_registry as reg
from .scoring import WindowScore


BASE_ENGINE_OVERRIDES = {
    # Mode toggles are applied via settings.temporary_override (not the
    # param_registry override machinery, since these are engine on/off
    # switches, not calibratable numeric knobs).
}


def _mode_engine_flags(mode: str) -> Dict:
    if mode == reg.MODE_BASELINE:
        return {"FUZZY_BACKTEST_ENABLED": False, "META_CONTROLLER_ENABLED": False}
    if mode == reg.MODE_FUZZY:
        return {"FUZZY_BACKTEST_ENABLED": True, "META_CONTROLLER_ENABLED": False,
                "OPPORTUNITY_SCORING_METHOD": "rules"}
    if mode == reg.MODE_AHP:
        return {"FUZZY_BACKTEST_ENABLED": True, "META_CONTROLLER_ENABLED": False,
                "OPPORTUNITY_SCORING_METHOD": "ahp"}
    if mode == reg.MODE_META:
        return {"FUZZY_BACKTEST_ENABLED": True, "META_CONTROLLER_ENABLED": True,
                "OPPORTUNITY_SCORING_METHOD": "rules"}
    raise ValueError(mode)


def run_one(bars_by_tf: Dict, mode: str, coin_id: Optional[str], param_overrides: Dict,
            base_tf: str = "15M", min_history: int = 200):
    engine_flags = _mode_engine_flags(mode)
    restore_params = reg.apply_overrides(param_overrides) if param_overrides else (lambda: None)
    try:
        with settings.temporary_override(engine_flags):
            return run_backtest(bars_by_tf, base_tf=base_tf, min_history=min_history, coin_id=coin_id)
    finally:
        restore_params()


@dataclass
class CalibrationStep:
    param: str
    from_value: object
    to_value: object
    is_score_before: float
    is_score_after: float
    accepted: bool


@dataclass
class CalibrationResult:
    mode: str
    fold_label: str
    locked_params: Dict = field(default_factory=dict)
    steps: List[CalibrationStep] = field(default_factory=list)
    final_is_score: float = 0.0


def calibrate_on_is(bars_by_tf_is: Dict, mode: str, coin_id: Optional[str],
                     base_tf: str = "15M", min_history: int = 200,
                     n_passes: int = 2, params: Optional[List[reg.ParamSpec]] = None,
                     fold_label: str = "fold") -> CalibrationResult:
    """
    Coordinate ascent on the IS slice only. Returns the locked parameter
    dict (only params that actually improved the IS composite score are
    included — everything else stays at its shipped default).
    """
    params = params if params is not None else reg.params_for_mode(mode)
    locked: Dict = {}
    result = CalibrationResult(mode=mode, fold_label=fold_label)

    def score_with(overrides: Dict) -> float:
        summary = run_one(bars_by_tf_is, mode, coin_id, overrides, base_tf, min_history)
        return WindowScore.from_summary("IS", summary).composite_score()

    current_score = score_with(locked)
    for _pass in range(n_passes):
        improved_this_pass = False
        for spec in params:
            if spec.kind in ("bool",) and len(spec.calibration_grid) <= 1:
                continue
            best_val = locked.get(spec.name, spec.current_value())
            best_score = current_score
            for candidate_val in spec.calibration_grid:
                trial = dict(locked)
                trial[spec.name] = candidate_val
                s = score_with(trial)
                if s > best_score:
                    best_score = s
                    best_val = candidate_val
            if best_val != locked.get(spec.name, spec.current_value()):
                result.steps.append(CalibrationStep(
                    param=spec.name, from_value=locked.get(spec.name, spec.current_value()),
                    to_value=best_val, is_score_before=current_score, is_score_after=best_score,
                    accepted=True))
                locked[spec.name] = best_val
                current_score = best_score
                improved_this_pass = True
        if not improved_this_pass:
            break

    result.locked_params = locked
    result.final_is_score = current_score
    return result
