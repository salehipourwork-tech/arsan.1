"""
RSP — Regime Perception v2.1
PATCH: ADX calibrated for crypto 15M, ATR history excludes current
FIX v2.1: renamed to perceive_market()/PerceptionReport to match the
contract expected by regime_engine.py (perception.state was previously
never computed — always returned as an empty string).
"""

from dataclasses import dataclass, field
from typing import Optional, List
import numpy as np
import pandas_ta as ta
import pandas as pd
from ..config import settings


@dataclass
class PerceptionReport:
    state: str; adx: float; adx_trending: bool; adx_strong: bool
    ema_alignment: str; price_vs_ema: str; atr_pct: float
    atr_pct_series: List[float] = field(default_factory=list)
    volatility_regime: str = ""; volatility_quality: float = 0.0
    notes: List[str] = field(default_factory=list)

    @property
    def regime(self) -> str:
        """Backward-compat alias — some older callers may read .regime."""
        return self.state


def _classify_state(ema_alignment: str, adx_trending: bool, adx_strong: bool,
                     range_zone: bool, vol_regime: str) -> str:
    """
    Maps the raw perception signals onto RSP.config.settings.REGIME_LABELS.
    This classification step was missing before (v2.0 always returned "").
    """
    if vol_regime == "EXTREME":
        return "HIGH_VOLATILITY"
    if ema_alignment == "BULLISH_ALIGNED":
        if adx_strong:
            return "STRONG_UPTREND"
        if adx_trending:
            return "UPTREND"
        return "WEAK_UPTREND"
    if ema_alignment == "BEARISH_ALIGNED":
        if adx_strong:
            return "STRONG_DOWNTREND"
        if adx_trending:
            return "DOWNTREND"
        return "WEAK_DOWNTREND"
    # MIXED alignment
    if vol_regime == "LOW":
        return "LOW_VOLATILITY"
    if range_zone:
        return "RANGE"
    return "TRANSITION"


def perceive_market(df: pd.DataFrame) -> PerceptionReport:
    close = df["close"]; high = df["high"]; low = df["low"]

    ema20 = ta.ema(close, length=20)
    ema50 = ta.ema(close, length=50)
    ema200 = ta.ema(close, length=200)

    adx_df = ta.adx(high, low, close, length=14)
    adx_val = adx_df["ADX_14"].iloc[-1] if adx_df is not None else 0.0

    atr_series = ta.atr(high, low, close, length=14)
    atr_pct_full = (atr_series / close) * 100
    atr_pct = atr_pct_full.iloc[-1] if atr_pct_full is not None else 0.0

    # FIX v2.0: Calibrated for crypto 15M
    adx_trending = adx_val >= 30  # was 20
    adx_strong = adx_val >= 45    # was 35
    range_zone = adx_val < 25     # was < 20

    last_close = close.iloc[-1]
    ema20_val = ema20.iloc[-1] if ema20 is not None else last_close
    ema50_val = ema50.iloc[-1] if ema50 is not None else last_close
    ema200_val = ema200.iloc[-1] if ema200 is not None else last_close

    if last_close > ema20_val > ema50_val > ema200_val:
        ema_alignment = "BULLISH_ALIGNED"
    elif last_close < ema20_val < ema50_val < ema200_val:
        ema_alignment = "BEARISH_ALIGNED"
    else:
        ema_alignment = "MIXED"

    price_vs_ema = "ABOVE_EMA20" if last_close > ema20_val else "BELOW_EMA20"

    vol_regime = "NORMAL"
    if atr_pct > 5.0: vol_regime = "EXTREME"
    elif atr_pct > 3.0: vol_regime = "HIGH"
    elif atr_pct < 1.0: vol_regime = "LOW"

    # FIX v2.0: Exclude current bar from history
    atr_pct_history = atr_pct_full.iloc[:-1].tail(500).tolist()
    atr_pct_series = [round(v, 3) for v in atr_pct_history if not np.isnan(v)]

    if len(atr_pct_series) >= settings.VOLATILITY_PERCENTILE_MIN_SAMPLES:
        sorted_hist = sorted(atr_pct_series)
        rank = sum(1 for v in sorted_hist if v <= atr_pct) / len(sorted_hist)
        vol_quality = rank * 100
    else:
        vol_quality = 50.0

    notes = []
    if adx_trending and not adx_strong: notes.append("trending_weak")
    if adx_strong: notes.append("trending_strong")
    if range_zone: notes.append("range_zone")

    state = _classify_state(ema_alignment, adx_trending, adx_strong, range_zone, vol_regime)

    return PerceptionReport(
        state=state, adx=round(adx_val, 2), adx_trending=adx_trending,
        adx_strong=adx_strong, ema_alignment=ema_alignment,
        price_vs_ema=price_vs_ema, atr_pct=round(atr_pct, 4),
        atr_pct_series=atr_pct_series, volatility_regime=vol_regime,
        volatility_quality=round(vol_quality, 2), notes=notes,
    )


# Backward-compat aliases (in case anything else in the repo still imports
# the old v2.0 names).
RegimePerceptionReport = PerceptionReport
analyze_regime_perception = perceive_market
