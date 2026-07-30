"""
آرسان - تشخیص رژیم بازار (نسخه ۵، بازطراحی موتور تحلیل)

--- چرا این بازنویسی لازم بود ---
نسخه‌ی قبلی (نسخه ۴) فقط یک بعد از بازار رو می‌دید: نوسان‌پذیری (quiet/normal/
volatile). این عمداً یک لایه‌ی صرفاً نمایشی بود که هیچ اثری روی امتیازدهی
decision.py نداشت. طبق درخواست بازطراحی، حالا رژیم بازار باید:
  ۱) شامل بعد روند هم بشه (صعودی/نزولی/رنج)، نه فقط نوسان
  ۲) حالت «تغییر روند» (که در نسخه‌ی قبلی به‌صورت جدا در decision.py به اسم
     momentum_reversal_gate وجود داشت) رو به‌عنوان یک رژیم مستقل بشناسه
  ۳) واقعاً به decision.py وصل بشه تا وزن فاکتورها رو عوض کنه (نه صرفاً یک
     برچسب برای نمایش در داشبورد)

--- شش رژیم قابل تشخیص ---
    trend_change → بازار به‌تازگی در حال برگشت روند است (پرریسک‌ترین حالت)
    volatile     → نوسان شدید (صرف‌نظر از جهت روند)
    uptrend      → روند صعودی پایدار با نوسان عادی/کم
    downtrend    → روند نزولی پایدار با نوسان عادی/کم
    quiet        → بازار رنج ولی آروم (نوسان کم)
    range        → بازار رنج/خنثی (حالت پیش‌فرض، بدون ویژگی خاص)

--- چرا فقط یک رژیم غالب انتخاب می‌شه، نه چند بعد هم‌زمان ---
می‌شد رژیم رو به‌صورت چند بعدی (مثلاً trend×volatility = ۹ حالت) طراحی کرد،
ولی برای این پروژه (که جدول وزن‌دهی هر رژیم باید توسط انسان قابل بازبینی و
درک باشه) یک برچسب واحد با یک ترتیب اولویت مشخص، هم ساده‌تر برای نگهداری‌ست
و هم شفاف‌تر برای کاربر نهایی در داشبورد. ترتیب اولویت (از پرریسک‌ترین به
عادی‌ترین): تغییر روند > نوسان شدید > روند صعودی/نزولی > نوسان کم > رنج.

--- ورودی‌ها ---
این ماژول برای جلوگیری از محاسبه‌ی تکراری/ناهماهنگ منطق روند، دیگه خودش
EMA یا diff_pct رو دوباره حساب نمی‌کنه — از خروجی indicators.py (که main.py
از قبل محاسبه کرده) استفاده می‌کنه:
    trend_diff_pct, trend_strength, recent_momentum_pct
فقط برای محاسبه‌ی نوسان‌پذیری (که در indicators.py وجود نداره) به
price_history خام نیاز داره.
"""

import statistics

# چند روز آخر برای محاسبه‌ی نوسان‌پذیری در نظر گرفته بشه
VOLATILITY_WINDOW_DAYS = 14

# آستانه‌ها بر حسب "درصد انحراف معیار بازده روزانه" - این اعداد باید بعد از
# مشاهده‌ی چند هفته داده‌ی واقعی احتمالاً کالیبره بشن (هشدار صادقانه‌ی همون
# نسخه‌ی قبلی، دست‌نخورده مونده چون هنوز داده‌ی زنده‌ی کافی جمع نشده)
LOW_VOL_THRESHOLD = 1.5    # زیر این: بازار آروم
HIGH_VOL_THRESHOLD = 4.0   # بالای این: بازار پرنوسان/شلوغ

# آستانه‌ی قدرت روند برای این‌که یک حرکت رو "روند پایدار" (نه رنج) بدونیم.
# عمداً همون عددیه که در decision.py برای پروفایل "balanced" به‌عنوان
# min_trend_strength استفاده می‌شه، تا دو ماژول در مورد "الان روند داریم یا
# نه" یک زبان مشترک داشته باشن.
TREND_REGIME_MIN_STRENGTH = 15

# گیت تشخیص "تغییر روند": اگه روند میان‌مدت (EMA۲۰/۵۰) یک جهت رو نشون بده ولی
# قیمت در ۳ روز اخیر حداقل به این اندازه در جهت مخالف حرکت کرده باشه، یعنی
# احتمالاً روند داره برمی‌گرده. همون آستانه‌ای که قبلاً به‌صورت پنهان فقط داخل
# decision.py (به اسم MOMENTUM_REVERSAL_THRESHOLD) وجود داشت؛ حالا به‌عنوان
# یک رژیم مستقل و قابل‌مشاهده در کل سیستم درش آوردیم.
TREND_CHANGE_MOMENTUM_THRESHOLD = 1.0
TREND_CHANGE_MIN_TREND_DIFF = 1.0

REGIME_LABELS_FA = {
    "trend_change": "تغییر روند (احتمال برگشت اخیر)",
    "volatile": "بازار پرنوسان (احتیاط بیشتر توصیه می‌شود)",
    "uptrend": "روند صعودی پایدار",
    "downtrend": "روند نزولی پایدار",
    "quiet": "بازار رنج و آرام (نوسان کم)",
    "range": "بازار رنج/خنثی",
    "unknown": "داده کافی برای تشخیص رژیم بازار نیست",
}


def _daily_returns_pct(price_history):
    prices = [p[1] for p in price_history[-VOLATILITY_WINDOW_DAYS:]]
    if len(prices) < 3:
        return []
    returns = []
    for i in range(1, len(prices)):
        if prices[i - 1] == 0:
            continue
        returns.append((prices[i] - prices[i - 1]) / prices[i - 1] * 100)
    return returns


def _calculate_volatility(price_history):
    """خروجی: (volatility_pct یا None, volatility_regime: low|normal|high|unknown)"""
    returns = _daily_returns_pct(price_history)
    if len(returns) < 2:
        return None, "unknown"
    vol = round(statistics.pstdev(returns), 2)
    if vol < LOW_VOL_THRESHOLD:
        return vol, "low"
    if vol > HIGH_VOL_THRESHOLD:
        return vol, "high"
    return vol, "normal"


def _detect_trend_change(trend_diff_pct, recent_momentum_pct):
    """
    True یعنی: روند میان‌مدت یک جهت رو نشون می‌ده ولی حرکت اخیر قیمت (سریع‌تر
    و بدون تاخیر EMA) در جهت مخالفه — نشونه‌ی احتمالی شروع برگشت روند.
    """
    if abs(trend_diff_pct) < TREND_CHANGE_MIN_TREND_DIFF:
        return False  # اصلاً روند مشخصی نیست که بخواد "برگرده"
    trend_sign = 1 if trend_diff_pct > 0 else -1
    momentum_opposes = (
        (trend_sign > 0 and recent_momentum_pct <= -TREND_CHANGE_MOMENTUM_THRESHOLD) or
        (trend_sign < 0 and recent_momentum_pct >= TREND_CHANGE_MOMENTUM_THRESHOLD)
    )
    return momentum_opposes


def calculate_market_regime(indicators, price_history):
    """
    indicators: خروجی کامل indicators.calculate_all_indicators (همون کوین)
    price_history: [[timestamp_ms, price], ...] فقط برای محاسبه‌ی نوسان‌پذیری

    خروجی:
        {
          "regime": "trend_change"|"volatile"|"uptrend"|"downtrend"|"quiet"|"range"|"unknown",
          "label_fa": str,
          "volatility_pct": float | None,
          "volatility_regime": "low"|"normal"|"high"|"unknown",
          "trend_diff_pct": float,
          "trend_strength": float,
          "trend_change_detected": bool,
          "recent_momentum_pct": float,
        }

    نکته‌ی سازگاری با نسخه‌ی قبلی: index.html فقط از regime.label_fa و
    regime.volatility_pct استفاده می‌کنه — هر دو فیلد اینجا هم با همون اسم و
    همون نوع داده وجود دارن، پس داشبورد بدون تغییر کار می‌کنه.
    """
    volatility_pct, volatility_regime = _calculate_volatility(price_history)

    trend_diff_pct = indicators["trend"]["diff_pct"]
    trend_strength = indicators["trend_strength"]
    recent_momentum_pct = indicators.get("recent_momentum_pct", 0.0)

    if volatility_regime == "unknown":
        # داده‌ی قیمتی به‌قدر کافی وجود نداره؛ نمی‌شه با اطمینان رژیمی تشخیص داد
        return {
            "regime": "unknown",
            "label_fa": REGIME_LABELS_FA["unknown"],
            "volatility_pct": None,
            "volatility_regime": "unknown",
            "trend_diff_pct": round(trend_diff_pct, 2),
            "trend_strength": round(trend_strength, 1),
            "trend_change_detected": False,
            "recent_momentum_pct": round(recent_momentum_pct, 2),
        }

    trend_change_detected = _detect_trend_change(trend_diff_pct, recent_momentum_pct)
    is_trending = trend_strength >= TREND_REGIME_MIN_STRENGTH

    # --- ترتیب اولویت انتخاب رژیم غالب ---
    if trend_change_detected:
        regime = "trend_change"
    elif volatility_regime == "high":
        regime = "volatile"
    elif is_trending and trend_diff_pct > 0:
        regime = "uptrend"
    elif is_trending and trend_diff_pct < 0:
        regime = "downtrend"
    elif volatility_regime == "low":
        regime = "quiet"
    else:
        regime = "range"

    return {
        "regime": regime,
        "label_fa": REGIME_LABELS_FA[regime],
        "volatility_pct": volatility_pct,
        "volatility_regime": volatility_regime,
        "trend_diff_pct": round(trend_diff_pct, 2),
        "trend_strength": round(trend_strength, 1),
        "trend_change_detected": trend_change_detected,
        "recent_momentum_pct": round(recent_momentum_pct, 2),
    }
