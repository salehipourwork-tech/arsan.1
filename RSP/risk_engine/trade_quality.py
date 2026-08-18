"""
RSP — Trade Quality Engine v2.0
PATCH: Proper weights, volume quality, real gate
"""

from dataclasses import dataclass, field
from typing import Dict
from ..config import settings


@dataclass
class TradeQualityReport:
    overall_score: float; components: Dict[str, float]; notes: list


def assess_trade_quality(risk_plan, data_quality, regime, confluence) -> TradeQualityReport:
    notes = []

    # FIX v2.0: Proper weights
    weights = {
        "risk_reward": 0.30, "data_quality": 0.20, "regime_quality": 0.20,
        "volume_quality": 0.15, "setup_quality": 0.15,
    }

    rr = risk_plan.risk_reward if risk_plan else 0.0
    rr_score = min(100, rr * 30)

    # FIX v2.1: QualityReport's field is quality_score, not overall_score;
    # volatility_quality lives on regime.perception, not regime itself.
    dq = data_quality.quality_score if data_quality else 50.0

    rq = 80.0 if regime and regime.regime in settings.ALLOWED_REGIMES_FOR_TRADING else 30.0
    if regime and regime.perception is not None:
        rq = (rq + regime.perception.volatility_quality) / 2

    vol_usd = confluence.volume_usd if confluence else 0.0
    if vol_usd >= settings.MIN_VOLUME_USD * 2:
        volume_score = 100.0
    elif vol_usd >= settings.MIN_VOLUME_USD:
        volume_score = 70.0
    else:
        volume_score = 30.0
        notes.append("low_volume")

    setup_score = 70.0
    if confluence:
        if "LOW_VOLUME_SKIP" in confluence.tags:
            setup_score = 20.0
            notes.append("setup_rejected_low_volume")
        if confluence.rsi_divergence != "NONE":
            setup_score += 10.0

    components = {
        "risk_reward": rr_score, "data_quality": dq,
        "regime_quality": rq, "volume_quality": volume_score,
        "setup_quality": setup_score,
    }

    overall = sum(components[k] * weights[k] for k in weights)

    if overall < settings.MIN_TRADE_QUALITY_SCORE:
        notes.append(f"below_min_quality:{overall:.1f}<{settings.MIN_TRADE_QUALITY_SCORE}")

    return TradeQualityReport(overall_score=round(overall, 2), components=components, notes=notes)
