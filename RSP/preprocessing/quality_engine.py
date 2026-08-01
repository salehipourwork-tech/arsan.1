"""
RSP — preprocessing/quality_engine.py  (Phase 3: DATA QUALITY ENGINE)

قبل از هر تحلیلی، هر تایم‌فریم از نظر کیفیت بررسی می‌شود. اگر کیفیت داده
برای تصمیم‌گیری کافی نباشد، موتور باید بتواند NO_TRADE بدهد - این تصمیم
اینجا گرفته نمی‌شود، فقط شواهد و پرچم‌ها تولید می‌شوند؛ decision_engine
تصمیم نهایی را می‌گیرد (تفکیک مسئولیت).
"""

from dataclasses import dataclass, field
from typing import List
import numpy as np
import pandas as pd

from RSP.config import settings


@dataclass
class QualityReport:
    timeframe: str
    issues: List[str] = field(default_factory=list)
    bar_count: int = 0
    gap_ratio: float = 0.0
    quality_ok: bool = True
    quality_score: float = 100.0   # 0-100


def check_quality(df: pd.DataFrame, timeframe: str) -> QualityReport:
    report = QualityReport(timeframe=timeframe, bar_count=len(df))

    if df.empty:
        report.issues.append("NO_DATA")
        report.quality_ok = False
        report.quality_score = 0.0
        return report

    min_needed = settings.MIN_BARS_REQUIRED.get(timeframe, 20)
    if len(df) < min_needed:
        report.issues.append(f"INSUFFICIENT_BARS ({len(df)} < {min_needed})")

    # Duplicate index
    if df.index.duplicated().any():
        report.issues.append("DUPLICATE_TIMESTAMPS")

    # Out-of-order index (باید بعد از resample مرتب باشد، ولی چک می‌کنیم)
    if not df.index.is_monotonic_increasing:
        report.issues.append("OUT_OF_ORDER_TIMESTAMPS")

    # Invalid OHLC (high must be >= low, >= open/close; low must be <= open/close)
    invalid_ohlc = ((df["high"] < df["low"]) |
                     (df["high"] < df["open"]) | (df["high"] < df["close"]) |
                     (df["low"] > df["open"]) | (df["low"] > df["close"]))
    n_invalid = int(invalid_ohlc.sum())
    if n_invalid > 0:
        report.issues.append(f"INVALID_OHLC_BARS ({n_invalid})")

    # Zero volume bars
    zero_vol = int((df["volume"] == 0).sum()) if "volume" in df else 0
    zero_vol_ratio = zero_vol / len(df) if len(df) else 0
    if zero_vol_ratio > 0.3:
        report.issues.append(f"HIGH_ZERO_VOLUME_RATIO ({zero_vol_ratio:.0%})")

    # Data gaps: expected bars vs actual, based on median interval
    if len(df) > 2:
        deltas = df.index.to_series().diff().dropna()
        median_delta = deltas.median()
        expected_span = df.index[-1] - df.index[0]
        expected_bars = (expected_span / median_delta) + 1 if median_delta.total_seconds() > 0 else len(df)
        gap_ratio = max(0.0, 1 - (len(df) / expected_bars)) if expected_bars > 0 else 0.0
        report.gap_ratio = float(gap_ratio)
        if gap_ratio > settings.MAX_ALLOWED_GAP_RATIO:
            report.issues.append(f"DATA_GAPS ({gap_ratio:.1%} missing)")

    # Abnormal spikes (return outliers)
    returns = df["close"].pct_change().dropna()
    if len(returns) > 5:
        std = returns.std()
        if std and not np.isnan(std) and std > 0:
            spikes = (returns.abs() > settings.ABNORMAL_SPIKE_STD_MULTIPLIER * std).sum()
            if spikes > 0:
                report.issues.append(f"ABNORMAL_PRICE_SPIKES ({int(spikes)})")

    # Score: هر مشکل جریمه دارد
    penalty = min(100, len(report.issues) * 15 + report.gap_ratio * 100)
    report.quality_score = round(max(0.0, 100.0 - penalty), 1)
    report.quality_ok = report.quality_score >= 50.0 and "NO_DATA" not in report.issues

    return report


def check_all_timeframes(bars_by_tf: dict) -> dict:
    return {tf: check_quality(df, tf) for tf, df in bars_by_tf.items()}
