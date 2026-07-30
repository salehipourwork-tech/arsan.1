"""
آرسان - موتور تصمیم‌گیری امتیازدهی‌شده (نسخه ۴)

--- تغییرات نسبت به نسخه ۳ ---

۱) فاکتور یازدهم: btc_alignment (دسته B، گزارش وضعیت)
   آلت‌کوین‌ها معمولاً دنباله‌روی روند کلی بیت‌کوین هستن. اگه روند کوین با روند
   BTC هم‌جهت باشه، اعتماد به اون روند تقویت می‌شه؛ اگه واگرا باشه (مثلاً کوین
   داره صعود می‌کنه ولی BTC در حال نزوله)، این یه پرچم احتیاطه چون همچین
   حرکتی معمولاً پایدار نیست.
   ورودی جدید تابع: btc_trend_diff_pct (همون diff_pct که از indicators.py برای
   خود BTC محاسبه می‌شه — دقیقاً هم‌مقیاس با indicators["trend"]["diff_pct"]).
   اگه این مقدار پاس داده نشه (None، پیش‌فرض)، فاکتور خنثی (۰.۰) می‌مونه و
   هیچ تاثیری نداره — یعنی کاملاً سازگار با نسخه ۳ است تا وقتی main.py آپدیت بشه.
   نکته‌ی مهم: weights.json باید کلید "btc_alignment" رو داشته باشه. اگه نداشته
   باشه (فایل نسخه ۳ رو عوض نکرده باشی)، خودکار وزن ۰.۸ در نظر گرفته می‌شه —
   پس چیزی خراب نمی‌شه، ولی توصیه می‌شه دستی این خط رو به weights.json اضافه کنی:
       "btc_alignment": 0.8

۲) حالت‌های ریسک شخصی‌سازی‌شده (دسته D، گزارش وضعیت)
   قبلاً آستانه‌ها (BUY_THRESHOLD=20 و...) ثابت و سراسری بودن. حالا سه پروفایل
   از پیش تعریف شده وجود داره: "conservative" / "balanced" / "aggressive".
   پیش‌فرض "balanced" دقیقاً همون اعداد نسخه ۳ است — یعنی اگه چیزی رو صدا
   نزنی، رفتار برنامه هیچ فرقی نمی‌کنه.
   نکته‌ی مهم برای دفتر جلویی (index.html): چون score و agreement_ratio از قبل
   ذخیره می‌شن، سوییچ بین پروفایل‌ها لازم نیست دوباره از main.py صدا زده بشه —
   frontend می‌تونه با همین سه آستانه، decision رو دوباره از روی داده‌ی ذخیره‌شده
   محاسبه کنه (به بخش risk-profile در index.html نگاه کن).

۳) گیت برگشت روند اخیر (momentum reversal gate) — یافته‌ی بک‌تست
   توی داده‌های بک‌تست دیدیم سیستم دقیقاً سر نقاطی که روند تازه داشت برمی‌گشت
   (مثلاً بیت‌کوین در حال صعود، ولی EMA۲۰/۵۰ هنوز به‌خاطر افت‌های قبلی «نزولی»
   نشون می‌داد) بیشترین سیگنال‌های غلط رو صادر می‌کرد. علتش تاخیر ذاتی EMA۲۰/۵۰ است.
   راه‌حل: indicators.py حالا recent_momentum_pct رو هم می‌ده (تغییر خام قیمت در
   ۳ روز اخیر، مستقل از EMA). اگه سیگنال خرید/فروش با جهت این حرکت اخیر در تضاد
   باشه (مثلاً سیگنال فروشه ولی قیمت تازه ≥۱٪ بالا رفته)، به‌جای صدور سیگنال
   قطعی، «uncertain» برمی‌گردونیم — دقیقاً مثل گیت agreement_ratio موجود، فقط با
   منبع دیگه‌ای از شک. weights.json و بقیه‌ی امتیازدهی دست‌نخورده مونده.

--- بدون تغییر نسبت به نسخه ۳ (خلاصه) ---
گیت قدرت روند، معیار توافق وزن‌دار، منبع واحد حقیقت برای برچسب — همه دست‌نخورده.

--- نسخه ۵ (بازطراحی موتور تحلیل: تشخیص رژیم بازار + وزن‌دهی پویا) ---
تغییر اصلی: make_decision حالا یک آرگومان جدید می‌گیره: market_regime (رشته‌ای
مثل "uptrend"/"range"/"volatile"/... — خروجی market_regime.calculate_market_regime).
منطق جدید:

    وزن پایه (weights.json) × ضریب رژیم (regime_weights.py) = وزن نهایی فاکتور

یعنی به‌جای این‌که وزن هر فاکتور برای همه‌ی حالت‌های بازار ثابت باشه، اول
مشخص می‌شه «الان چه نوع بازاری داریم» و بعد اهمیت هر فاکتور بر همون اساس
تعدیل می‌شه (مثلاً در بازار رنج، RSI/بولینگر مهم‌ترن؛ در روند قوی، MACD/EMA
Cross مهم‌ترن). جزئیات و منطق هر رژیم در regime_weights.py مستند شده.

سازگاری با کدهای قدیمی (نسخه ۴ و قبل‌تر، مثل backtest_lab.py که همچنان
market_regime رو پاس نمی‌ده): اگه market_regime پاس داده نشه (پیش‌فرض None)،
regime_weights.apply_regime_multipliers ضریب خالی برمی‌گردونه یعنی همه‌ی
ضرایب ۱.۰ می‌مونن — دقیقاً هم‌ارز رفتار نسخه‌های قبلی، بدون هیچ تغییری در
نتیجه‌ی نهایی. خروجی make_decision هم یک فیلد جدید "market_regime" (همون
رشته‌ی ورودی) داره تا در history.json/optimize_weights.py قابل ردیابی باشه.
"""

import json
import os

from regime_weights import apply_regime_multipliers

# ---------------- پروفایل‌های ریسک (دسته D) ----------------
RISK_PROFILES = {
    "conservative": {
        "buy_threshold": 30,
        "sell_threshold": -30,
        "min_agreement_ratio": 0.65,
        "min_trend_strength": 20,
    },
    "balanced": {  # == اعداد ثابت نسخه ۳، پیش‌فرض
        "buy_threshold": 20,
        "sell_threshold": -20,
        "min_agreement_ratio": 0.55,
        "min_trend_strength": 15,
    },
    "aggressive": {
        "buy_threshold": 12,
        "sell_threshold": -12,
        "min_agreement_ratio": 0.45,
        "min_trend_strength": 10,
    },
}

STRONG_TREND_STRENGTH = 40
NEUTRAL_ZONE = 0.3
REVERSAL_INDICATORS = ["rsi", "bollinger", "stochastic_rsi"]
LOW_VOLUME_CONFIDENCE = 0.6
DEFAULT_BTC_ALIGNMENT_WEIGHT = 0.8

# گیت برگشت روند اخیر (نسخه ۴) — این‌قدر درصد حرکت اخیر خلاف جهت سیگنال کافیه
# که به‌جای خرید/فروش قطعی، «صبر» بدیم. عدد اولیه‌ی معقول است، نه علمی‌کالیبره‌شده؛
# بعد از جمع‌شدن داده‌ی زنده‌ی بیشتر قابل تنظیم دقیق‌تره.
MOMENTUM_REVERSAL_THRESHOLD = 1.0

_WEIGHTS_PATH = os.path.join(os.path.dirname(__file__), "weights.json")


def _load_weights():
    with open(_WEIGHTS_PATH, "r", encoding="utf-8") as f:
        weights = json.load(f)
    weights.setdefault("btc_alignment", DEFAULT_BTC_ALIGNMENT_WEIGHT)
    return weights


def _to_percent(score):
    return round((score + 100) / 2, 1)


def _score_rsi(rsi):
    if rsi <= 25: return 2.0
    if rsi <= 35: return 1.2
    if rsi <= 45: return 0.4
    if rsi >= 75: return -2.0
    if rsi >= 65: return -1.2
    if rsi >= 55: return -0.4
    return 0.0


def _score_macd(macd_data):
    hist, hist_prev = macd_data["histogram"], macd_data["histogram_prev"]
    rising = hist > hist_prev
    if hist > 0: return 1.6 if rising else 1.0
    if hist < 0: return -1.6 if not rising else -1.0
    return 0.0


def _score_trend(trend_diff_pct):
    if trend_diff_pct > 4: return 2.0
    if trend_diff_pct > 1: return 1.0
    if trend_diff_pct < -4: return -2.0
    if trend_diff_pct < -1: return -1.0
    return 0.0


def _score_volume(volume_label, trend_diff_pct):
    if volume_label == "بالا":
        return 1.0 if trend_diff_pct > 0 else (-1.0 if trend_diff_pct < 0 else 0.0)
    return 0.0


def _score_bollinger(position):
    if position <= 0.05: return 2.0
    if position <= 0.2: return 1.0
    if position >= 0.95: return -2.0
    if position >= 0.8: return -1.0
    return 0.0


def _score_stochastic_rsi(value):
    if value <= 10: return 2.0
    if value <= 20: return 1.0
    if value >= 90: return -2.0
    if value >= 80: return -1.0
    return 0.0


def _score_obv(label):
    mapping = {
        "تاییدکننده صعود": 1.2, "تاییدکننده نزول": -1.2,
        "واگرایی هشداردهنده (صعود بدون حمایت حجم)": -0.8,
        "واگرایی هشداردهنده (نزول بدون فشار فروش واقعی)": 0.8,
        "خنثی": 0.0, "نامشخص": 0.0,
    }
    return mapping.get(label, 0.0)


def _score_ema_cross(label):
    if label == "کراس طلایی اخیر (صعودی)": return 1.6
    if label == "کراس مرگ اخیر (نزولی)": return -1.6
    return 0.0


def _score_support_resistance(last_price, support, resistance):
    if resistance == support: return 0.0
    range_size = resistance - support
    d = (last_price - support) / range_size
    if d <= 0.08: return 1.6
    if d <= 0.2: return 0.8
    if d >= 0.92: return -1.6
    if d >= 0.8: return -0.8
    return 0.0


def _score_news_sentiment(sentiment_score):
    return max(-2.0, min(2.0, sentiment_score * 2))


def _score_btc_alignment(coin_diff_pct, btc_diff_pct):
    """
    دسته B — همبستگی با روند کلی بیت‌کوین.
    coin_diff_pct: همون indicators["trend"]["diff_pct"] خود کوین
    btc_diff_pct: همون مقدار ولی برای BTC؛ اگه None باشه یعنی این فاکتور هنوز
        وصل نشده (main.py قیمت BTC رو جدا نگرفته) — پس خنثی برمی‌گردونیم.
    """
    if btc_diff_pct is None:
        return 0.0
    coin_sign = 1 if coin_diff_pct > 0.5 else (-1 if coin_diff_pct < -0.5 else 0)
    btc_sign = 1 if btc_diff_pct > 0.5 else (-1 if btc_diff_pct < -0.5 else 0)
    if coin_sign == 0 or btc_sign == 0:
        return 0.0
    aligned = (coin_sign == btc_sign)
    magnitude = 1.5 if aligned else 1.0
    alignment_sign = 1 if aligned else -1
    return coin_sign * alignment_sign * magnitude


def _confidence_multiplier(trend_strength, min_trend_strength):
    if trend_strength >= STRONG_TREND_STRENGTH:
        return 1.0
    span = STRONG_TREND_STRENGTH - min_trend_strength
    return 0.3 + 0.7 * (trend_strength - min_trend_strength) / span


def make_decision(indicators, news_sentiment=0.0, btc_trend_diff_pct=None, risk_profile="balanced",
                   apply_momentum_gate=True, market_regime=None):
    """
    indicators: خروجی indicators.calculate_all_indicators
    news_sentiment: -۱ تا +۱ (پیش‌فرض خنثی)
    btc_trend_diff_pct: diff_pct روند BTC، هم‌مقیاس با indicators["trend"]["diff_pct"]
        (اختیاری؛ اگه پاس داده نشه فاکتور btc_alignment خنثی می‌مونه)
    risk_profile: "conservative" | "balanced" (پیش‌فرض) | "aggressive"
    apply_momentum_gate: پیش‌فرض True (رفتار زنده و آزمایشگاه اصلی). فقط توسط
        backtest_horizon_lab.py با False صدا زده می‌شه تا اثر «افق ارزیابی» رو
        بدون قاطی‌شدن با فیلتر momentum، با نمونه‌ی کامل بشه سنجید.
    market_regime: رشته‌ی رژیم فعلی بازار (خروجی
        market_regime.calculate_market_regime(...)["regime"]، مثل "uptrend"،
        "range"، "volatile"، ...). پیش‌فرض None یعنی وزن‌دهی پویا غیرفعاله و
        فقط وزن پایه‌ی weights.json استفاده می‌شه (سازگار با نسخه‌های قبلی و
        با کدهایی مثل backtest_lab.py که هنوز این آرگومان رو پاس نمی‌دن).

    خروجی مثل نسخه ۳ + فیلد "risk_profile" (نسخه ۴) + فیلد جدید "market_regime"
    (نسخه ۵) برای شفافیت این‌که این تصمیم با کدوم پروفایل و کدوم رژیم بازار
    محاسبه شده.
    """
    profile = RISK_PROFILES.get(risk_profile, RISK_PROFILES["balanced"])
    base_weights = _load_weights()
    weights = apply_regime_multipliers(base_weights, market_regime)
    trend_strength = indicators["trend_strength"]

    if trend_strength < profile["min_trend_strength"]:
        return {
            "decision": "hold",
            "score": 0.0,
            "score_percent": None,
            "reasons": [
                f"قدرت روند فعلی خیلی پایینه ({trend_strength:.0f} از ۱۰۰) — بازار در حال حاضر "
                "رِنج/بی‌جهته و سیگنال خرید یا فروش قابل‌اعتماد نیست."
            ],
            "factors": {},
            "agreement_ratio": None,
            "trend_gate_triggered": True,
            "momentum_gate_triggered": False,
            "risk_profile": risk_profile,
            "market_regime": market_regime,
            "disclaimer": _disclaimer(),
        }

    confidence = _confidence_multiplier(trend_strength, profile["min_trend_strength"])

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
        "news_sentiment": _score_news_sentiment(news_sentiment),
        "btc_alignment": _score_btc_alignment(indicators["trend"]["diff_pct"], btc_trend_diff_pct),
    }

    volume_confidence = LOW_VOLUME_CONFIDENCE if indicators["volume_trend"]["label"] == "پایین" else 1.0
    for k in REVERSAL_INDICATORS:
        base_scores[k] *= volume_confidence

    scored = dict(base_scores)
    scored["macd"] *= confidence
    scored["trend"] *= confidence
    scored["ema_cross"] *= confidence

    weighted_sum = sum(scored[k] * weights[k] for k in scored)
    max_possible = sum(2.0 * weights[k] for k in scored)
    final_score_pct = round((weighted_sum / max_possible) * 100, 1) if max_possible else 0.0

    overall_sign = 1 if final_score_pct >= 0 else -1
    directional_items = [(k, v) for k, v in base_scores.items() if abs(v) >= NEUTRAL_ZONE]
    if directional_items:
        total_strength = sum(weights[k] * abs(v) for k, v in directional_items)
        agree_strength = sum(
            weights[k] * abs(v) for k, v in directional_items if (1 if v > 0 else -1) == overall_sign
        )
        agreement_ratio = agree_strength / total_strength if total_strength else 0.0
    else:
        agreement_ratio = 0.0

    would_cross_threshold = (
        final_score_pct >= profile["buy_threshold"] or final_score_pct <= profile["sell_threshold"]
    )

    if would_cross_threshold and agreement_ratio < profile["min_agreement_ratio"]:
        return {
            "decision": "uncertain",
            "score": final_score_pct,
            "score_percent": _to_percent(final_score_pct),
            "reasons": [
                f"امتیاز خام {_to_percent(final_score_pct):.0f}٪ بود، اما شاخص‌ها با هم هم‌جهت نیستن "
                f"(فقط {agreement_ratio*100:.0f}٪ توافق) — بعضی صعودی و بعضی نزولی‌اند، "
                "پس سیگنال قطعی صادر نمی‌شه."
            ],
            "factors": scored,
            "agreement_ratio": round(agreement_ratio, 2),
            "trend_gate_triggered": False,
            "momentum_gate_triggered": False,
            "risk_profile": risk_profile,
            "market_regime": market_regime,
            "disclaimer": _disclaimer(),
        }

    if final_score_pct >= profile["buy_threshold"]:
        decision = "buy"
    elif final_score_pct <= profile["sell_threshold"]:
        decision = "sell"
    else:
        decision = "hold"

    # --- گیت برگشت روند اخیر ---
    # سیگنال قطعیه (buy/sell)، ولی قیمت در چند روز اخیر خلاف همون جهت حرکت کرده؟
    # این دقیقاً همون الگویی بود که در بک‌تست بیشترین خطا رو ایجاد می‌کرد.
    if apply_momentum_gate and decision in ("buy", "sell"):
        recent_momentum_pct = indicators.get("recent_momentum_pct", 0.0)
        signal_sign = 1 if decision == "buy" else -1
        momentum_opposes = (
            (signal_sign > 0 and recent_momentum_pct <= -MOMENTUM_REVERSAL_THRESHOLD) or
            (signal_sign < 0 and recent_momentum_pct >= MOMENTUM_REVERSAL_THRESHOLD)
        )
        if momentum_opposes:
            direction_fa = "صعودی" if decision == "buy" else "نزولی"
            return {
                "decision": "uncertain",
                "score": final_score_pct,
                "score_percent": _to_percent(final_score_pct),
                "reasons": [
                    f"شاخص‌های میان‌مدت روند {direction_fa} نشون می‌دن، اما قیمت در ۳ روز اخیر "
                    f"{abs(recent_momentum_pct):.1f}٪ در جهت مخالف حرکت کرده — این می‌تونه نشونه‌ی "
                    "شروع تغییر روند باشه، پس به‌جای سیگنال قطعی، صبر داده شد."
                ],
                "factors": scored,
                "agreement_ratio": round(agreement_ratio, 2),
                "trend_gate_triggered": False,
                "momentum_gate_triggered": True,
                "risk_profile": risk_profile,
                "market_regime": market_regime,
                "disclaimer": _disclaimer(),
            }

    reasons = _build_reasons(indicators, scored, confidence, agreement_ratio, volume_confidence, btc_trend_diff_pct,
                              market_regime)

    return {
        "decision": decision,
        "score": final_score_pct,
        "score_percent": _to_percent(final_score_pct),
        "reasons": reasons,
        "factors": scored,
        "agreement_ratio": round(agreement_ratio, 2),
        "trend_gate_triggered": False,
        "momentum_gate_triggered": False,
        "risk_profile": risk_profile,
        "market_regime": market_regime,
        "disclaimer": _disclaimer(),
    }


def _disclaimer():
    return (
        "این تحلیل صرفاً بر اساس داده‌های بازار و شاخص‌های تکنیکال تولید شده و "
        "هیچ تضمینی برای سود یا پیش‌بینی قطعی قیمت نیست. تصمیم نهایی همیشه با شماست."
    )


REGIME_REASON_FA = {
    "uptrend": "رژیم بازار «روند صعودی پایدار» تشخیص داده شد؛ وزن فاکتورهای دنباله‌روی روند (MACD، کراس EMA) افزایش یافت.",
    "downtrend": "رژیم بازار «روند نزولی پایدار» تشخیص داده شد؛ وزن فاکتورهای دنباله‌روی روند (MACD، کراس EMA) افزایش یافت.",
    "range": "رژیم بازار «رنج/خنثی» تشخیص داده شد؛ وزن فاکتورهای نوسان‌گیر (RSI، بولینگر) افزایش و فاکتورهای روندی کاهش یافت.",
    "quiet": "رژیم بازار «رنج و آرام» تشخیص داده شد؛ نوسان کم است و سیگنال‌ها با اطمینان کمی بیشتر وزن‌دهی شدند.",
    "volatile": "رژیم بازار «پرنوسان» تشخیص داده شد؛ وزن فاکتورهای باندمحور کاهش و وزن فاکتورهای تاییدی (حجم، هم‌سویی با BTC، اخبار) افزایش یافت.",
    "trend_change": "رژیم بازار «تغییر روند» تشخیص داده شد؛ وزن فاکتورهای تاخیری روندی به‌شدت کاهش یافت (پرریسک‌ترین حالت).",
}


def _build_reasons(ind, scores, confidence, agreement_ratio, volume_confidence, btc_trend_diff_pct,
                    market_regime=None):
    reasons = []
    if market_regime in REGIME_REASON_FA:
        reasons.append(REGIME_REASON_FA[market_regime])
    if scores["rsi"] > 0.3: reasons.append(f"RSI در محدوده اشباع فروش قرار دارد ({ind['rsi']:.1f}).")
    elif scores["rsi"] < -0.3: reasons.append(f"RSI در محدوده اشباع خرید قرار دارد ({ind['rsi']:.1f}).")
    if scores["macd"] > 0.3: reasons.append("MACD مثبت و در جهت تقویت است.")
    elif scores["macd"] < -0.3: reasons.append("MACD منفی و در جهت تضعیف است.")
    if scores["trend"] != 0: reasons.append(f"روند قیمت {ind['trend']['label']} تشخیص داده شده است.")
    if scores["volume_trend"] != 0: reasons.append(f"حجم معاملات {ind['volume_trend']['label']} است.")
    if scores["bollinger"] > 0.3: reasons.append("قیمت نزدیک باند پایین بولینگر است.")
    elif scores["bollinger"] < -0.3: reasons.append("قیمت نزدیک باند بالای بولینگر است.")
    if scores["stochastic_rsi"] > 0.3: reasons.append("استوکاستیک RSI در ناحیه اشباع فروش است.")
    elif scores["stochastic_rsi"] < -0.3: reasons.append("استوکاستیک RSI در ناحیه اشباع خرید است.")
    if scores["obv_trend"] != 0: reasons.append(f"وضعیت حجم تجمعی (OBV): {ind['obv_trend']}.")
    if scores["ema_cross"] > 0.3: reasons.append("کراس طلایی اخیر رخ داده (سیگنال صعودی).")
    elif scores["ema_cross"] < -0.3: reasons.append("کراس مرگ اخیر رخ داده (سیگنال نزولی).")
    if scores["support_resistance"] > 0.3: reasons.append("قیمت نزدیک سطح حمایت ۳۰ روز اخیر است.")
    elif scores["support_resistance"] < -0.3: reasons.append("قیمت نزدیک سطح مقاومت ۳۰ روز اخیر است.")
    if scores["news_sentiment"] > 0.3: reasons.append("احساسات اخبار ۲۴ ساعت اخیر مثبت بوده است.")
    elif scores["news_sentiment"] < -0.3: reasons.append("احساسات اخبار ۲۴ ساعت اخیر منفی بوده است.")
    if btc_trend_diff_pct is not None:
        if scores["btc_alignment"] > 0.3:
            reasons.append("روند این کوین با روند کلی بیت‌کوین هم‌جهت است (تقویت‌کننده).")
        elif scores["btc_alignment"] < -0.3:
            reasons.append("روند این کوین با روند کلی بیت‌کوین واگرا است (نیازمند احتیاط بیشتر).")
    if confidence < 1.0:
        reasons.append("قدرت روند فعلی متوسط است؛ امتیاز شاخص‌های روندی با احتیاط بیشتری اعمال شد.")
    if volume_confidence < 1.0:
        reasons.append("حجم معاملات پایین است؛ امتیاز شاخص‌های بازگشتی/اشباع با احتیاط بیشتری اعمال شد.")
    reasons.append(f"توافق بین شاخص‌ها: {agreement_ratio*100:.0f}٪.")
    if not reasons:
        reasons.append("هیچ سیگنال قوی خرید یا فروشی مشاهده نشد؛ بازار در وضعیت خنثی است.")
    return reasons
