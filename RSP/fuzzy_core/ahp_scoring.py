"""
RSP — fuzzy_core/ahp_scoring.py

نسخه‌ی «تولیدی» ahp_calibrate.py (که یک اسکریپت مستقل تشخیصی بود، خارج از
RSP). این ماژول همون وزن‌ها رو به یک تابع ساده تبدیل می‌کنه که decision_controller می‌تونه به‌جای/کنار امتیاز rule-based استفاده کنه.

نسخه‌ی ۲: وزن‌ها متعادل‌تر شدند + entry_quality اضافه شد + compensatory bonus
"""
from typing import Optional

# وزن‌های AHP نسخه‌ی ۲: متعادل‌تر — نوسان دیگر ۴۰٪ نیست
AHP_WEIGHTS = {
    "trend_quality": 0.30,
    "risk_quality_v2": 0.35,
    "volatility_quality_v2": 0.25,
    "entry_quality": 0.10,
}

def ahp_opportunity_score(trend_quality_raw: float, risk_quality_v2_raw: float,
                          volatility_quality_v2_badness_raw: float,
                          entry_quality_raw: float = 0.5) -> float:
    """
    ورودی: ۴ raw score (نه fuzzified) روی مقیاس ۰..۱
    - trend_quality: خوبی روند
    - risk_quality_v2: خوبی ریسک/ریوارد (R:R واقعی)
    - volatility_quality_v2: بدی نوسان (معکوس می‌شود)
    - entry_quality: خوبی نقطه ورود (اختیاری، پیش‌فرض ۰.۵)

    Compensatory bonus: اگر روند و ریسک هر دو قوی باشند (>=0.65)،
    نوسان کم‌تر اثر می‌دهد (score ۱۰٪ تقویت + ۵٪ offset).

    خروجی: امتیاز ترکیبی روی مقیاس ۰..۱۰۰
    """
    vol_goodness = 1.0 - volatility_quality_v2_badness_raw
    score01 = (
        AHP_WEIGHTS["trend_quality"] * trend_quality_raw
        + AHP_WEIGHTS["risk_quality_v2"] * risk_quality_v2_raw
        + AHP_WEIGHTS["volatility_quality_v2"] * vol_goodness
        + AHP_WEIGHTS["entry_quality"] * entry_quality_raw
    )

    # Compensatory bonus: strong trend + good risk = volatility matters less
    if trend_quality_raw >= 0.65 and risk_quality_v2_raw >= 0.65:
        score01 = min(1.0, score01 * 1.10 + 0.05)

    return round(max(0.0, min(1.0, score01)) * 100.0, 2)
