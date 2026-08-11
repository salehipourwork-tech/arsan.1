"""
RSP — fuzzy_core/ahp_scoring.py

نسخه‌ی «تولیدی» ahp_calibrate.py (که یک اسکریپت مستقل تشخیصی بود، خارج از
RSP). این ماژول همون ۳ وزن (از روی همون تحلیل pairwise) رو به یک تابع ساده
تبدیل می‌کنه که decision_controller می‌تونه به‌جای/کنار امتیاز rule-based
استفاده کنه.

فقط ۳ feature تأییدشده: trend_quality، risk_quality_v2 (raw)،
volatility_quality_v2 (raw, badness scale). بقیه‌ی ۶ feature چون هنوز
correlation معناداری با pnl واقعی نشون ندادن، عمداً بیرون گذاشته شدن (نگاه
کنید تحلیل آماری قبلی) — وارد کردنشون بدون شواهد یعنی نویز رو با وزن AHP
"معتبر" جلوه بدیم.

Rollback: این ماژول به‌تنهایی هیچ رفتاری رو عوض نمی‌کنه؛ فقط وقتی
settings.OPPORTUNITY_SCORING_METHOD == "ahp" باشد در decision_controller
مصرف می‌شود (پیش‌فرض "rules" = رفتار قدیمی دست‌نخورده).
"""
from typing import Optional

# وزن‌های AHP (از ahp_calibrate.py — Saaty pairwise + geometric mean، CR=0.0)
AHP_WEIGHTS = {
    "trend_quality": 0.20,
    "risk_quality_v2": 0.40,
    "volatility_quality_v2": 0.40,
}


def ahp_opportunity_score(trend_quality_raw: float, risk_quality_v2_raw: float,
                           volatility_quality_v2_badness_raw: float) -> float:
    """
    ورودی: ۳ raw score (نه fuzzified) روی مقیاس ۰..۱ — trend_quality همون
    مقیاس «خوبی» همیشگی، risk_quality_v2 «خوبی»، volatility_quality_v2 روی
    مقیاس «بدی» (badness) است پس اینجا معکوس می‌شود.
    خروجی: امتیاز ترکیبی روی مقیاس ۰..۱۰۰ (هم‌مقیاس با opportunity_score
    قدیمی، تا گیت‌های موجود که threshold عددی روی ۰..۱۰۰ دارن بدون تغییر کار کنن).
    """
    vol_goodness = 1.0 - volatility_quality_v2_badness_raw
    score01 = (
        AHP_WEIGHTS["trend_quality"] * trend_quality_raw
        + AHP_WEIGHTS["risk_quality_v2"] * risk_quality_v2_raw
        + AHP_WEIGHTS["volatility_quality_v2"] * vol_goodness
    )
    return round(max(0.0, min(1.0, score01)) * 100.0, 2)
