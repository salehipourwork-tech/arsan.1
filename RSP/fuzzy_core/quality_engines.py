"""
RSP — Fuzzy Quality Engines v2.1
PATCH v2.0: ATR history excludes current bar
FIX v2.1:
  - evaluate_risk_quality was broken: rolling_percentile_score() returns a
    BoundedScore object (or None when history is too short), but the code
    added it directly as if it were a float ("vol_score + rr_score"), which
    raises TypeError on every call. Now extracts .value and falls back to a
    neutral 50.0 score when there isn't enough history yet.
  - The package __init__.py expects 10 evaluate_*_quality functions from
    this module (Phase 29-38). Only evaluate_risk_quality actually existed;
    the other 9 were referenced but never implemented, which made the whole
    RSP.fuzzy_core package (and therefore the backtest engine) fail to
    import. Implemented below using the existing build_*_quality_variable()
    linguistic variables from membership.py, following the same pattern as
    evaluate_risk_quality: fuzzify a normalized [0,1] input, report the
    dominant fuzzy term, and return a 0-100 overall_score.

    NOTE ON SCOPE: nothing else in the codebase currently calls these 9
    functions with real trading data (grep shows the only references were
    the __init__.py import/export list). So this fix restores importability
    and gives each function a sensible, documented fuzzy-quality scoring
    behavior consistent with its Phase's linguistic variable — but it is
    NOT wired into decision_brain.py's live scoring path (which instead
    runs its own inference via fuzzy_core.inference / decision_controller).
    If you intended these 9 functions to drive actual trade decisions,
    double-check where each should be called from and what raw input each
    should receive.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence
from ..config import settings
from ..fuzzy_core.bounded_uncertainty import rolling_percentile_score
from ..fuzzy_core import membership as _mv


@dataclass
class QualityResult:
    overall_score: float; components: Dict[str, float]; notes: List[str] = field(default_factory=list)


def evaluate_risk_quality(atr_pct: float, atr_pct_history: List[float],
                          risk_reward: float, risk_reward_history: List[float]) -> QualityResult:
    notes = []

    # FIX v2.0: History should already exclude current (from perception.py)
    vol_bs = rolling_percentile_score(
        atr_pct, atr_pct_history,
        min_samples=settings.VOLATILITY_PERCENTILE_MIN_SAMPLES,
        target_samples=settings.VOLATILITY_PERCENTILE_TARGET_SAMPLES,
    )

    rr_bs = rolling_percentile_score(
        risk_reward, risk_reward_history,
        min_samples=settings.RISK_QUALITY_PERCENTILE_MIN_SAMPLES,
        target_samples=settings.VOLATILITY_PERCENTILE_TARGET_SAMPLES,
    )

    # FIX v2.1: rolling_percentile_score returns a BoundedScore (or None on
    # insufficient history) — not a plain float. Extract .value and fall
    # back to a neutral midpoint when history isn't deep enough yet.
    if vol_bs is None:
        vol_score = 50.0
        notes.append("insufficient_volatility_history_fallback_neutral")
    else:
        vol_score = round(vol_bs.value * 100, 2)

    if rr_bs is None:
        rr_score = 50.0
        notes.append("insufficient_risk_reward_history_fallback_neutral")
    else:
        rr_score = round(rr_bs.value * 100, 2)

    overall = (vol_score + rr_score) / 2

    return QualityResult(overall_score=round(overall, 2), components={"volatility": vol_score, "risk_reward": rr_score}, notes=notes)


def _evaluate_generic_quality(raw_score: float, build_variable_fn, label: str) -> QualityResult:
    """
    Shared implementation for the simple 0..1-input quality engines: fuzzify
    the normalized score against its Phase's linguistic variable, report the
    dominant term, and scale to a 0-100 overall_score.
    """
    x = max(0.0, min(1.0, raw_score))
    variable = build_variable_fn()
    degrees = variable.fuzzify(x)
    dominant = variable.dominant_term(degrees)
    overall = round(x * 100, 2)
    return QualityResult(
        overall_score=overall,
        components={k: round(v, 4) for k, v in degrees.items()},
        notes=[f"{label}_dominant_term={dominant}"],
    )


def evaluate_trend_quality(raw_score: float) -> QualityResult:
    """Phase 29 — raw_score: normalized [0,1] trend-strength input."""
    return _evaluate_generic_quality(raw_score, _mv.build_trend_quality_variable, "trend_quality")


def evaluate_momentum_quality(raw_score: float) -> QualityResult:
    """Phase 30 — raw_score: normalized [0,1] momentum-strength input."""
    return _evaluate_generic_quality(raw_score, _mv.build_momentum_quality_variable, "momentum_quality")


def evaluate_entry_quality(raw_score: float) -> QualityResult:
    """Phase 31 — raw_score: normalized [0,1] entry-timing quality input."""
    return _evaluate_generic_quality(raw_score, _mv.build_entry_quality_variable, "entry_quality")


def evaluate_volatility_quality(raw_score: float) -> QualityResult:
    """
    Phase 33 — raw_score: normalized [0,1] volatility badness input
    (higher = worse, per build_volatility_quality_variable's term shapes).
    If settings.USE_PERCENTILE_RISK_VOLATILITY is set, uses the v2
    percentile-calibrated variable instead (see membership.py docstring).
    """
    use_v2 = getattr(settings, "USE_PERCENTILE_RISK_VOLATILITY", False)
    build_fn = _mv.build_volatility_quality_variable_v2 if use_v2 else _mv.build_volatility_quality_variable
    return _evaluate_generic_quality(raw_score, build_fn, "volatility_quality")


def evaluate_market_stability(raw_score: float) -> QualityResult:
    """Phase 34 — raw_score: normalized [0,1] market-stability input."""
    return _evaluate_generic_quality(raw_score, _mv.build_market_stability_variable, "market_stability")


def evaluate_signal_strength(raw_score: float) -> QualityResult:
    """
    Phase 35 — raw_score: normalized [0,1] signal-strength input.
    NOTE: RSP.fuzzy_core.__init__ imports evaluate_signal_strength from
    BOTH this module and RSP.fuzzy_core.inference; the inference.py version
    (net_score -> FuzzySignalReport) is imported second and wins as the
    package-level export. This function exists so this module's own import
    block doesn't fail, and is directly importable as
    RSP.fuzzy_core.quality_engines.evaluate_signal_strength if needed.
    """
    return _evaluate_generic_quality(raw_score, _mv.build_signal_strength_variable, "signal_strength")


def evaluate_signal_confidence(raw_score: float) -> QualityResult:
    """Phase 36 — raw_score: normalized [0,1] signal-confidence input."""
    return _evaluate_generic_quality(raw_score, _mv.build_signal_confidence_variable, "signal_confidence")


def evaluate_contradiction_severity(raw_score: float) -> QualityResult:
    """Phase 37 — raw_score: normalized [0,1] contradiction severity (higher = worse)."""
    return _evaluate_generic_quality(raw_score, _mv.build_contradiction_severity_variable, "contradiction_severity")


def evaluate_opportunity_quality(raw_score: float) -> QualityResult:
    """Phase 38 — raw_score: normalized [0,1] opportunity-quality input."""
    return _evaluate_generic_quality(raw_score, _mv.build_opportunity_quality_variable, "opportunity_quality")
