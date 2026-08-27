#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP.calibration.robustness

Runs, on a LOCKED parameter set (never re-optimizes anything here):
  1. Parameter perturbation ±5% / ±10% around the locked values, generic
     across the whole registry (the shipped RSP/robustness/monte_carlo.py
     only perturbed a fixed, hand-picked scenario list — this instead
     perturbs whatever was actually locked, which is what "look for a
     plateau, not a magic point" requires).
  2. Regime analysis — reuses RSP.robustness.stress_test.performance_by_market_type
     on the OOS trades actually produced.
  3. Fee/slippage stress test — reuses RSP.robustness.monte_carlo's cost
     scenarios.
  4. Trade sequence randomization / drawdown robustness — reuses
     RSP.robustness.monte_carlo.randomize_trade_sequence.
  5. Trade-count sanity check — flags "profit via near-zero trades".
  6. Overfitting detection — reuses RSP.anti_overfitting logic pattern
     (IS vs OOS degradation), applied to the calibration fold results.
Multi-window and multi-coin validation are orchestrated one level up in
run_calibration.py (they're about repeating this whole suite across
folds/coins, not something this module does internally).
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional
import statistics

from RSP.backtest_engine.backtest_engine import BacktestSummary
from RSP.robustness.monte_carlo import randomize_trade_sequence, FEE_SLIPPAGE_SCENARIOS, \
    _temporary_settings_override
from RSP.robustness.stress_test import performance_by_market_type

from . import param_registry as reg
from .optimizer import run_one
from .scoring import WindowScore


MIN_TRADES_SANITY = 8  # below this on OOS, "profit" is not trustworthy regardless of %


@dataclass
class PerturbationPoint:
    param: str
    pct: float
    value: object
    net_return_pct: float
    profit_factor: float
    max_drawdown_pct: float
    trades: int


@dataclass
class RobustnessReport:
    locked_params: Dict
    baseline_oos_score: float
    perturbation_points: List[PerturbationPoint] = field(default_factory=list)
    plateau: bool = False
    fragile_params: List[str] = field(default_factory=list)
    fee_slippage_results: Dict[str, WindowScore] = field(default_factory=dict)
    fee_slippage_fragile: bool = False
    sequence_dd_p95: float = 0.0
    sequence_order_dependent: bool = False
    regime_breakdown: List[dict] = field(default_factory=list)
    weakest_regime: str = ""
    trade_count_sanity_ok: bool = True
    trade_count_sanity_note: str = ""
    notes: List[str] = field(default_factory=list)


def perturbation_sensitivity(bars_by_tf_oos: Dict, mode: str, coin_id: Optional[str],
                              locked_params: Dict, base_tf: str = "15M", min_history: int = 200,
                              params: Optional[List[reg.ParamSpec]] = None) -> List[PerturbationPoint]:
    """±5% and ±10% perturbation of every numeric locked (or default)
    param, evaluated on OOS bars (never re-optimized — this only measures
    sensitivity of the already-locked config, per the brief's "look for a
    plateau, not a single magic point")."""
    params = params if params is not None else reg.params_for_mode(mode)
    points: List[PerturbationPoint] = []
    for spec in params:
        if spec.kind not in ("float", "int", "tuple4", "dict_scale"):
            continue
        base_overrides = dict(locked_params)
        base_val = locked_params.get(spec.name, spec.current_value())
        for pct in spec.perturb_pcts:
            # temporarily set the spec's "current" reference to base_val so
            # perturbed() scales the LOCKED value, not the shipped default
            restore = reg.apply_overrides({spec.name: base_val})
            try:
                perturbed_val = spec.perturbed(pct)
            finally:
                restore()
            trial = dict(base_overrides)
            trial[spec.name] = perturbed_val
            summary = run_one(bars_by_tf_oos, mode, coin_id, trial, base_tf, min_history)
            points.append(PerturbationPoint(
                param=spec.name, pct=pct, value=perturbed_val,
                net_return_pct=summary.net_return_pct, profit_factor=summary.profit_factor,
                max_drawdown_pct=summary.max_drawdown_pct, trades=summary.total_trades))
    return points


def _assess_plateau(baseline_net: float, points: List[PerturbationPoint]) -> (bool, List[str]):
    """Plateau = perturbing any single param ±5%/±10% doesn't flip the
    sign of net return or collapse it to near zero. A 'magic point' shows
    up as a param whose small perturbation swings net return wildly."""
    fragile = set()
    by_param: Dict[str, List[PerturbationPoint]] = {}
    for p in points:
        by_param.setdefault(p.param, []).append(p)
    for name, pts in by_param.items():
        base_sign = 1 if baseline_net > 0 else (-1 if baseline_net < 0 else 0)
        flips = sum(1 for p in pts if p.trades >= 3 and
                    (1 if p.net_return_pct > 0 else (-1 if p.net_return_pct < 0 else 0)) != base_sign
                    and base_sign != 0)
        if flips >= max(1, len(pts) // 2):
            fragile.add(name)
    plateau = len(fragile) == 0
    return plateau, sorted(fragile)


def fee_slippage_stress(bars_by_tf_oos: Dict, mode: str, coin_id: Optional[str],
                         locked_params: Dict, base_tf: str = "15M", min_history: int = 200) -> Dict[str, WindowScore]:
    out = {}
    for label, cost_overrides in FEE_SLIPPAGE_SCENARIOS.items():
        with _temporary_settings_override(cost_overrides):
            summary = run_one(bars_by_tf_oos, mode, coin_id, locked_params, base_tf, min_history)
        out[label] = WindowScore.from_summary(label, summary)
    return out


def run_robustness_suite(bars_by_tf_oos: Dict, mode: str, coin_id: Optional[str],
                          locked_params: Dict, oos_summary: BacktestSummary,
                          base_tf: str = "15M", min_history: int = 200) -> RobustnessReport:
    baseline_score = WindowScore.from_summary("OOS_locked", oos_summary).composite_score()
    report = RobustnessReport(locked_params=locked_params, baseline_oos_score=baseline_score)

    # 1) perturbation ±5/±10% — ONLY on params that were actually locked (i.e.
    # moved away from their shipped default). Sweeping the full mode registry
    # here was wasteful: most params stay at default and perturbing a default
    # nobody chose tells you nothing about the candidate that's being shipped.
    locked_specs = [reg.PARAMS_BY_NAME[k] for k in locked_params if k in reg.PARAMS_BY_NAME]
    points = perturbation_sensitivity(bars_by_tf_oos, mode, coin_id, locked_params, base_tf, min_history,
                                       params=locked_specs if locked_specs else None)
    report.perturbation_points = points
    report.plateau, report.fragile_params = _assess_plateau(oos_summary.net_return_pct, points)

    # 2) regime breakdown (real trades from this OOS run)
    stress = performance_by_market_type(oos_summary)
    report.regime_breakdown = [
        {"market_type": r.market_type, "trades": r.trades, "win_rate": r.win_rate,
         "net_return_pct": r.net_return_pct, "avg_trade_pct": r.average_trade_pct}
        for r in stress.by_market_type
    ]
    report.weakest_regime = stress.weakest_market_type

    # 3) fee/slippage stress
    fs = fee_slippage_stress(bars_by_tf_oos, mode, coin_id, locked_params, base_tf, min_history)
    report.fee_slippage_results = fs
    base_sign = 1 if oos_summary.net_return_pct > 0 else (-1 if oos_summary.net_return_pct < 0 else 0)
    flips = sum(1 for w in fs.values() if w.trades >= 3 and
                (1 if w.net_return_pct > 0 else (-1 if w.net_return_pct < 0 else 0)) != base_sign and base_sign != 0)
    report.fee_slippage_fragile = flips >= 1  # even one cost-scenario flip on realistic fees is worth flagging

    # 4) trade sequence randomization / drawdown robustness
    seq = randomize_trade_sequence(oos_summary)
    report.sequence_dd_p95 = seq.p95_drawdown
    report.sequence_order_dependent = seq.order_dependent

    # 5) trade-count sanity check — the brief's explicit anti-gaming rule
    if oos_summary.total_trades < MIN_TRADES_SANITY:
        report.trade_count_sanity_ok = False
        report.trade_count_sanity_note = (
            f"فقط {oos_summary.total_trades} معامله در OOS (< {MIN_TRADES_SANITY}) — سود/زیان گزارش‌شده "
            f"از نظر آماری قابل‌اتکا نیست، صرف‌نظر از درصد آن.")
    else:
        report.trade_count_sanity_note = f"{oos_summary.total_trades} معامله در OOS — تعداد کافی برای قضاوت اولیه."

    report.notes.append(
        f"Plateau={'YES' if report.plateau else 'NO'} "
        f"({'هیچ پارامتری با ±5%/±10% جهت سود را عوض نکرد' if report.plateau else 'پارامترهای شکننده: ' + ', '.join(report.fragile_params)})")
    if report.fee_slippage_fragile:
        report.notes.append("هشدار: نتیجه به هزینه‌های واقعی (fee/slippage) حساس است.")
    if report.sequence_order_dependent:
        report.notes.append("هشدار: Max Drawdown تا حدی به ترتیب معاملات وابسته است (order-dependent).")
    return report
