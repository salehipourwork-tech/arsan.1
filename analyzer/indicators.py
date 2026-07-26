"""
محاسبه شاخص‌های تکنیکال روی سری قیمت.
ورودی هر تابع: لیست قیمت‌های بسته‌شدن (close price) به ترتیب زمانی صعودی.
"""
import pandas as pd
import numpy as np


def to_series(prices):
    return pd.Series(prices, dtype="float64")


def rsi(prices, period: int = 14):
    s = to_series(prices)
    delta = s.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi_val = 100 - (100 / (1 + rs))
    return rsi_val.iloc[-1] if not rsi_val.empty and not pd.isna(rsi_val.iloc[-1]) else None


def ema(prices, period: int):
    s = to_series(prices)
    return s.ewm(span=period, adjust=False).mean()


def macd(prices, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = ema(prices, fast)
    ema_slow = ema(prices, slow)
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return {
        "macd": round(float(macd_line.iloc[-1]), 4),
        "signal": round(float(signal_line.iloc[-1]), 4),
        "histogram": round(float(histogram.iloc[-1]), 4),
    }


def moving_average(prices, period: int = 20):
    s = to_series(prices)
    ma = s.rolling(window=period).mean()
    return float(ma.iloc[-1]) if not pd.isna(ma.iloc[-1]) else None


def ema_value(prices, period: int = 20):
    e = ema(prices, period)
    return float(e.iloc[-1])


def volume_trend(volumes, period: int = 7):
    """مقایسه میانگین حجم اخیر با میانگین حجم قبل‌تر -> بالا/متوسط/پایین"""
    s = to_series(volumes)
    if len(s) < period * 2:
        return "نامشخص"
    recent = s.tail(period).mean()
    previous = s.tail(period * 2).head(period).mean()
    if previous == 0 or pd.isna(previous):
        return "نامشخص"
    change = (recent - previous) / previous
    if change > 0.2:
        return "بالا"
    if change < -0.2:
        return "پایین"
    return "متوسط"


def trend_direction(prices, short_period: int = 10, long_period: int = 30):
    """تشخیص روند بر اساس مقایسه EMA کوتاه و بلند مدت"""
    if len(prices) < long_period:
        return "نامشخص"
    ema_short = ema_value(prices, short_period)
    ema_long = ema_value(prices, long_period)
    diff_pct = (ema_short - ema_long) / ema_long * 100

    if diff_pct > 3:
        return "صعودی قوی"
    if diff_pct > 0.5:
        return "صعودی ضعیف"
    if diff_pct < -3:
        return "نزولی قوی"
    if diff_pct < -0.5:
        return "نزولی ضعیف"
    return "خنثی"


def support_resistance(prices, window: int = 30):
    """ساده‌ترین روش: کف و سقف قیمت در بازه اخیر"""
    s = to_series(prices).tail(window)
    if s.empty:
        return None, None
    return float(s.min()), float(s.max())


def compute_all(price_series, volume_series):
    """
    محاسبه همه شاخص‌ها برای یک رمزارز و بازگرداندن دیکشنری آماده استفاده.
    price_series, volume_series: لیست اعداد به ترتیب زمانی صعودی.
    """
    support, resistance = support_resistance(price_series)
    result = {
        "rsi": round(rsi(price_series), 2) if rsi(price_series) is not None else None,
        "macd": macd(price_series),
        "ma20": round(moving_average(price_series, 20), 4) if moving_average(price_series, 20) else None,
        "ema20": round(ema_value(price_series, 20), 4),
        "volume_trend": volume_trend(volume_series),
        "trend": trend_direction(price_series),
        "support": round(support, 4) if support else None,
        "resistance": round(resistance, 4) if resistance else None,
        "current_price": round(price_series[-1], 6),
    }
    return result
