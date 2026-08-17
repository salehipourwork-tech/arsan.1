"""
RSP — Multi-Timeframe Brain v2.0
PATCH: MTF Divergence Score added
"""

from dataclasses import dataclass, field
from typing import Dict, List
from ..config import settings


@dataclass
class MTFReport:
    context_bias: str; trend_bias: str; entry_bias: str
    agreement: bool; divergence_score: float; notes: List[str] = field(default_factory=list)


def analyze_mtf(bars_by_tf: Dict) -> MTFReport:
    def tf_trend(tf):
        df = bars_by_tf.get(tf)
        if df is None or len(df) < 3:
            return "NEUTRAL"
        c = df["close"]
        if c.iloc[-1] > c.iloc[-2] > c.iloc[-3]: return "UP"
        elif c.iloc[-1] < c.iloc[-2] < c.iloc[-3]: return "DOWN"
        return "NEUTRAL"

    context_trend = tf_trend("1D")
    trend_trend = tf_trend("4H")
    entry_trend = tf_trend("15M")

    agreement = context_trend == trend_trend == entry_trend and context_trend != "NEUTRAL"

    # FIX v2.0: Divergence detection
    divergence_score = 0.0
    notes = []

    if context_trend == "UP" and entry_trend == "DOWN":
        divergence_score = 0.8
        notes.append("bearish_divergence:1D_UP_15M_DOWN")
    elif context_trend == "DOWN" and entry_trend == "UP":
        divergence_score = 0.8
        notes.append("bullish_divergence:1D_DOWN_15M_UP")
    elif context_trend == "UP" and trend_trend == "DOWN":
        divergence_score = 0.5
        notes.append("medium_divergence:1D_UP_4H_DOWN")
    elif context_trend == "DOWN" and trend_trend == "UP":
        divergence_score = 0.5
        notes.append("medium_divergence:1D_DOWN_4H_UP")
    else:
        notes.append("no_divergence")

    return MTFReport(
        context_bias=context_trend, trend_bias=trend_trend,
        entry_bias=entry_trend, agreement=agreement,
        divergence_score=divergence_score, notes=notes,
    )
