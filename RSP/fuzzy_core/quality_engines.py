"""
RSP — Fuzzy Quality Engines v2.0
PATCH: ATR history excludes current bar
"""

from dataclasses import dataclass, field
from typing import Dict, List
from ..config import settings
from ..fuzzy_core.bounded_uncertainty import rolling_percentile_score


@dataclass
class QualityResult:
    overall_score: float; components: Dict[str, float]; notes: List[str] = field(default_factory=list)


def evaluate_risk_quality(atr_pct: float, atr_pct_history: List[float],
                          risk_reward: float, risk_reward_history: List[float]) -> QualityResult:
    notes = []

    # FIX v2.0: History should already exclude current (from perception.py)
    vol_score = rolling_percentile_score(
        atr_pct, atr_pct_history,
        min_samples=settings.VOLATILITY_PERCENTILE_MIN_SAMPLES,
        target_samples=settings.VOLATILITY_PERCENTILE_TARGET_SAMPLES,
    )

    rr_score = rolling_percentile_score(
        risk_reward, risk_reward_history,
        min_samples=settings.RISK_QUALITY_PERCENTILE_MIN_SAMPLES,
        target_samples=settings.VOLATILITY_PERCENTILE_TARGET_SAMPLES,
    )

    overall = (vol_score + rr_score) / 2

    return QualityResult(overall_score=round(overall, 2), components={"volatility": vol_score, "risk_reward": rr_score}, notes=notes)
