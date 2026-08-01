"""
RSP — indicators/technical.py  (Phase 7 support: raw indicator calculations)

فقط محاسبه. تفسیر و Confluence در signal_engine/confluence.py انجام می‌شود
(طبق اسپک: "اندیکاتورها را جداگانه بررسی نکن، به دنبال Confluence باش").

این ماژول مستقل از analyzer/indicators.py آرسان اصلی است؛ اما چون روی
OHLCV واقعی کار می‌کند (نه فقط سری قیمت خطی)، می‌تواند ATR و ADX واقعی
محاسبه کند - چیزی که آرسان اصلی به‌خاطر نبود OHLC نداشت (به AVG True Range
تقریبی با Trend Strength Index در آرسان اصلی نگاه کن).
"""

import numpy as np
import pandas as pd


def rsi(close: pd.Series, period=14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period, min_periods=period).mean()
    avg_loss = loss.rolling(period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def macd(close: pd.Series, fast=12, slow=26, signal=9):
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def sma(series: pd.Series, period=20) -> pd.Series:
    return series.rolling(period, min_periods=period).mean()


def ema(series: pd.Series, period=20) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def bollinger_bands(close: pd.Series, period=20, std_mult=2.0):
    mid = sma(close, period)
    std = close.rolling(period, min_periods=period).std()
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    return upper, mid, lower


def true_range(high, low, close):
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr


def atr(high, low, close, period=14) -> pd.Series:
    tr = true_range(high, low, close)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def adx(high, low, close, period=14):
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    tr = true_range(high, low, close)
    atr_ = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    plus_di = 100 * pd.Series(plus_dm, index=high.index).ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_.replace(0, np.nan)
    minus_di = 100 * pd.Series(minus_dm, index=high.index).ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_.replace(0, np.nan)
    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
    adx_ = dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    return adx_, plus_di, minus_di


def stochastic_rsi(close: pd.Series, rsi_period=14, stoch_period=14):
    rsi_series = rsi(close, rsi_period)
    min_rsi = rsi_series.rolling(stoch_period, min_periods=stoch_period).min()
    max_rsi = rsi_series.rolling(stoch_period, min_periods=stoch_period).max()
    return ((rsi_series - min_rsi) / (max_rsi - min_rsi).replace(0, np.nan)) * 100


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = np.sign(close.diff().fillna(0))
    return (direction * volume.fillna(0)).cumsum()


def last(series: pd.Series, default=None):
    if series is None or series.empty:
        return default
    val = series.iloc[-1]
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return default
    return float(val)
