"""
آرسان - محاسبه شاخص‌های تکنیکال (نسخه ۲)

تغییر نسبت به نسخه ۱: تعداد شاخص‌ها افزایش یافته تا تصمیم نهایی روی «امتیاز میانگین
چند فاکتور مستقل» بنا شود نه فقط ۲-۳ شاخص؛ این کار سیستم را هم حساس‌تر می‌کند
(چون سیگنال‌های ضعیف‌تر هم دیده می‌شوند) و هم خطای کمتری دارد (چون یک شاخص تنها
نمی‌تواند کل نتیجه را عوض کند).

شاخص‌های نسخه ۱ (بدون تغییر): RSI, MACD, SMA/EMA trend, Volume trend, Support/Resistance
شاخص‌های جدید نسخه ۲: Bollinger Bands, Stochastic RSI, OBV trend, EMA Cross (Golden/Death),
Trend Strength Index (جایگزین ساده‌ی ADX که به OHLC واقعی نیاز دارد و CoinGecko آن را نمی‌دهد)

نسخه ۳: recent_momentum_pct اضافه شد — پیدا شد که در بک‌تست، سیگنال‌ها دقیقاً
سر نقاط برگشت روند (وقتی قیمت تازه شروع به حرکت خلاف EMA۲۰/۵۰ کرده بود) بیشترین
خطا رو داشتن، چون EMA۲۰/۵۰ ذاتاً تاخیری‌اند. این فاکتور جدید در decision.py برای
گرفتن جلوی همین مشکل استفاده می‌شه (به decision.py نگاه کن).
"""

import pandas as pd
import numpy as np


def _prices_to_series(prices):
    """prices: [[timestamp_ms, price], ...] -> pandas Series از قیمت‌ها"""
    values = [p[1] for p in prices]
    return pd.Series(values, dtype="float64")


def _volumes_to_series(volumes):
    values = [v[1] for v in volumes]
    return pd.Series(values, dtype="float64")


# ---------------------------------------------------------------------------
# شاخص‌های نسخه ۱
# ---------------------------------------------------------------------------

def calculate_rsi(price_series, period=14):
    delta = price_series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not rsi.empty and not np.isnan(rsi.iloc[-1]) else 50.0


def calculate_macd(price_series, fast=12, slow=26, signal=9):
    ema_fast = price_series.ewm(span=fast, adjust=False).mean()
    ema_slow = price_series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    return {
        "macd": float(macd_line.iloc[-1]),
        "signal": float(signal_line.iloc[-1]),
        "histogram": float(histogram.iloc[-1]),
        "histogram_prev": float(histogram.iloc[-2]) if len(histogram) > 1 else float(histogram.iloc[-1]),
    }


def calculate_sma(price_series, period=20):
    sma = price_series.rolling(window=period, min_periods=1).mean()
    return float(sma.iloc[-1])


def calculate_ema(price_series, period=20):
    ema = price_series.ewm(span=period, adjust=False).mean()
    return float(ema.iloc[-1])


def calculate_volume_trend(volume_series):
    """مقایسه‌ی میانگین ۷ روز اخیر با ۷ روز قبل‌تر."""
    if len(volume_series) < 14:
        return "نامشخص", 0.0
    recent = volume_series.iloc[-7:].mean()
    previous = volume_series.iloc[-14:-7].mean()
    if previous == 0:
        return "نامشخص", 0.0
    change_pct = ((recent - previous) / previous) * 100
    if change_pct > 15:
        return "بالا", change_pct
    elif change_pct < -15:
        return "پایین", change_pct
    return "متوسط", change_pct


def calculate_trend_direction(price_series, short_period=20, long_period=50):
    """تشخیص روند بر اساس مقایسه EMA کوتاه‌مدت و بلندمدت."""
    ema_short = price_series.ewm(span=short_period, adjust=False).mean().iloc[-1]
    long_p = min(long_period, len(price_series))
    ema_long = price_series.ewm(span=long_p, adjust=False).mean().iloc[-1]
    diff_pct = ((ema_short - ema_long) / ema_long) * 100 if ema_long else 0

    if diff_pct > 4:
        label = "صعودی قوی"
    elif diff_pct > 1:
        label = "صعودی ضعیف"
    elif diff_pct < -4:
        label = "نزولی قوی"
    elif diff_pct < -1:
        label = "نزولی ضعیف"
    else:
        label = "خنثی"
    return label, diff_pct


def calculate_support_resistance(price_series, lookback=30):
    window = price_series.iloc[-lookback:]
    return float(window.min()), float(window.max())


# ---------------------------------------------------------------------------
# شاخص‌های جدید نسخه ۲
# ---------------------------------------------------------------------------

def calculate_bollinger_bands(price_series, period=20, std_dev=2):
    sma = price_series.rolling(window=period, min_periods=1).mean()
    std = price_series.rolling(window=period, min_periods=1).std().fillna(0)
    upper = sma + std_dev * std
    lower = sma - std_dev * std
    last_price = float(price_series.iloc[-1])
    upper_val = float(upper.iloc[-1])
    lower_val = float(lower.iloc[-1])
    band_width = upper_val - lower_val
    # موقعیت قیمت داخل باند: 0 = روی باند پایین، 1 = روی باند بالا
    position = (last_price - lower_val) / band_width if band_width > 0 else 0.5
    return {
        "upper": upper_val,
        "lower": lower_val,
        "position": float(np.clip(position, 0, 1)),
    }


def calculate_stochastic_rsi(price_series, period=14):
    """Stochastic RSI: موقعیت RSI فعلی نسبت به بازه RSI در period اخیر (0 تا 100)."""
    delta = price_series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    rsi_series = (100 - (100 / (1 + rs))).dropna()

    if len(rsi_series) < period:
        return 50.0

    rsi_window = rsi_series.iloc[-period:]
    rsi_min, rsi_max = rsi_window.min(), rsi_window.max()
    if rsi_max == rsi_min:
        return 50.0
    stoch_rsi = (rsi_series.iloc[-1] - rsi_min) / (rsi_max - rsi_min) * 100
    return float(stoch_rsi)


def calculate_obv_trend(price_series, volume_series):
    """On-Balance Volume: آیا جریان حجم، حرکت قیمت را تایید می‌کند یا در تضاد است."""
    n = min(len(price_series), len(volume_series))
    prices = price_series.iloc[-n:].reset_index(drop=True)
    volumes = volume_series.iloc[-n:].reset_index(drop=True)

    obv = [0.0]
    for i in range(1, n):
        if prices[i] > prices[i - 1]:
            obv.append(obv[-1] + volumes[i])
        elif prices[i] < prices[i - 1]:
            obv.append(obv[-1] - volumes[i])
        else:
            obv.append(obv[-1])
    obv_series = pd.Series(obv)

    if len(obv_series) < 10:
        return "نامشخص"

    obv_recent_slope = obv_series.iloc[-5:].diff().mean()
    price_recent_slope = prices.iloc[-5:].diff().mean()

    if obv_recent_slope > 0 and price_recent_slope > 0:
        return "تاییدکننده صعود"
    elif obv_recent_slope < 0 and price_recent_slope < 0:
        return "تاییدکننده نزول"
    elif obv_recent_slope < 0 and price_recent_slope > 0:
        return "واگرایی هشداردهنده (صعود بدون حمایت حجم)"
    elif obv_recent_slope > 0 and price_recent_slope < 0:
        return "واگرایی هشداردهنده (نزول بدون فشار فروش واقعی)"
    return "خنثی"


def calculate_ema_cross(price_series, short=12, long=26, lookback=5):
    """تشخیص کراس طلایی (golden cross) یا کراس مرگ (death cross) در N روز اخیر."""
    ema_short = price_series.ewm(span=short, adjust=False).mean()
    ema_long_p = min(long, len(price_series))
    ema_long = price_series.ewm(span=ema_long_p, adjust=False).mean()
    diff = ema_short - ema_long

    if len(diff) < lookback + 1:
        return "بدون کراس اخیر"

    recent = diff.iloc[-(lookback + 1):]
    sign_changes = np.sign(recent).diff().dropna()
    if (sign_changes > 0).any():
        return "کراس طلایی اخیر (صعودی)"
    if (sign_changes < 0).any():
        return "کراس مرگ اخیر (نزولی)"
    return "بدون کراس اخیر"


def calculate_recent_momentum(price_series, days=3):
    """
    درصد تغییر قیمت در N روز اخیر — مستقل از EMA۲۰/۵۰ که در calculate_trend_direction
    استفاده می‌شه. هدف: EMA۲۰/۵۰ ذاتاً تاخیری (lagging) است؛ درست همون لحظه‌ای که
    یه روند داره برمی‌گرده، این دو میانگین هنوز چند روز طول می‌کشه تا واکنش نشون بدن.
    این تابع یه سیگنال «تازه‌تر و سریع‌تر» می‌ده که در decision.py برای تشخیص
    برگشت‌های احتمالی روند استفاده می‌شه (نه برای جایگزینی خود روند).
    """
    if len(price_series) < days + 1:
        return 0.0
    past = price_series.iloc[-(days + 1)]
    recent = price_series.iloc[-1]
    if past == 0:
        return 0.0
    return float((recent - past) / past * 100)


def calculate_trend_strength(price_series, short=20, long=50):
    """
    جایگزین ساده‌ی ADX: چون CoinGecko داده OHLC واقعی نمی‌دهد، قدرت روند را از
    فاصله نسبی EMA کوتاه و بلندمدت می‌سازیم. خروجی یک عدد 0 تا 100 (هرچه بیشتر، روند قوی‌تر).
    از این عدد به‌عنوان «ضریب اطمینان» برای تعدیل امتیاز شاخص‌های روندی استفاده می‌شود.
    """
    ema_short = price_series.ewm(span=short, adjust=False).mean().iloc[-1]
    long_p = min(long, len(price_series))
    ema_long = price_series.ewm(span=long_p, adjust=False).mean().iloc[-1]
    if ema_long == 0:
        return 0.0
    strength = abs((ema_short - ema_long) / ema_long) * 100
    return float(min(strength * 10, 100))  # مقیاس‌بندی تقریبی به بازه 0-100


# ---------------------------------------------------------------------------
# تابع اصلی: محاسبه‌ی همه‌ی شاخص‌ها برای یک رمزارز
# ---------------------------------------------------------------------------

def calculate_all_indicators(market_chart):
    """
    market_chart: خروجی fetch_data.get_market_chart (شامل prices و volumes)
    خروجی: دیکشنری کامل شاخص‌ها برای استفاده در decision.py
    """
    price_series = _prices_to_series(market_chart["prices"])
    volume_series = _volumes_to_series(market_chart["volumes"])

    trend_label, trend_diff_pct = calculate_trend_direction(price_series)
    volume_trend_label, volume_change_pct = calculate_volume_trend(volume_series)
    support, resistance = calculate_support_resistance(price_series)
    last_price = float(price_series.iloc[-1])

    return {
        "rsi": calculate_rsi(price_series),
        "macd": calculate_macd(price_series),
        "sma_20": calculate_sma(price_series, 20),
        "ema_20": calculate_ema(price_series, 20),
        "trend": {"label": trend_label, "diff_pct": trend_diff_pct},
        "volume_trend": {"label": volume_trend_label, "change_pct": volume_change_pct},
        "support": support,
        "resistance": resistance,
        "last_price": last_price,
        "bollinger": calculate_bollinger_bands(price_series),
        "stochastic_rsi": calculate_stochastic_rsi(price_series),
        "obv_trend": calculate_obv_trend(price_series, volume_series),
        "ema_cross": calculate_ema_cross(price_series),
        "trend_strength": calculate_trend_strength(price_series),
        "recent_momentum_pct": calculate_recent_momentum(price_series),
    }
