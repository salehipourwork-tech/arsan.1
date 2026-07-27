"""
آرسان - موتور تصمیم‌گیری امتیازدهی‌شده (نسخه ۳)

تغییرات نسبت به نسخه ۲ (برای رفع مشکل‌های ۱، ۲، ۳ و ۶ گزارش وضعیت):

۱) گیت واقعی «قدرت روند» (trend_strength):
   نسخه‌ی ۲ فقط ضریب اطمینان رو کم می‌کرد (حداقل ۰.۵)، هیچ‌وقت واقعاً سیگنال رو
   نمی‌بست. حالا اگر trend_strength از MIN_TREND_STRENGTH پایین‌تر باشه، تصمیم
   همیشه "hold" می‌شه، بدون توجه به امتیاز — چون بازار رِنج/بی‌جهته.

۲) معیار توافق (agreement ratio):
   قبلاً اگه فقط ۱-۲ شاخص قوی، امتیاز نهایی رو از آستانه رد می‌کردن، درحالی‌که
   بقیه‌ی شاخص‌ها خنثی یا مخالف بودن، بازم "buy"/"sell" قطعی صادر می‌شد
   (این دقیقاً همون باگ امتیاز ۲۱.۹ با برچسب خرید بود). حالا اگه اکثر شاخص‌های
   «جهت‌دار» با علامت امتیاز نهایی هم‌جهت نباشن، تصمیم "uncertain" می‌شه.

۳) منبع واحد حقیقت برای برچسب:
   تصمیم فقط و فقط از روی final_score_pct (بعد از اعمال گیت‌ها) ساخته می‌شه —
   هیچ مسیر دیگه‌ای برای تعیین decision وجود نداره.

نکته‌ی مهم سازگاری: ورودی/خروجی make_decision(indicators) دقیقاً مثل قبل
است — main.py نیازی به تغییر ساختاری نداره، فقط دو فیلد جدید
("trend_gate_triggered", "agreement_ratio") به خروجی اضافه شده که اختیاری‌ان
و می‌تونن بعداً در داشبورد یا لاگ استفاده بشن.

مقدار جدید "uncertain" برای decision اضافه شده (قبلاً فقط buy/sell/hold بود).
این یعنی index.html باید یه حالت نمایشی برای "uncertain" هم اضافه کنه
(پیشنهاد: 🟣 نامشخص یا 🟡 با متن متفاوت از "صبر").
"""

import json
import os

BUY_THRESHOLD = 20     # از 100-  تا 100+
SELL_THRESHOLD = -20

# گیت قدرت روند: زیر این مقدار، بازار «بی‌روند» حساب می‌شه (نگاه کن به
# calculate_trend_direction در indicators.py: diff_pct=1 مرز خنثی/ضعیف است،
# و trend_strength تقریباً diff_pct*10 است؛ پس MIN=15 یعنی diff_pct~1.5%)
MIN_TREND_STRENGTH = 15
STRONG_TREND_STRENGTH = 40   # همون مرز "صعودی/نزولی قوی" در indicators.py (diff_pct=4 -> strength=40)

# حداقل نسبت توافق بین شاخص‌های «جهت‌دار» با علامت امتیاز نهایی
MIN_AGREEMENT_RATIO = 0.55
# آستانه‌ای که پایین‌تر از اون یک شاخص «خنثی» حساب می‌شه (نه موافق نه مخالف)
NEUTRAL_ZONE = 0.3

_WEIGHTS_PATH = os.path.join(os.path.dirname(__file__), "weights.json")


def _load_weights():
    """
    وزن‌ها حالا در weights.json نگه داشته می‌شن (نه هاردکد اینجا) تا فاز بک‌تست
    آینده (مشکل شماره ۴ و ۵ گزارش) بتونه خودکار تنظیمشون کنه.
    """
    with open(_WEIGHTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


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
    if volume_label == "بالا":
        return 1.0 if trend_diff_pct > 0 else (-1.0 if trend_diff_pct < 0 else 0.0)
    return 0.0


def _score_bollinger(position):
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
    """
    نسخه‌ی ۳: به‌جای پله‌ی سه‌تایی قبلی (که هیچ‌وقت زیر ۰.۵ نمی‌رفت)، حالا
    این تابع فقط داخل «محدوده‌ی روند‌دار» (بالای MIN_TREND_STRENGTH) صدا زده
    می‌شه، چون زیرش make_decision اصلاً گیت می‌زنه و به اینجا نمی‌رسه.
    بین MIN_TREND_STRENGTH و STRONG_TREND_STRENGTH به‌صورت خطی از ۰.۳ به ۱.۰ می‌ره.
    """
    if trend_strength >= STRONG_TREND_STRENGTH:
        return 1.0
    span = STRONG_TREND_STRENGTH - MIN_TREND_STRENGTH
    return 0.3 + 0.7 * (trend_strength - MIN_TREND_STRENGTH) / span


def make_decision(indicators):
    """
    indicators: خروجی indicators.calculate_all_indicators
    خروجی: {"decision": "buy"|"sell"|"hold"|"uncertain", "score": float,
            "reasons": [str,...], "factors": {...},
            "agreement_ratio": float|None, "trend_gate_triggered": bool}
    """
    weights = _load_weights()
    trend_strength = indicators["trend_strength"]

    # ---------- گام ۱: گیت واقعی قدرت روند (مشکل ۲ و ۶) ----------
    if trend_strength < MIN_TREND_STRENGTH:
        reasons = [
            f"قدرت روند فعلی خیلی پایینه ({trend_strength:.0f} از ۱۰۰) — بازار در حال حاضر "
            "رِنج/بی‌جهته و سیگنال خرید یا فروش قابل‌اعتماد نیست.",
        ]
        return {
            "decision": "hold",
            "score": 0.0,
            "reasons": reasons,
            "factors": {},
            "agreement_ratio": None,
            "trend_gate_triggered": True,
            "disclaimer": _disclaimer(),
        }

    confidence = _confidence_multiplier(trend_strength)

    # امتیاز خام هر شاخص، قبل از اعمال ضریب اطمینان — برای معیار توافق استفاده می‌شه
    base_scores = {
        "rsi": _score_rsi(indicators["rsi"]),
        "macd": _score_macd(indicators["macd"]),
        "trend": _score_trend(indicators["trend"]["diff_pct"]),
        "volume_trend": _score_volume(indicators["volume_trend"]["label"], indicators["trend"]["diff_pct"]),
        "bollinger": _score_bollinger(indicators["bollinger"]["position"]),
        "stochastic_rsi": _score_stochastic_rsi(indicators["stochastic_rsi"]),
        "obv_trend": _score_obv(indicators["obv_trend"]),
        "ema_cross": _score_ema_cross(indicators["ema_cross"]),
        "support_resistance": _score_support_resistance(
            indicators["last_price"], indicators["support"], indicators["resistance"]
        ),
    }

    # ضریب اطمینان فقط روی شاخص‌های روندی/مومنتوم اعمال می‌شه (مثل نسخه ۲)
    scored = dict(base_scores)
    scored["macd"] *= confidence
    scored["trend"] *= confidence
    scored["ema_cross"] *= confidence

    weighted_sum = sum(scored[k] * weights[k] for k in scored)
    max_possible = sum(2.0 * weights[k] for k in scored)
    final_score_pct = round((weighted_sum / max_possible) * 100, 1) if max_possible else 0.0

    # ---------- گام ۲: معیار توافق (مشکل ۱ و ۳) ----------
    overall_sign = 1 if final_score_pct >= 0 else -1
    directional = [v for v in base_scores.values() if abs(v) >= NEUTRAL_ZONE]
    if directional:
        agree_count = sum(1 for v in directional if (1 if v > 0 else -1) == overall_sign)
        agreement_ratio = agree_count / len(directional)
    else:
        agreement_ratio = 0.0

    would_cross_threshold = final_score_pct >= BUY_THRESHOLD or final_score_pct <= SELL_THRESHOLD

    if would_cross_threshold and agreement_ratio < MIN_AGREEMENT_RATIO:
        reasons = [
            f"امتیاز خام {final_score_pct:.1f} بود، اما شاخص‌ها با هم هم‌جهت نیستن "
            f"(فقط {agreement_ratio*100:.0f}٪ توافق) — بعضی صعودی و بعضی نزولی‌اند، "
            "پس سیگنال قطعی صادر نمی‌شه.",
        ]
        return {
            "decision": "uncertain",
            "score": final_score_pct,
            "reasons": reasons,
            "factors": scored,
            "agreement_ratio": round(agreement_ratio, 2),
            "trend_gate_triggered": False,
            "disclaimer": _disclaimer(),
        }

    # ---------- گام ۳: تصمیم نهایی (منبع واحد حقیقت — مشکل ۱) ----------
    if final_score_pct >= BUY_THRESHOLD:
        decision = "buy"
    elif final_score_pct <= SELL_THRESHOLD:
        decision = "sell"
    else:
        decision = "hold"

    reasons = _build_reasons(indicators, scored, confidence, agreement_ratio)

    return {
        "decision": decision,
        "score": final_score_pct,
        "reasons": reasons,
        "factors": scored,
        "agreement_ratio": round(agreement_ratio, 2),
        "trend_gate_triggered": False,
        "disclaimer": _disclaimer(),
    }


def _disclaimer():
    return (
        "این تحلیل صرفاً بر اساس داده‌های بازار و شاخص‌های تکنیکال تولید شده و "
        "هیچ تضمینی برای سود یا پیش‌بینی قطعی قیمت نیست. تصمیم نهایی همیشه با شماست."
    )


def _build_reasons(ind, scores, confidence, agreement_ratio):
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
        reasons.append("قدرت روند فعلی متوسط است؛ به همین دلیل امتیاز شاخص‌های روندی با احتیاط بیشتری اعمال شد.")

    reasons.append(f"توافق بین شاخص‌ها: {agreement_ratio*100:.0f}٪.")

    if not reasons:
        reasons.append("هیچ سیگنال قوی خرید یا فروشی مشاهده نشد؛ بازار در وضعیت خنثی است.")

    return reasons
