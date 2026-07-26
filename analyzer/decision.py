"""
موتور تصمیم‌گیری آرسان.
بر اساس شاخص‌های محاسبه‌شده، امتیازدهی می‌کند و نتیجه (خرید/فروش/صبر)
را به همراه دلیل به زبان ساده فارسی تولید می‌کند.

توجه: این یک سیستم قانون-محور (rule-based) شفاف است، نه پیش‌بینی قطعی بازار.
"""


def score_rsi(rsi_value):
    if rsi_value is None:
        return 0, "نامشخص"
    if rsi_value < 30:
        return 2, "اشباع فروش (احتمال برگشت به بالا)"
    if rsi_value > 70:
        return -2, "اشباع خرید (احتمال اصلاح قیمت)"
    if 45 <= rsi_value <= 55:
        return 0, "خنثی"
    if rsi_value < 45:
        return 1, "کمی ضعیف رو به مثبت"
    return -1, "کمی قوی رو به منفی"


def score_macd(macd_data):
    hist = macd_data.get("histogram", 0)
    if hist > 0:
        return 1, "مثبت"
    if hist < 0:
        return -1, "منفی"
    return 0, "خنثی"


def score_trend(trend):
    mapping = {
        "صعودی قوی": (2, trend),
        "صعودی ضعیف": (1, trend),
        "خنثی": (0, trend),
        "نزولی ضعیف": (-1, trend),
        "نزولی قوی": (-2, trend),
        "نامشخص": (0, trend),
    }
    return mapping.get(trend, (0, trend))


def score_volume(volume_trend, trend_score):
    """حجم بالا در جهت روند، سیگنال را تقویت می‌کند"""
    if volume_trend == "بالا" and trend_score > 0:
        return 1
    if volume_trend == "بالا" and trend_score < 0:
        return -1
    return 0


def decide(indicators: dict):
    rsi_score, rsi_label = score_rsi(indicators.get("rsi"))
    macd_score, macd_label = score_macd(indicators.get("macd", {}))
    trend_score, trend_label = score_trend(indicators.get("trend"))
    volume_score = score_volume(indicators.get("volume_trend"), trend_score)

    total_score = rsi_score + macd_score + trend_score + volume_score

    if total_score >= 3:
        signal = "buy"
    elif total_score <= -3:
        signal = "sell"
    else:
        signal = "hold"

    signal_fa = {"buy": "خرید", "sell": "فروش", "hold": "صبر"}[signal]
    signal_emoji = {"buy": "🟢", "sell": "🔴", "hold": "🟡"}[signal]

    reason = build_reason(signal, indicators, rsi_label, macd_label, trend_label, indicators.get("volume_trend"))

    return {
        "signal": signal,
        "signal_fa": signal_fa,
        "emoji": signal_emoji,
        "score": total_score,
        "reason": reason,
        "disclaimer": "این تحلیل صرفاً بر اساس شاخص‌های تکنیکال است و تضمینی برای سود یا پیش‌بینی قطعی بازار نیست. تصمیم نهایی همیشه با شماست.",
    }


def build_reason(signal, indicators, rsi_label, macd_label, trend_label, volume_trend):
    parts = []
    parts.append(f"روند فعلی {trend_label} است")
    parts.append(f"RSI در وضعیت {rsi_label} قرار دارد")
    parts.append(f"MACD {macd_label} است")
    parts.append(f"حجم معاملات نسبت به روزهای اخیر {volume_trend} است")

    base = "، ".join(parts) + "."

    if signal == "buy":
        conclusion = " مجموع این شاخص‌ها نشان‌دهنده شرایط نسبتاً مثبت برای ورود است، هرچند ریسک بازار همیشه وجود دارد."
    elif signal == "sell":
        conclusion = " مجموع این شاخص‌ها نشان‌دهنده ضعف روند و افزایش احتمال کاهش قیمت است."
    else:
        conclusion = " شاخص‌ها سیگنال قاطعی در یک جهت مشخص نمی‌دهند، بنابراین صبر و مشاهده بیشتر منطقی‌تر است."

    return base + conclusion
