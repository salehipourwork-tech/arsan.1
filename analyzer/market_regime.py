"""
آرسان - تشخیص رژیم بازار بر پایه نوسان‌پذیری تاریخی (نسخه ۴، دسته C)

چرا این یکی الان قابل‌ساختنه ولی «وزن‌دهی پویا» (بخش دیگه‌ی دسته C) نه:
این ماژول فقط به تاریخچه‌ی قیمت نیاز داره (که fetch_data.py با days=100 از
قبل می‌گیره)، نه به تاریخچه‌ی صحت سیگنال‌ها (history.json) که هنوز خالیه.
پس برخلاف optimize_weights.py، این ماژول از روز اول داده‌ی کافی داره.

هدف: گیت فعلی trend_strength در decision.py فقط می‌گه «روند هست یا نیست».
این ماژول یه لایه‌ی اضافه می‌ده: حتی وقتی روند هست، بازار چقدر «آرومه» یا
«شلوغ/نوسانیه». این برای نمایش به کاربر مفیده (مثلاً «صعودی ولی نوسان بالا،
احتیاط کن») ولی عمداً روی امتیاز decision.py اثر مستقیم نمی‌ذاره — چون گزارش
وضعیت گفته بود این بخش «شاید» بعد از تثبیت باید امتحان بشه، پس فعلاً یه لایه‌ی
نمایشی/اطلاعاتی مستقله، نه یه گیت جدید که رفتار موجود رو عوض کنه.

ورودی: لیست [timestamp_ms, price] که indicators.py هم از همون استفاده می‌کنه
(fetch_data.py با days=100 برمی‌گردونه).
"""

import statistics

# چند روز آخر برای محاسبه‌ی نوسان‌پذیری در نظر گرفته بشه
VOLATILITY_WINDOW_DAYS = 14

# آستانه‌ها بر حسب "درصد انحراف معیار بازده روزانه" - این اعداد باید بعد از
# مشاهده‌ی چند هفته داده‌ی واقعی احتمالاً کالیبره بشن (این خودش هشدار صادقانه‌ست:
# اعداد اولیه‌ی معقول‌اند، نه علمی‌اثبات‌شده)
LOW_VOL_THRESHOLD = 1.5    # زیر این: بازار آروم
HIGH_VOL_THRESHOLD = 4.0   # بالای این: بازار پرنوسان/شلوغ


def _daily_returns_pct(price_history):
    prices = [p[1] for p in price_history[-VOLATILITY_WINDOW_DAYS:]]
    if len(prices) < 3:
        return []
    returns = []
    for i in range(1, len(prices)):
        if prices[i-1] == 0:
            continue
        returns.append((prices[i] - prices[i-1]) / prices[i-1] * 100)
    return returns


def calculate_market_regime(price_history):
    """
    خروجی:
        {
          "volatility_pct": float | None,   # انحراف معیار بازده روزانه (٪)
          "regime": "quiet" | "normal" | "volatile" | "unknown",
          "label_fa": str
        }
    اگه داده کافی نباشه (کمتر از ۳ روز)، regime="unknown" برمی‌گرده.
    """
    returns = _daily_returns_pct(price_history)
    if len(returns) < 2:
        return {"volatility_pct": None, "regime": "unknown", "label_fa": "داده کافی برای تشخیص نوسان‌پذیری نیست"}

    vol = statistics.pstdev(returns)

    if vol < LOW_VOL_THRESHOLD:
        regime, label = "quiet", "بازار آروم (نوسان کم)"
    elif vol > HIGH_VOL_THRESHOLD:
        regime, label = "volatile", "بازار پرنوسان (احتیاط بیشتر توصیه می‌شود)"
    else:
        regime, label = "normal", "نوسان‌پذیری در محدوده‌ی معمول"

    return {"volatility_pct": round(vol, 2), "regime": regime, "label_fa": label}


"""
--- نحوه‌ی وصل‌کردن به main.py (چون indicators.py رو نداشتم) ---

در main.py، بعد از این‌که indicators = calculate_all_indicators(...) رو داری
و coin.price_history (همون چیزی که الان به index.html هم می‌ره) در دسترسه:

    from market_regime import calculate_market_regime
    regime_info = calculate_market_regime(price_history)
    # و در دیکشنری خروجی هر کوین (همونی که در analysis.json ذخیره می‌شه):
    coin_result["market_regime"] = regime_info

هیچ تغییری در decision.py یا indicators.py لازم نیست؛ این فقط یه فیلد اضافه به
خروجی هر کوینه که index.html می‌تونه نمایش بده (به‌روزرسانی index.html پیوست شده).
"""
