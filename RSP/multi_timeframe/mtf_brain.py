"""
RSP — Multi-Timeframe Brain v2.0
PATCH: MTF Divergence Score added
"""

from dataclasses import dataclass, field
from typing import Dict, List
import pandas as pd
from ..config import settings


_TREND_TO_SCORE = {"UP": 1.0, "DOWN": -1.0, "NEUTRAL": 0.0}


@dataclass
class MTFReport:
    context_bias: str; trend_bias: str; entry_bias: str
    agreement: bool; divergence_score: float; notes: List[str] = field(default_factory=list)

    # FIX v2.1: several callers (contradiction_engine.py, fusion_engine.py)
    # expected .aligned / .summary / .consensus_score which were never
    # defined here. Added as derived properties instead of duplicating
    # storage, so they always stay consistent with the raw fields.
    @property
    def aligned(self) -> bool:
        return self.agreement

    @property
    def consensus_score(self) -> float:
        raw = (_TREND_TO_SCORE.get(self.context_bias, 0.0)
               + _TREND_TO_SCORE.get(self.trend_bias, 0.0)
               + _TREND_TO_SCORE.get(self.entry_bias, 0.0)) / 3.0
        damped = raw * (1.0 - min(1.0, self.divergence_score))
        return round(max(-1.0, min(1.0, damped)), 4)

    @property
    def summary(self) -> str:
        return (f"1D={self.context_bias}/4H={self.trend_bias}/15M={self.entry_bias} "
                f"agreement={self.agreement} divergence={self.divergence_score:.2f}")


def analyze_mtf(bars_by_tf: Dict) -> MTFReport:
    def tf_trend(tf):
        # FIX v2.1: was `c[-1] > c[-2] > c[-3]` (3-strictly-monotonic-closes)
        # — essentially a noise detector, almost never true on real candles,
        # which made entry_bias (15M) stuck at NEUTRAL and MTF agreement
        # nearly impossible. Standard fast/slow SMA cross with a noise
        # threshold instead.
        df = bars_by_tf.get(tf)
        slow_n = settings.MTF_TREND_SMA_SLOW
        if df is None or len(df) < slow_n:
            return "NEUTRAL"
        c = df["close"]
        sma_fast = c.rolling(settings.MTF_TREND_SMA_FAST).mean().iloc[-1]
        sma_slow = c.rolling(slow_n).mean().iloc[-1]
        if sma_slow == 0 or pd.isna(sma_fast) or pd.isna(sma_slow):
            return "NEUTRAL"
        pct_diff = (sma_fast - sma_slow) / sma_slow
        if pct_diff > settings.MTF_TREND_THRESHOLD_PCT:
            return "UP"
        elif pct_diff < -settings.MTF_TREND_THRESHOLD_PCT:
            return "DOWN"
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
