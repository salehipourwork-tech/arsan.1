#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP.calibration.param_registry

Full inventory of every parameter in the pipeline that affects profit/risk
and can be legally tuned on IS data. Built by reading, top to bottom:
  RSP/config/settings.py, RSP/meta_controller/meta_controller.py,
  RSP/fuzzy_core/ahp_scoring.py, RSP/risk_engine/risk_engine.py,
  RSP/exit_manager.py.

Each ParamSpec knows:
  - where it actually lives (module + attribute name) so overrides land on
    the real object the engine reads, not just on settings.py — several
    live params (AHP_WEIGHTS, meta_controller's mode thresholds/weights)
    are plain module-level constants, NOT settings.* attributes, and a
    calibration system that only patches settings.py silently never
    touches them.
  - which mode(s) it applies to, so the optimizer only searches the
    subspace relevant to whichever mode is being calibrated.
  - a search grid (for calibration) and a perturbation scale (for the
    ±5%/±10% sensitivity/robustness pass) separately, because a coarse
    calibration grid and a fine sensitivity probe answer different
    questions.

Nothing here mutates anything on import. Callers apply/undo via
`apply_params()` / the returned restore closure.
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
import importlib

from RSP.config import settings as _settings
from RSP.meta_controller import meta_controller as _meta
from RSP.fuzzy_core import ahp_scoring as _ahp


MODE_BASELINE = "baseline"
MODE_FUZZY = "fuzzy"
MODE_AHP = "ahp"
MODE_META = "meta"
MODE_RISK = "risk"          # shared by every mode (SL/TP/ATR/RR/trailing/sizing)
ALL_MODES = (MODE_BASELINE, MODE_FUZZY, MODE_AHP, MODE_META, MODE_RISK)


@dataclass
class ParamSpec:
    name: str                       # unique key used in overrides dicts / reports
    module: Any                     # python module object the attribute lives on
    attr: str                       # attribute name on that module
    modes: Tuple[str, ...]          # which mode(s) this affects
    kind: str                       # "float" | "int" | "tuple4" | "dict_scale" | "bool" | "categorical"
    calibration_grid: List[Any] = field(default_factory=list)   # coarse candidates for search
    perturb_pcts: Tuple[float, ...] = (-0.10, -0.05, 0.05, 0.10)  # for sensitivity analysis
    bounds: Optional[Tuple[float, float]] = None  # hard sanity bounds (min, max)
    description: str = ""

    def current_value(self) -> Any:
        return getattr(self.module, self.attr)

    def perturbed(self, pct: float) -> Any:
        """Scale a numeric-ish value by (1+pct), respecting bounds. Non-numeric
        kinds (bool/categorical/dict_scale) are perturbed by their own rule."""
        cur = self.current_value()
        if self.kind == "float":
            v = cur * (1 + pct)
        elif self.kind == "int":
            v = max(1, round(cur * (1 + pct)))
        elif self.kind == "tuple4":
            v = tuple(round(x * (1 + pct), 4) for x in cur)
        elif self.kind == "dict_scale":
            # scale every numeric leaf of a flat {str: float} dict
            v = {k: round(val * (1 + pct), 4) for k, val in cur.items()}
        else:
            return cur  # bool/categorical/nested_dict: perturbation suite skips these
        if self.bounds and self.kind in ("float", "int"):
            lo, hi = self.bounds
            v = max(lo, min(hi, v))
        return v


def _reg(name, module, attr, modes, kind, grid, **kw) -> ParamSpec:
    return ParamSpec(name=name, module=module, attr=attr, modes=modes, kind=kind,
                      calibration_grid=grid, **kw)


# ---------------------------------------------------------------------------
# RISK — shared across every mode (SL, TP, ATR, RR, trailing, position sizing)
# ---------------------------------------------------------------------------
RISK_PARAMS: List[ParamSpec] = [
    _reg("rr_target", _settings, "RR_TARGET", (MODE_RISK,), "float",
         [1.5, 2.0, 2.5, 3.0, 3.5], bounds=(1.0, 5.0),
         description="Risk/Reward target used to place TP relative to SL distance"),
    _reg("sl_atr_multiplier", _settings, "SL_ATR_MULTIPLIER", (MODE_RISK,), "float",
         [1.0, 1.25, 1.5, 1.75, 2.0, 2.5], bounds=(0.5, 4.0),
         description="Stop-loss distance = ATR * this multiplier"),
    _reg("max_sl_distance_pct", _settings, "MAX_SL_DISTANCE_PCT", (MODE_RISK,), "float",
         [0.03, 0.04, 0.05, 0.07], bounds=(0.01, 0.15),
         description="Hard cap on SL distance as % of entry price"),
    _reg("max_risk_percent_per_trade", _settings, "MAX_RISK_PERCENT_PER_TRADE", (MODE_RISK,), "float",
         [0.5, 1.0, 1.5, 2.0], bounds=(0.1, 3.0),
         description="Position sizing: % of account risked per trade"),
    _reg("min_acceptable_rr", _settings, "MIN_ACCEPTABLE_RISK_REWARD", (MODE_RISK,), "float",
         [1.2, 1.5, 1.8, 2.0], bounds=(1.0, 3.0),
         description="Floor RR below which a risk plan is rejected outright"),
    _reg("atr_period", _settings, "ATR_PERIOD", (MODE_RISK,), "int",
         [10, 14, 20], bounds=(5, 30),
         description="ATR lookback period feeding SL/TP distance"),
    _reg("trailing_stop_enabled", _settings, "TRAILING_STOP_ENABLED", (MODE_RISK,), "bool",
         [False, True],
         description="ATR-based trailing stop instead of fixed SL/TP"),
    _reg("trailing_activate_atr", _settings, "TRAILING_ACTIVATE_ATR", (MODE_RISK,), "float",
         [0.5, 1.0, 1.5, 2.0], bounds=(0.25, 3.0),
         description="Profit (in ATR multiples) before trailing stop arms"),
    _reg("trailing_atr", _settings, "TRAILING_ATR", (MODE_RISK,), "float",
         [0.75, 1.0, 1.25, 1.5], bounds=(0.25, 3.0),
         description="Trailing distance behind price, in ATR multiples"),
    _reg("min_trade_distance_bars", _settings, "MIN_TRADE_DISTANCE_BARS", (MODE_RISK,), "int",
         [6, 12, 18, 24], bounds=(1, 50),
         description="Minimum bars between two trades (overtrading control)"),
    _reg("cooldown_after_sl", _settings, "COOLDOWN_BARS_AFTER_STOP_LOSS", (MODE_RISK,), "int",
         [3, 6, 9, 12], bounds=(0, 30),
         description="Bars to wait after a stopped-out trade before re-entry"),
    _reg("cooldown_after_tp", _settings, "COOLDOWN_BARS_AFTER_TAKE_PROFIT", (MODE_RISK,), "int",
         [0, 3, 6], bounds=(0, 30),
         description="Bars to wait after a winning trade before re-entry"),
    _reg("daily_max_trades", _settings, "DAILY_MAX_TRADES", (MODE_RISK,), "int",
         [3, 5, 8, 12], bounds=(1, 30),
         description="Hard cap on trades per day (guards against overtrading masking risk)"),
]

# ---------------------------------------------------------------------------
# BASELINE — gating / regime / signal-weighting parameters active even with
# fuzzy/ahp/meta all off
# ---------------------------------------------------------------------------
BASELINE_PARAMS: List[ParamSpec] = [
    _reg("min_confidence_to_trade", _settings, "MIN_CONFIDENCE_TO_TRADE", (MODE_BASELINE,), "float",
         [45.0, 50.0, 55.0, 60.0, 65.0], bounds=(20.0, 85.0),
         description="Decision-Brain confidence gate"),
    _reg("min_trade_quality_score", _settings, "MIN_TRADE_QUALITY_SCORE", (MODE_BASELINE,), "float",
         [50.0, 55.0, 60.0, 65.0, 70.0], bounds=(20.0, 90.0),
         description="Trade-Quality-Engine gate"),
    _reg("contradiction_block_threshold", _settings, "CONTRADICTION_BLOCK_THRESHOLD", (MODE_BASELINE,), "float",
         [0.10, 0.15, 0.20, 0.25], bounds=(0.0, 0.5),
         description="Contradiction ratio above which a trade is blocked"),
    _reg("exhaustion_net_score_threshold", _settings, "EXHAUSTION_NET_SCORE_THRESHOLD", (MODE_BASELINE,), "float",
         [0.60, 0.65, 0.70, 0.75, 0.80], bounds=(0.4, 0.95),
         description="Exhaustion filter threshold on net evidence score"),
    _reg("mtf_sma_fast", _settings, "MTF_TREND_SMA_FAST", (MODE_BASELINE,), "int",
         [5, 8, 10, 14], bounds=(3, 30),
         description="MTF fast SMA period"),
    _reg("mtf_sma_slow", _settings, "MTF_TREND_SMA_SLOW", (MODE_BASELINE,), "int",
         [15, 20, 25, 30], bounds=(10, 60),
         description="MTF slow SMA period"),
    _reg("mtf_threshold_pct", _settings, "MTF_TREND_THRESHOLD_PCT", (MODE_BASELINE,), "float",
         [0.0005, 0.001, 0.0015, 0.002], bounds=(0.0001, 0.01),
         description="Minimum fast/slow SMA separation to call a trend up/down"),
    _reg("min_volume_usd", _settings, "MIN_VOLUME_USD", (MODE_BASELINE,), "float",
         [500_000, 1_000_000, 2_000_000], bounds=(0, 1e8),
         description="Liquidity gate"),
]

# ---------------------------------------------------------------------------
# FUZZY — membership breakpoints, rule-output calibration, opportunity gate
# ---------------------------------------------------------------------------
FUZZY_PARAMS: List[ParamSpec] = [
    _reg("mf_trend", _settings, "FUZZY_MF_TREND", (MODE_FUZZY,), "tuple4",
         [(0.15, 0.33, 0.58, 0.80), (0.20, 0.40, 0.65, 0.85), (0.25, 0.47, 0.72, 0.90)],
         description="Trend-quality membership breakpoints (weak/mod/strong/extreme)"),
    _reg("mf_momentum", _settings, "FUZZY_MF_MOMENTUM", (MODE_FUZZY,), "tuple4",
         [(0.18, 0.38, 0.63, 0.83), (0.25, 0.45, 0.70, 0.88), (0.30, 0.52, 0.77, 0.93)],
         description="Momentum-quality membership breakpoints"),
    _reg("mf_entry", _settings, "FUZZY_MF_ENTRY", (MODE_FUZZY,), "tuple4",
         [(0.15, 0.33, 0.58, 0.80), (0.20, 0.40, 0.65, 0.85), (0.25, 0.47, 0.72, 0.90)],
         description="Entry-quality membership breakpoints"),
    _reg("mf_risk", _settings, "FUZZY_MF_RISK", (MODE_FUZZY,), "tuple4",
         [(0.18, 0.38, 0.63, 0.85), (0.25, 0.45, 0.70, 0.90), (0.30, 0.52, 0.77, 0.95)],
         description="Risk-quality membership breakpoints"),
    _reg("mf_stability", _settings, "FUZZY_MF_STABILITY", (MODE_FUZZY,), "tuple4",
         [(0.15, 0.33, 0.58, 0.80), (0.20, 0.40, 0.65, 0.85)],
         description="Stability-quality membership breakpoints"),
    _reg("mf_confidence", _settings, "FUZZY_MF_CONFIDENCE", (MODE_FUZZY,), "tuple4",
         [(0.20, 0.40, 0.65, 0.85), (0.25, 0.45, 0.70, 0.88)],
         description="Confidence-quality membership breakpoints"),
    _reg("rule_output_multiplier", _settings, "FUZZY_RULE_OUTPUT_MULTIPLIER", (MODE_FUZZY,), "float",
         [0.9, 0.95, 1.0, 1.05, 1.1], bounds=(0.7, 1.3),
         description="Uniform scale applied to every fuzzy rule output singleton"),
    _reg("rule_output_offset", _settings, "FUZZY_RULE_OUTPUT_OFFSET", (MODE_FUZZY,), "float",
         [-8.0, -4.0, 0.0, 4.0, 8.0], bounds=(-20.0, 20.0),
         description="Uniform offset applied to every fuzzy rule output singleton"),
    _reg("opp_threshold_rules", _settings, "FUZZY_OPPORTUNITY_THRESHOLD_BY_METHOD", (MODE_FUZZY, MODE_AHP), "dict_scale",
         [{"rules": 64.0, "ahp": 50.0}, {"rules": 72.0, "ahp": 58.0}, {"rules": 78.0, "ahp": 64.0}],
         description="Per-method opportunity-score gate (rules vs ahp on different natural scales)"),
    _reg("fuzzy_hysteresis_drop", _settings, "FUZZY_HYSTERESIS_DROP", (MODE_FUZZY,), "float",
         [15.0, 20.0, 25.0, 30.0], bounds=(5.0, 40.0),
         description="Score drop required to flip a stable decision (anti flip-flop)"),
    _reg("fuzzy_stability_min_consistent", _settings, "FUZZY_STABILITY_MIN_CONSISTENT", (MODE_FUZZY,), "int",
         [2, 3, 4], bounds=(1, 6),
         description="Consecutive-bar agreement required before acting on a fuzzy signal"),
    _reg("fuzzy_trade_permission_min", _settings, "FUZZY_TRADE_PERMISSION_MIN", (MODE_FUZZY,), "float",
         [40.0, 50.0, 60.0], bounds=(10.0, 80.0),
         description="Floor permission score to allow a trade at all"),
]

# ---------------------------------------------------------------------------
# AHP — pairwise-derived weights + opportunity score
# ---------------------------------------------------------------------------
AHP_PARAMS: List[ParamSpec] = [
    _reg("ahp_weights", _ahp, "AHP_WEIGHTS", (MODE_AHP,), "dict_scale",
         [
             {"trend_quality": 0.25, "risk_quality_v2": 0.40, "volatility_quality_v2": 0.25, "entry_quality": 0.10},
             {"trend_quality": 0.30, "risk_quality_v2": 0.35, "volatility_quality_v2": 0.25, "entry_quality": 0.10},
             {"trend_quality": 0.35, "risk_quality_v2": 0.30, "volatility_quality_v2": 0.20, "entry_quality": 0.15},
         ],
         description="AHP compensatory weights over trend/risk/volatility/entry quality "
                      "(module-level constant in fuzzy_core/ahp_scoring.py, NOT settings.py)"),
]

# ---------------------------------------------------------------------------
# META — mode thresholds, blend weights, memory/decay, trade threshold
# ---------------------------------------------------------------------------
META_PARAMS: List[ParamSpec] = [
    _reg("meta_vol_defensive_pct", _meta, "VOLATILITY_DEFENSIVE_PCT", (MODE_META,), "float",
         [65.0, 70.0, 75.0, 80.0], bounds=(40.0, 95.0),
         description="Volatility percentile above which Meta enters DEFENSIVE mode"),
    _reg("meta_vol_preservation_pct", _meta, "VOLATILITY_PRESERVATION_PCT", (MODE_META,), "float",
         [85.0, 90.0, 93.0], bounds=(70.0, 99.0),
         description="Volatility percentile above which Meta enters PRESERVATION (no-trade) mode"),
    _reg("meta_rules_win_rate_min", _meta, "RULES_WIN_RATE_MIN", (MODE_META,), "float",
         [0.25, 0.30, 0.35, 0.40], bounds=(0.1, 0.6),
         description="Recent Rules-engine win rate floor before Meta demotes it to DEFENSIVE"),
    _reg("meta_adaptive_window", _meta, "META_ADAPTIVE_WINDOW", (MODE_META,), "int",
         [10, 15, 20, 30], bounds=(5, 60),
         description="Rolling trade-count window used for recent_win_rate (learning-rate proxy)"),
    _reg("meta_history_maxlen", _meta, "META_HISTORY_MAXLEN", (MODE_META,), "int",
         [50, 100, 150, 200], bounds=(20, 500),
         description="Max trades kept in per-engine memory (decay horizon)"),
    _reg("meta_trade_threshold", _meta, "META_TRADE_THRESHOLD", (MODE_META,), "float",
         [0.25, 0.30, 0.35, 0.40, 0.45], bounds=(0.1, 0.6),
         description="Minimum fused vote score required to act (was hardcoded; now tunable)"),
    _reg("meta_mode_weights", _meta, "MODE_WEIGHTS", (MODE_META,), "nested_dict",
         [
             {"OPPORTUNITY": {"rules": 0.75, "ahp": 0.25, "no_trade": 0.0},
              "DEFENSIVE": {"rules": 0.30, "ahp": 0.70, "no_trade": 0.0},
              "PRESERVATION": {"rules": 0.0, "ahp": 0.0, "no_trade": 1.0}},
             {"OPPORTUNITY": {"rules": 0.85, "ahp": 0.15, "no_trade": 0.0},
              "DEFENSIVE": {"rules": 0.20, "ahp": 0.80, "no_trade": 0.0},
              "PRESERVATION": {"rules": 0.0, "ahp": 0.0, "no_trade": 1.0}},
             {"OPPORTUNITY": {"rules": 0.90, "ahp": 0.10, "no_trade": 0.0},
              "DEFENSIVE": {"rules": 0.10, "ahp": 0.90, "no_trade": 0.0},
              "PRESERVATION": {"rules": 0.0, "ahp": 0.0, "no_trade": 1.0}},
         ],
         perturb_pcts=(),  # nested dict-of-dicts: not scaled by the generic ±pct rule, grid-only
         description="Rules/AHP/no-trade blend weights per Meta mode (nested dict, module-level "
                      "constant on meta_controller.py) — calibrated via discrete grid only, "
                      "excluded from the generic ±% sensitivity pass"),
]

ALL_PARAMS: List[ParamSpec] = RISK_PARAMS + BASELINE_PARAMS + FUZZY_PARAMS + AHP_PARAMS + META_PARAMS
PARAMS_BY_NAME: Dict[str, ParamSpec] = {p.name: p for p in ALL_PARAMS}


def params_for_mode(mode: str, include_risk: bool = True) -> List[ParamSpec]:
    """Every param relevant to `mode`, optionally including shared RISK params
    (default True — risk knobs affect every mode's realized P&L)."""
    out = [p for p in ALL_PARAMS if mode in p.modes]
    if include_risk and mode != MODE_RISK:
        out += [p for p in ALL_PARAMS if MODE_RISK in p.modes]
    return out


def apply_overrides(overrides: Dict[str, Any]) -> Callable[[], None]:
    """
    Apply {param_name: value} onto the real module attributes. Returns a
    zero-arg restore() closure. Never touches anything not explicitly
    listed in `overrides` — safe to call repeatedly/nested is NOT supported
    (use one apply/restore pair per scope, mirroring
    settings.temporary_override's contract).
    """
    originals: Dict[str, Any] = {}
    for name, value in overrides.items():
        spec = PARAMS_BY_NAME.get(name)
        if spec is None:
            raise KeyError(f"Unknown calibration parameter: {name}")
        originals[name] = getattr(spec.module, spec.attr)
        setattr(spec.module, spec.attr, value)

    def restore():
        for name, value in originals.items():
            spec = PARAMS_BY_NAME[name]
            setattr(spec.module, spec.attr, value)

    return restore


class override_scope:
    """Context-manager wrapper around apply_overrides for convenience."""
    def __init__(self, overrides: Dict[str, Any]):
        self.overrides = overrides
        self._restore = None

    def __enter__(self):
        self._restore = apply_overrides(self.overrides)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._restore:
            self._restore()
        return False


def snapshot_all() -> Dict[str, Any]:
    """Full current value of every registered parameter (for before/after logs)."""
    return {p.name: p.current_value() for p in ALL_PARAMS}
