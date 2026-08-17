"""
RSP — Confidence Engine v2.0
PATCH: Rebalanced weights, less regime-label bias
"""

from dataclasses import dataclass
from typing import Optional
from ..config import settings


@dataclass
class ConfidenceReport:
    confidence: float; components: dict; notes: list


def calculate_confidence(fusion, mtf, data_quality, risk_plan, contradiction, regime) -> ConfidenceReport:
    notes = []

    # FIX v2.0: Rebalanced weights
    weights = {
        "signal_agreement": 0.30,   # was 0.55
        "mtf_agreement": 0.20,      # was 0.30
        "stability": 0.05,          # was 0.03
        "data_quality": 0.15,       # was 0.05
        "volatility": 0.05,         # was 0.02
        "risk_reward": 0.15,        # was 0.05
        "contradiction_penalty": 0.10,  # NEW
    }

    signal_agreement = min(abs(fusion.net_score) * 100, 100) if fusion else 50.0
    mtf_agreement = 100.0 if mtf and mtf.agreement else 50.0
    stability = 100.0 if fusion and fusion.stability else 50.0
    data_quality_score = data_quality.overall_score if data_quality else 50.0
    vol_quality = regime.volatility_quality if regime else 50.0
    rr_score = min(risk_plan.risk_reward_pct, 100) if risk_plan else 50.0

    contradiction_score = 100.0
    if contradiction and contradiction.severity > settings.CONTRADICTION_SEVERE_THRESHOLD:
        contradiction_score = max(0, 100 - contradiction.severity * 100)
        notes.append(f"severe_contradiction_penalty:{contradiction.severity:.2f}")
    elif contradiction and contradiction.severity > settings.CONTRADICTION_BLOCK_THRESHOLD:
        contradiction_score = max(50, 100 - contradiction.severity * 50)

    components = {
        "signal_agreement": signal_agreement, "mtf_agreement": mtf_agreement,
        "stability": stability, "data_quality": data_quality_score,
        "volatility": vol_quality, "risk_reward": rr_score,
        "contradiction_penalty": contradiction_score,
    }

    confidence = sum(components[k] * weights[k] for k in weights)
    confidence = max(0, min(100, confidence))

    return ConfidenceReport(confidence=round(confidence, 2), components=components, notes=notes)
