"""
RSP — regime_engine/perception.py  (Phase 4: MARKET PERCEPTION ENGINE)

قبل از پرسیدن BUY/SELL، این ماژول می‌پرسد: «الان چه نوع بازاری داریم؟»
از ترکیب Trend (EMA slope) + ADX + Price Structure + Volatility (ATR%) +
Volume + Momentum (RSI) استفاده می‌کند - نه یک اندیکاتور تنها.
"""

from dataclasses import dataclass, field
from typing import List
import pandas as pd

from RSP.indicators import technical as ta


@dataclass
class PerceptionReport:
    state: str = "UNKNOWN"
    evidence: List[str] = field(default_factory=list)
    ema20_slope_pct: float = 0.0
    adx_value: float = 0.0
    atr_pct: float = 0.0
    rsi_value: float = 50.0
    volume_trend: str = "UNKNOWN"
    # تاریخچه‌ی ATR% (فقط تا همین کندل، هرگز آینده) — برای Bounded Uncertainty /
    # percentile-based scoring در volatility_quality و risk_quality. چون از همان
    # df ورودی (که خودش قبلاً توسط caller به تاریخچه‌ی تا لحظه‌ی تصمیم محدود شده)
    # ساخته می‌شود، ذاتاً walk-forward-safe است.
    atr_pct_series: List[float] = field(default_factory=list)


def perceive_market(df: pd.DataFrame) -> PerceptionReport:
    report = PerceptionReport()
    if df.empty or len(df) < 25:
        report.state = "UNKNOWN"
        report.evidence.append("INSUFFICIENT_DATA")
        return report

    close, high, low, volume = df["close"], df["high"], df["low"], df["volume"]

    ema20 = ta.ema(close, 20)
    ema50 = ta.ema(close, 50) if len(close) >= 50 else ema20
    adx_series, plus_di, minus_di = ta.adx(high, low, close, 14)
    atr_series = ta.atr(high, low, close, 14)
    rsi_series = ta.rsi(close, 14)

    ema20_last = ta.last(ema20, close.iloc[-1])
    ema20_prev = ta.last(ema20.iloc[:-5], ema20_last) if len(ema20) > 5 else ema20_last
    slope_pct = ((ema20_last - ema20_prev) / ema20_prev * 100) if ema20_prev else 0.0

    adx_val = ta.last(adx_series, 15.0)
    atr_val = ta.last(atr_series, 0.0)
    atr_pct = (atr_val / close.iloc[-1] * 100) if close.iloc[-1] else 0.0
    rsi_val = ta.last(rsi_series, 50.0)
    plus_di_val = ta.last(plus_di, 0.0)
    minus_di_val = ta.last(minus_di, 0.0)

    report.ema20_slope_pct = round(slope_pct, 3)
    report.adx_value = round(adx_val, 2)
    report.atr_pct = round(atr_pct, 3)
    report.rsi_value = round(rsi_val, 2)

    # atr_series از ta.atr همین‌جا محاسبه شده؛ فقط به % close تبدیل و به یک
    # پنجره‌ی محدود (حداکثر ۵۰۰ کندل گذشته) کپ می‌کنیم — منطق ATR تغییری نکرده،
    # فقط یک نمای تاریخی از همان مقدار برای caller اضافه می‌شود.
    try:
        atr_pct_full = (atr_series / close * 100).dropna()
        report.atr_pct_series = [round(v, 3) for v in atr_pct_full.tail(500).tolist()]
    except Exception:
        report.atr_pct_series = []

    recent_vol = volume.iloc[-10:].mean()
    prior_vol = volume.iloc[-20:-10].mean() if len(volume) >= 20 else recent_vol
    if prior_vol and prior_vol > 0:
        vol_change = (recent_vol - prior_vol) / prior_vol
        report.volume_trend = "RISING" if vol_change > 0.15 else ("FALLING" if vol_change < -0.15 else "STABLE")
    else:
        report.volume_trend = "UNKNOWN"

    trending = adx_val >= 20
    strong_trend = adx_val >= 35
    bullish_dir = plus_di_val > minus_di_val
    high_vol = atr_pct > 4.0
    low_vol = atr_pct < 1.0

    price_above_ema50 = close.iloc[-1] > ta.last(ema50, close.iloc[-1])

    if high_vol and adx_val < 15:
        report.state = "HIGH_VOLATILITY"
        report.evidence.append(f"ATR% {atr_pct:.2f} > 4 با ADX پایین -> نوسان بدون جهت مشخص")
    elif low_vol and adx_val < 15:
        report.state = "LOW_VOLATILITY"
        report.evidence.append(f"ATR% {atr_pct:.2f} < 1 -> نوسان کم")
    elif not trending:
        report.state = "RANGE"
        report.evidence.append(f"ADX {adx_val:.1f} < 20 -> بدون روند مشخص")
    elif trending and bullish_dir and price_above_ema50:
        report.state = "STRONG_UPTREND" if strong_trend else ("UPTREND" if adx_val >= 25 else "WEAK_UPTREND")
        report.evidence.append(f"ADX {adx_val:.1f}, +DI>{minus_di_val:.1f}, قیمت بالای EMA50")
    elif trending and not bullish_dir and not price_above_ema50:
        report.state = "STRONG_DOWNTREND" if strong_trend else ("DOWNTREND" if adx_val >= 25 else "WEAK_DOWNTREND")
        report.evidence.append(f"ADX {adx_val:.1f}, -DI>{plus_di_val:.1f}, قیمت زیر EMA50")
    else:
        report.state = "TRANSITION"
        report.evidence.append("سیگنال‌های جهت‌دار ناسازگار (ADX روند نشان می‌دهد ولی جهت واضح نیست)")

    # RSI افراطی می‌تواند نشانه‌ی Recovery/Crash در کنار روند باشد
    if rsi_val < 20 and report.state in ("STRONG_DOWNTREND", "DOWNTREND"):
        report.evidence.append("RSI شدیداً اشباع فروش - احتمال Crash یا نزدیک کف")
    if rsi_val > 80 and report.state in ("STRONG_UPTREND", "UPTREND"):
        report.evidence.append("RSI شدیداً اشباع خرید - احتیاط لازم است")

    return report
