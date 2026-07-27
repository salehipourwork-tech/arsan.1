"""
آرسان - موتور تصمیم‌گیری امتیازدهی‌شده (نسخه ۲)

منطق نسخه ۲:
- هر شاخص یک امتیاز مستقل بین -2 تا +2 می‌دهد (مثبت = گرایش به خرید، منفی = گرایش به فروش).
- هر شاخص یک «وزن» دارد که اهمیت نسبی آن را نشان می‌دهد.
- «قدرت روند» (trend_strength) به‌عنوان ضریب اطمینان روی شاخص‌های روندی/مومنتوم اعمال می‌شود:
  اگر روند ضعیف باشد، امتیاز آن شاخص‌ها تعدیل (کم‌اثر) می‌شود تا در بازارهای بی‌روند
  سیگنال کاذب کمتر صادر شود.
- امتیاز نهایی = میانگین وزنی همه‌ی شاخص‌ها، سپس به درصد (-100 تا +100) تبدیل می‌شود.
- این روش نسبت به نسخه ۱ هم «حساس‌تر» است (چون شاخص‌های بیشتری با وزن کمتر هم دیده می‌شوند
  و امتیازهای ضعیف هم در نتیجه اثر می‌گذارند) و هم «کم‌خطاتر» (چون هیچ شاخص واحدی به‌تنهایی
  نمی‌تواند کل تصمیم را عوض کند).

آستانه‌ی تصمیم (قابل تنظیم در همین فایل، پارامترهای BUY_THRESHOLD / SELL_THRESHOLD):
  امتیاز نهایی >= BUY_THRESHOLD   -> خرید
  امتیاز نهایی <= SELL_THRESHOLD  -> فروش
  در غیر این صورت                -> صبر
"""

BUY_THRESHOLD = 20     # از 100-  تا 100+
SELL_THRESHOLD = -20

# وزن هر شاخص (مجموع وزن‌ها مهم نیست، فقط اهمیت نسبی مهم است)
WEIGHTS = {
    "rsi": 1.4,
    "macd": 1.2,
    "trend": 1.4,
    "volume_trend": 0.7,
    "bollinger": 1.0,
    "stochastic_rsi": 0.9,
    "obv_trend": 0.8,
    "ema_cross": 1.1,
    "support_resistance": 0.9,
}


def _score_rsi(rsi):
    if rsi <= 25:
        return 2.0
    if rsi <= 35:
        return 1.2
    if rsi <= 45:
        return 0.4
    if rsi >= 75:
        return -2.0
    if rsi >= 65:
        return -1.2
    if rsi >= 55:
        return -0.4
    return 0.0


def _score_macd(macd_data):
    hist = macd_data["histogram"]
    hist_prev = macd_data["histogram_prev"]
    rising = hist > hist_prev
    if hist > 0:
        return 1.6 if rising else 1.0
    if hist < 0:
        return -1.6 if not rising else -1.0
    return 0.0


def _score_trend(trend_diff_pct):
    if trend_diff_pct > 4:
        return 2.0
    if trend_diff_pct > 1:
        return 1.0
    if trend_diff_pct < -4:
        return -2.0
    if trend_diff_pct < -1:
        return -1.0
    return 0.0


def _score_volume(volume_label, trend_diff_pct):
    """حجم بالا فقط زمانی سیگنال می‌دهد که همسو با جهت روند باشد (تاییدکننده)."""
    if volume_label == "بالا":
        return 1.0 if trend_diff_pct > 0 else (-1.0 if trend_diff_pct < 0 else 0.0)
    return 0.0


def _score_bollinger(position):
    # position: 0 (روی باند پایین) تا 1 (روی باند بالا)
    if position <= 0.05:
        return 2.0
    if position <= 0.2:
        return 1.0
    if position >= 0.95:
        return -2.0
    if position >= 0.8:
        return -1.0
    return 0.0


def _score_stochastic_rsi(value):
    if value <= 10:
        return 2.0
    if value <= 20:
        return 1.0
    if value >= 90:
        return -2.0
    if value >= 80:
        return -1.0
    return 0.0


def _score_obv(label):
    mapping = {
        "تاییدکننده صعود": 1.2,
        "تاییدکننده نزول": -1.2,
        "واگرایی هشداردهنده (صعود بدون حمایت حجم)": -0.8,
        "واگرایی هشداردهنده (نزول بدون فشار فروش واقعی)": 0.8,
        "خنثی": 0.0,
        "نامشخص": 0.0,
    }
    return mapping.get(label, 0.0)


def _score_ema_cross(label):
    if label == "کراس طلایی اخیر (صعودی)":
        return 1.6
    if label == "کراس مرگ اخیر (نزولی)":
        return -1.6
    return 0.0


def _score_support_resistance(last_price, support, resistance):
    if resistance == support:
        return 0.0
    range_size = resistance - support
    distance_to_support_pct = (last_price - support) / range_size
    if distance_to_support_pct <= 0.08:
        return 1.6
    if distance_to_support_pct <= 0.2:
        return 0.8
    if distance_to_support_pct >= 0.92:
        return -1.6
    if distance_to_support_pct >= 0.8:
        return -0.8
    return 0.0


def _confidence_multiplier(trend_strength):
    """اگر روند ضعیف باشد (بازار بی‌جهت)، اثر شاخص‌های روندی/مومنتوم را کم می‌کنیم."""
    if trend_strength >= 40:
        return 1.0
    if trend_strength >= 20:
        return 0.75
    return 0.5


def make_decision(indicators):
    """
    indicators: خروجی indicators.calculate_all_indicators
    خروجی: {"decision": "buy"|"sell"|"hold", "score": float, "reasons": [str,...], "factors": {...}}
    """
    confidence = _confidence_multiplier(indicators["trend_strength"])

    raw_scores = {
        "rsi": _score_rsi(indicators["rsi"]),
        "macd": _score_macd(indicators["macd"]) * confidence,
        "trend": _score_trend(indicators["trend"]["diff_pct"]) * confidence,
        "volume_trend": _score_volume(indicators["volume_trend"]["label"], indicators["trend"]["diff_pct"]),
        "bollinger": _score_bollinger(indicators["bollinger"]["position"]),
        "stochastic_rsi": _score_stochastic_rsi(indicators["stochastic_rsi"]),
        "obv_trend": _score_obv(indicators["obv_trend"]),
        "ema_cross": _score_ema_cross(indicators["ema_cross"]) * confidence,
        "support_resistance": _score_support_resistance(
            indicators["last_price"], indicators["support"], indicators["resistance"]
        ),
    }

    weighted_sum = sum(raw_scores[k] * WEIGHTS[k] for k in raw_scores)
    max_possible = sum(2.0 * WEIGHTS[k] for k in raw_scores)
    final_score_pct = (weighted_sum / max_possible) * 100 if max_possible else 0.0
    final_score_pct = round(final_score_pct, 1)

    if final_score_pct >= BUY_THRESHOLD:
        decision = "buy"
    elif final_score_pct <= SELL_THRESHOLD:
        decision = "sell"
    else:
        decision = "hold"

    reasons = _build_reasons(indicators, raw_scores, confidence)

    return {
        "decision": decision,
        "score": final_score_pct,
        "reasons": reasons,
        "factors": raw_scores,
        "disclaimer": (
            "این تحلیل صرفاً بر اساس داده‌های بازار و شاخص‌های تکنیکال تولید شده و "
            "هیچ تضمینی برای سود یا پیش‌بینی قطعی قیمت نیست. تصمیم نهایی همیشه با شماست."
        ),
    }


def _build_reasons(ind, scores, confidence):
    reasons = []

    if scores["rsi"] > 0.3:
        reasons.append(f"RSI در محدوده اشباع فروش قرار دارد ({ind['rsi']:.1f}) که معمولاً نشانه فرصت خرید است.")
    elif scores["rsi"] < -0.3:
        reasons.append(f"RSI در محدوده اشباع خرید قرار دارد ({ind['rsi']:.1f}) که معمولاً نشانه احتیاط یا فروش است.")

    if scores["macd"] > 0.3:
        reasons.append("MACD مثبت و در جهت تقویت است.")
    elif scores["macd"] < -0.3:
        reasons.append("MACD منفی و در جهت تضعیف است.")

    if scores["trend"] > 0.3:
        reasons.append(f"روند قیمت {ind['trend']['label']} تشخیص داده شده است.")
    elif scores["trend"] < -0.3:
        reasons.append(f"روند قیمت {ind['trend']['label']} تشخیص داده شده است.")

    if scores["volume_trend"] != 0:
        reasons.append(f"حجم معاملات {ind['volume_trend']['label']} است و همسو با روند فعلی حرکت می‌کند.")

    if scores["bollinger"] > 0.3:
        reasons.append("قیمت نزدیک باند پایین بولینگر است (اشباع فروش احتمالی).")
    elif scores["bollinger"] < -0.3:
        reasons.append("قیمت نزدیک باند بالای بولینگر است (اشباع خرید احتمالی).")

    if scores["stochastic_rsi"] > 0.3:
        reasons.append("استوکاستیک RSI در ناحیه اشباع فروش است.")
    elif scores["stochastic_rsi"] < -0.3:
        reasons.append("استوکاستیک RSI در ناحیه اشباع خرید است.")

    if scores["obv_trend"] != 0:
        reasons.append(f"وضعیت حجم تجمعی (OBV): {ind['obv_trend']}.")

    if scores["ema_cross"] > 0.3:
        reasons.append("کراس طلایی اخیر بین میانگین‌های متحرک رخ داده (سیگنال صعودی).")
    elif scores["ema_cross"] < -0.3:
        reasons.append("کراس مرگ اخیر بین میانگین‌های متحرک رخ داده (سیگنال نزولی).")

    if scores["support_resistance"] > 0.3:
        reasons.append("قیمت نزدیک سطح حمایت ۳۰ روز اخیر است.")
    elif scores["support_resistance"] < -0.3:
        reasons.append("قیمت نزدیک سطح مقاومت ۳۰ روز اخیر است.")

    if confidence < 1.0:
        reasons.append("قدرت روند فعلی پایین است؛ به همین دلیل امتیاز شاخص‌های روندی با احتیاط بیشتری اعمال شد.")

    if not reasons:
        reasons.append("هیچ سیگنال قوی خرید یا فروشی مشاهده نشد؛ بازار در وضعیت خنثی است.")

    return reasons
