"""
آرسان - جدول ضرایب وزن‌دهی پویا بر اساس رژیم بازار (نسخه ۵، بازطراحی موتور تحلیل)

--- ایده‌ی اصلی ---
weights.json وزن «پایه»ی هر فاکتور رو نگه می‌داره (همون چیزی که همیشه بوده و
دست‌نخورده می‌مونه). این فایل یک لایه‌ی ضرب‌شونده روی همون وزن پایه است که بر
اساس رژیم فعلی بازار (خروجی market_regime.py) فرق می‌کنه:

    وزن نهایی فاکتور در این تحلیل = وزن پایه (weights.json) × ضریب رژیم (اینجا)

مثال: در رژیم "range" (بازار خنثی/رنج)، فاکتورهای نوسان‌گیر مثل RSI و
Bollinger و Stochastic RSI قابل‌اعتمادترن (چون قیمت بین حمایت/مقاومت نوسان
می‌کنه)، ولی فاکتورهای دنباله‌روی روند مثل EMA Cross و MACD کم‌اعتبارترن (چون
اصلاً روند پایداری برای دنبال‌کردن وجود نداره). برعکسش در "uptrend"/"downtrend"
صادقه.

--- هشدار صادقانه (هم‌راستا با optimize_weights.py) ---
این ضرایب اولیه بر اساس منطق شناخته‌شده‌ی تحلیل تکنیکال تعیین شدن (مثلاً
"در روند قوی، اندیکاتورهای اشباع خرید/فروش می‌تونن مدت زیادی در ناحیه‌ی
اشباع بمونن، پس اعتبارشون کمتره")، نه بر پایه‌ی بک‌تست آماری روی این رژیم‌های
خاص. optimize_weights.py حالا آمار عملکرد هر فاکتور را به‌تفکیک رژیم هم
محاسبه می‌کند (factor_stats_by_regime)؛ وقتی داده‌ی کافی جمع شد، همون‌جا
پیشنهاد اصلاح این جدول رو می‌ده — ولی هیچ‌وقت این فایل رو خودکار overwrite
نمی‌کنه؛ اصلاح این اعداد همیشه دستی و توسط انسان انجام می‌شه.

--- قرارداد کلیدها ---
هر رژیم باید دقیقاً همون کلیدهای factors/weights.json را (یا زیرمجموعه‌ای از
آن‌ها) پوشش بدهد. اگر فاکتوری در جدول رژیم فعلی نباشد، ضریب پیش‌فرض ۱.۰
(بدون تغییر نسبت به وزن پایه) در نظر گرفته می‌شود — یعنی جدول ناقص هرگز باعث
کرش یا رفتار غیرمنتظره نمی‌شود.
"""

DEFAULT_MULTIPLIER = 1.0

REGIME_WEIGHT_MULTIPLIERS = {
    # --- روند صعودی/نزولی پایدار: فاکتورهای دنباله‌روی روند تقویت می‌شن،
    # فاکتورهای اشباع خرید/فروش (که در روند قوی می‌تونن مدت‌ها اشباع بمونن
    # بدون بازگشت) کمی تضعیف می‌شن. ---
    "uptrend": {
        "trend": 1.3, "macd": 1.2, "ema_cross": 1.2,
        "obv_trend": 1.1, "btc_alignment": 1.1,
        "rsi": 0.7, "bollinger": 0.7, "stochastic_rsi": 0.7,
        "volume_trend": 1.0, "support_resistance": 1.0, "news_sentiment": 1.0,
    },
    "downtrend": {
        "trend": 1.3, "macd": 1.2, "ema_cross": 1.2,
        "obv_trend": 1.1, "btc_alignment": 1.1,
        "rsi": 0.7, "bollinger": 0.7, "stochastic_rsi": 0.7,
        "volume_trend": 1.0, "support_resistance": 1.0, "news_sentiment": 1.0,
    },

    # --- بازار رنج/خنثی: عکس حالت روند. فاکتورهای نوسان‌گیر بین حمایت/مقاومت
    # قابل‌اعتمادترن؛ فاکتورهای دنباله‌روی روند تقریباً بی‌معنی‌ان چون روند
    # پایداری برای دنبال‌کردن وجود نداره. ---
    "range": {
        "rsi": 1.3, "bollinger": 1.3, "stochastic_rsi": 1.3, "support_resistance": 1.2,
        "trend": 0.6, "macd": 0.7, "ema_cross": 0.6,
        "obv_trend": 0.9, "btc_alignment": 0.8,
        "volume_trend": 1.0, "news_sentiment": 1.0,
    },

    # --- رنج ولی آرام (نوسان کم): شبیه رنج، ولی چون نویز کمتره سیگنال‌ها کمی
    # قابل‌اعتمادتر می‌شن (به‌خصوص بولینگر که فشردگی باند، اغلب مقدمه‌ی یک
    # حرکت بزرگه). ---
    "quiet": {
        "rsi": 1.05, "bollinger": 1.1, "stochastic_rsi": 1.05, "support_resistance": 1.1,
        "trend": 1.05, "macd": 1.05, "ema_cross": 1.0,
        "obv_trend": 1.0, "btc_alignment": 1.0,
        "volume_trend": 1.0, "news_sentiment": 0.9,
    },

    # --- نوسان شدید: کل بازار نویزی‌تره. فاکتورهای باند-محور (بولینگر/استوکاستیک)
    # زودتر false-signal می‌دن، پس تضعیف می‌شن؛ فاکتورهای تاییدی (حجم/OBV/هم‌سویی
    # با BTC/اخبار) که کمتر تحت‌تاثیر نوسان کوتاه‌مدت قیمتن، تقویت می‌شن. ---
    "volatile": {
        "bollinger": 0.7, "stochastic_rsi": 0.7, "rsi": 0.85,
        "volume_trend": 1.2, "obv_trend": 1.2, "btc_alignment": 1.2, "news_sentiment": 1.3,
        "trend": 0.9, "macd": 0.9, "ema_cross": 0.8, "support_resistance": 0.9,
    },

    # --- تغییر روند (پرریسک‌ترین حالت): فاکتورهای دنباله‌روی روند (EMA/MACD/trend)
    # ذاتاً تاخیری‌ان و دقیقاً همین‌جا گمراه‌کننده‌ترن، پس به‌شدت تضعیف می‌شن.
    # فاکتورهای تاییدی سریع‌تر (حجم، OBV، اخبار) که زودتر از EMA واکنش نشون
    # می‌دن، تقویت می‌شن. ---
    "trend_change": {
        "trend": 0.5, "macd": 0.6, "ema_cross": 0.5,
        "rsi": 1.0, "bollinger": 1.1, "stochastic_rsi": 0.9,
        "volume_trend": 1.3, "obv_trend": 1.3, "support_resistance": 1.2, "news_sentiment": 1.2,
        "btc_alignment": 0.9,
    },

    # --- نامشخص (داده کافی برای تشخیص رژیم نبود): بدون هیچ تعدیلی، دقیقاً
    # رفتار قدیمی (نسخه ۴ به قبل) حفظ می‌شه. ---
    "unknown": {},
}


def get_regime_multipliers(regime):
    """
    خروجی: دیکشنری {factor_name: multiplier} برای رژیم داده‌شده.
    اگه رژیم ناشناخته باشه (یا None پاس داده بشه)، دیکشنری خالی برمی‌گردونه —
    یعنی همه‌ی فاکتورها ضریب پیش‌فرض DEFAULT_MULTIPLIER (۱.۰) می‌گیرن، دقیقاً
    هم‌ارز رفتار قدیمی بدون وزن‌دهی پویا.
    """
    return REGIME_WEIGHT_MULTIPLIERS.get(regime, {})


def apply_regime_multipliers(base_weights, regime):
    """
    base_weights: دیکشنری وزن پایه (خروجی weights.json در decision.py)
    regime: رشته‌ی رژیم فعلی (خروجی market_regime.calculate_market_regime()["regime"])
            یا None (یعنی وزن‌دهی پویا غیرفعاله، مثلاً برای سازگاری با کدهای قدیمی)

    خروجی: دیکشنری وزن نهایی، هم‌مقیاس با base_weights (همون کلیدها)، آماده
    برای استفاده‌ی مستقیم در محاسبه‌ی weighted_sum در decision.py.
    """
    multipliers = get_regime_multipliers(regime)
    return {
        factor: round(base_weights[factor] * multipliers.get(factor, DEFAULT_MULTIPLIER), 4)
        for factor in base_weights
    }
