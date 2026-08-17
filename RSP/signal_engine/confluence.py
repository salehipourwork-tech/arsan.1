"""
RSP — Signal Confluence Engine v2.0
PATCH: Volume USD filter, LOW_VOLUME_SKIP tag
"""

from dataclasses import dataclass, field
from typing import List
import pandas_ta as ta
from ..config import settings


@dataclass
class ConfluenceReport:
    signal: str; strength: float; rsi: float; rsi_divergence: str
    volume_trend: str; volume_strength: float; volume_usd: float
    ema_alignment: str; trend_strength: float; tags: List[str] = field(default_factory=list)


def analyze_confluence(df, regime) -> ConfluenceReport:
    close = df["close"]; volume = df["volume"]; high = df["high"]; low = df["low"]

    rsi_series = ta.rsi(close, length=14)
    rsi = rsi_series.iloc[-1] if rsi_series is not None else 50.0

    rsi_divergence = "NONE"
    if len(rsi_series) >= 5 and len(close) >= 5:
        if close.iloc[-1] > close.iloc[-5] and rsi_series.iloc[-1] < rsi_series.iloc[-5]:
            rsi_divergence = "BEARISH"
        if close.iloc[-1] < close.iloc[-5] and rsi_series.iloc[-1] > rsi_series.iloc[-5]:
            rsi_divergence = "BULLISH"

    vol_sma = volume.rolling(20).mean()
    latest_vol = volume.iloc[-1]
    avg_vol = vol_sma.iloc[-1] if vol_sma is not None else latest_vol
    volume_trend = "INCREASING" if latest_vol > avg_vol * 1.2 else "DECREASING" if latest_vol < avg_vol * 0.8 else "NEUTRAL"
    volume_strength = min(100, (latest_vol / avg_vol) * 50) if avg_vol > 0 else 50.0

    latest_close = close.iloc[-1]
    volume_usd = latest_vol * latest_close

    ema20 = ta.ema(close, length=20)
    ema50 = ta.ema(close, length=50)
    ema20_val = ema20.iloc[-1] if ema20 is not None else latest_close
    ema50_val = ema50.iloc[-1] if ema50 is not None else latest_close
    ema_alignment = "BULLISH" if ema20_val > ema50_val else "BEARISH"

    adx_series = ta.adx(high, low, close, length=14)
    adx_val = adx_series["ADX_14"].iloc[-1] if adx_series is not None else 20.0
    trend_strength = min(100, adx_val * 2)

    if rsi > 70 and volume_trend == "INCREASING":
        signal, strength = "SELL", 0.7
    elif rsi < 30 and volume_trend == "INCREASING":
        signal, strength = "BUY", 0.7
    elif ema_alignment == "BULLISH" and trend_strength > 50:
        signal, strength = "BUY", 0.5
    elif ema_alignment == "BEARISH" and trend_strength > 50:
        signal, strength = "SELL", 0.5
    else:
        signal, strength = "HOLD", 0.3

    tags = []
    if rsi_divergence != "NONE":
        tags.append(f"rsi_divergence_{rsi_divergence}")

    # FIX v2.0: Volume filter
    if volume_usd < settings.MIN_VOLUME_USD:
        tags.append("LOW_VOLUME_SKIP")
        signal, strength = "HOLD", 0.0

    return ConfluenceReport(
        signal=signal, strength=strength, rsi=round(rsi, 2),
        rsi_divergence=rsi_divergence, volume_trend=volume_trend,
        volume_strength=round(volume_strength, 2), volume_usd=round(volume_usd, 2),
        ema_alignment=ema_alignment, trend_strength=round(trend_strength, 2), tags=tags,
    )
