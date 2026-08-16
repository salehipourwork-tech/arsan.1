"""
RSP — signal_engine/confluence.py  (Phase 7: TECHNICAL INTELLIGENCE)

طبق اسپک: اندیکاتورها را جداگانه بررسی نکن؛ به دنبال CONFLUENCE باش.

این ماژول RSI, MACD, EMA/SMA, Bollinger, ATR, ADX, Stochastic RSI, OBV,
Volume, Momentum را می‌خواند و به‌جای صدور یک سیگنال ساده، طبقه‌بندی می‌کند:

  AGREEMENT     -> چند اندیکاتور مستقل هم‌جهت‌اند
  CONFLICT      -> اندیکاتورها خلاف هم
  DIVERGENCE    -> قیمت و اندیکاتور (RSI/MACD/OBV) خلاف هم حرکت می‌کنند
  CONFIRMATION  -> اندیکاتور جدید، جهت قبلی را تایید می‌کند
  WEAKENING     -> شتاب/حجم رو به کاهش با وجود ادامه‌ی روند
  ACCELERATION  -> شتاب/حجم رو به افزایش هم‌جهت با روند

خروجی این ماژول "TechnicalEvidence" است که ورودی مستقیم signal_fusion است.
"""

from dataclasses import dataclass, field
from typing import List, Dict
import pandas as pd
import numpy as np

from RSP.indicators import technical as ta


@dataclass
class IndicatorReading:
    name: str
    direction: str      # "BULLISH" | "BEARISH" | "NEUTRAL"
    value: float
    detail: str = ""


@dataclass
class ConfluenceReport:
    readings: List[IndicatorReading] = field(default_factory=list)
    bullish_count: int = 0
    bearish_count: int = 0
    neutral_count: int = 0
    agreement_ratio: float = 0.0     # 0..1  (اکثریت از کل)
    classification: str = "NEUTRAL"  # AGREEMENT_BULLISH / AGREEMENT_BEARISH / CONFLICT / NEUTRAL
    divergences: List[str] = field(default_factory=list)
    momentum_state: str = "UNKNOWN"  # ACCELERATION | WEAKENING | STABLE
    tags: List[str] = field(default_factory=list)


def _dir_from_threshold(value, bull_thresh, bear_thresh):
    if value >= bull_thresh:
        return "BULLISH"
    if value <= bear_thresh:
        return "BEARISH"
    return "NEUTRAL"


def analyze_confluence(df: pd.DataFrame) -> ConfluenceReport:
    report = ConfluenceReport()
    if df.empty or len(df) < 30:
        report.tags.append("INSUFFICIENT_DATA_FOR_CONFLUENCE")
        return report

    close, high, low, volume = df["close"], df["high"], df["low"], df["volume"]

    # --- RSI ---
    rsi_series = ta.rsi(close, 14)
    rsi_val = ta.last(rsi_series, 50.0)
    rsi_dir = _dir_from_threshold(rsi_val, 55, 45)
    report.readings.append(IndicatorReading("RSI", rsi_dir, rsi_val))

    # --- MACD ---
    macd_line, signal_line, hist = ta.macd(close)
    hist_val = ta.last(hist, 0.0)
    hist_prev = ta.last(hist.iloc[:-1], hist_val) if len(hist) > 1 else hist_val
    macd_dir = "BULLISH" if hist_val > 0 else ("BEARISH" if hist_val < 0 else "NEUTRAL")
    report.readings.append(IndicatorReading("MACD", macd_dir, hist_val,
                            detail="rising" if hist_val > hist_prev else "falling"))

    # --- EMA cross (20 vs 50) ---
    ema20 = ta.ema(close, 20)
    ema50 = ta.ema(close, 50) if len(close) >= 50 else ema20
    e20, e50 = ta.last(ema20, close.iloc[-1]), ta.last(ema50, close.iloc[-1])
    ema_dir = "BULLISH" if e20 > e50 else ("BEARISH" if e20 < e50 else "NEUTRAL")
    report.readings.append(IndicatorReading("EMA_CROSS", ema_dir, e20 - e50))

    # --- SMA trend (price vs SMA20) ---
    sma20 = ta.sma(close, 20)
    s20 = ta.last(sma20, close.iloc[-1])
    sma_dir = "BULLISH" if close.iloc[-1] > s20 else ("BEARISH" if close.iloc[-1] < s20 else "NEUTRAL")
    report.readings.append(IndicatorReading("SMA_TREND", sma_dir, float(close.iloc[-1] - s20)))

    # --- Bollinger Bands (position) ---
    upper, mid, lower = ta.bollinger_bands(close, 20, 2.0)
    u, m, l = ta.last(upper, close.iloc[-1]), ta.last(mid, close.iloc[-1]), ta.last(lower, close.iloc[-1])
    bb_pos = (close.iloc[-1] - l) / (u - l) if (u - l) else 0.5
    bb_dir = "BULLISH" if bb_pos > 0.65 else ("BEARISH" if bb_pos < 0.35 else "NEUTRAL")
    report.readings.append(IndicatorReading("BOLLINGER_POSITION", bb_dir, bb_pos))

    # --- ADX (trend strength - جهت را از +DI/-DI می‌گیریم) ---
    adx_series, plus_di, minus_di = ta.adx(high, low, close, 14)
    adx_val = ta.last(adx_series, 15.0)
    pd_val, md_val = ta.last(plus_di, 0.0), ta.last(minus_di, 0.0)
    adx_dir = "NEUTRAL" if adx_val < 20 else ("BULLISH" if pd_val > md_val else "BEARISH")
    report.readings.append(IndicatorReading("ADX", adx_dir, adx_val))

    # --- Stochastic RSI ---
    stoch_series = ta.stochastic_rsi(close)
    stoch_val = ta.last(stoch_series, 50.0)
    stoch_dir = _dir_from_threshold(stoch_val, 60, 40)
    report.readings.append(IndicatorReading("STOCH_RSI", stoch_dir, stoch_val))

    # --- OBV trend ---
    obv_series = ta.obv(close, volume)
    if len(obv_series) >= 10:
        obv_slope = obv_series.iloc[-1] - obv_series.iloc[-10]
        obv_dir = "BULLISH" if obv_slope > 0 else ("BEARISH" if obv_slope < 0 else "NEUTRAL")
    else:
        obv_dir, obv_slope = "NEUTRAL", 0.0
    report.readings.append(IndicatorReading("OBV", obv_dir, float(obv_slope)))

    # --- Volume trend ---
    if len(volume) >= 20:
        recent_v, prior_v = volume.iloc[-10:].mean(), volume.iloc[-20:-10].mean()
        vol_change = (recent_v - prior_v) / prior_v if prior_v else 0
        vol_dir = "BULLISH" if vol_change > 0.1 else ("BEARISH" if vol_change < -0.1 else "NEUTRAL")
    else:
        vol_dir, vol_change = "NEUTRAL", 0.0
    report.readings.append(IndicatorReading("VOLUME_TREND", vol_dir, float(vol_change)))

    # ------------------------------------------------------------------
    # Aggregate counts
    # ------------------------------------------------------------------
    for r in report.readings:
        if r.direction == "BULLISH":
            report.bullish_count += 1
        elif r.direction == "BEARISH":
            report.bearish_count += 1
        else:
            report.neutral_count += 1

    total = len(report.readings)
    majority = max(report.bullish_count, report.bearish_count)
    report.agreement_ratio = round(majority / total, 3) if total else 0.0

    if report.bullish_count >= total * 0.6:
        report.classification = "AGREEMENT_BULLISH"
    elif report.bearish_count >= total * 0.6:
        report.classification = "AGREEMENT_BEARISH"
    elif report.bullish_count > 0 and report.bearish_count > 0 and \
            min(report.bullish_count, report.bearish_count) / total >= 0.3:
        report.classification = "CONFLICT"
    else:
        report.classification = "NEUTRAL"

    # ------------------------------------------------------------------
    # Divergence detection: price higher-high but RSI/MACD/OBV lower-high (bearish div) و برعکس
    # ------------------------------------------------------------------
    if len(close) >= 20:
        price_recent_max = close.iloc[-10:].max()
        price_prior_max = close.iloc[-20:-10].max()
        rsi_recent_max = rsi_series.iloc[-10:].max()
        rsi_prior_max = rsi_series.iloc[-20:-10].max()
        if price_recent_max > price_prior_max and rsi_recent_max < rsi_prior_max:
            report.divergences.append("BEARISH_DIVERGENCE_RSI (قیمت بالاتر، RSI پایین‌تر)")

        price_recent_min = close.iloc[-10:].min()
        price_prior_min = close.iloc[-20:-10].min()
        rsi_recent_min = rsi_series.iloc[-10:].min()
        rsi_prior_min = rsi_series.iloc[-20:-10].min()
        if price_recent_min < price_prior_min and rsi_recent_min > rsi_prior_min:
            report.divergences.append("BULLISH_DIVERGENCE_RSI (قیمت پایین‌تر، RSI بالاتر)")

        obv_recent_slope = obv_series.iloc[-1] - obv_series.iloc[-10] if len(obv_series) >= 10 else 0
        if price_recent_max > price_prior_max and obv_recent_slope < 0:
            report.divergences.append("BEARISH_DIVERGENCE_OBV (قیمت بالاتر، حجم تجمعی پایین‌تر)")

    # ------------------------------------------------------------------
    # Momentum state: ACCELERATION / WEAKENING / STABLE
    # (بر اساس شتاب هیستوگرام MACD و حجم، هم‌جهت با کلاسیفیکیشن غالب)
    # ------------------------------------------------------------------
    momentum_up = hist_val > hist_prev
    volume_up = vol_change > 0
    if report.classification == "AGREEMENT_BULLISH":
        report.momentum_state = "ACCELERATION" if (momentum_up and volume_up) else \
                                 ("WEAKENING" if (not momentum_up and not volume_up) else "STABLE")
    elif report.classification == "AGREEMENT_BEARISH":
        report.momentum_state = "ACCELERATION" if (not momentum_up and volume_up) else \
                                 ("WEAKENING" if (momentum_up and not volume_up) else "STABLE")
    else:
        report.momentum_state = "STABLE"

    if report.divergences:
        report.tags.append("DIVERGENCE_PRESENT")
    if report.classification == "CONFLICT":
        report.tags.append("INDICATOR_CONFLICT")

    return report
