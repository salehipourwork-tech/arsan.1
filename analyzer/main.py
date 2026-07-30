"""
آرسان - اجرای کامل زنجیره تحلیل (نسخه ۴)
دریافت داده -> محاسبه شاخص‌ها -> تصمیم‌گیری -> ذخیره در data/analysis.json
                                              -> ثبت در data/history.json
                                              -> ارزیابی سیگنال‌های قدیمی‌تر
                                              -> به‌روزرسانی پرتفوی فرضی سراسری

--- تغییرات نسبت به نسخه ۳ ---
۱) قبل از حلقه‌ی اصلی، یک‌بار روند خود BTC محاسبه می‌شه (btc_trend_diff_pct) و به
   make_decision هر کوین پاس داده می‌شه — این همون فاکتور btc_alignment در
   decision.py نسخه ۴ رو فعال می‌کنه. اگه این مرحله به هر دلیلی خطا بده، برنامه
   کرش نمی‌کنه؛ فقط btc_trend_diff_pct=None می‌مونه (دقیقاً رفتار نسخه ۳).
۲) بعد از محاسبه‌ی indicators هر کوین، market_regime.calculate_market_regime روی
   همون price_history صدا زده می‌شه و به خروجی هر کوین اضافه می‌شه (فیلد جدید،
   اختیاری، چیزی رو خراب نمی‌کنه).
۳) بعد از evaluate_pending_signals، portfolio_tracker.run() صدا زده می‌شه تا
   data/portfolio.json به‌روز بشه (پرتفوی فرضی سراسری).
۴) volume_news_alert.run() هم در انتها صدا زده می‌شه — چون fetch_data.py حالا
   واقعاً get_volume_snapshot رو داره (نسخه ۴)، دیگه فرضی نیست.
"""

import json
import os
import time
from datetime import datetime, timezone

from fetch_data import DEFAULT_COINS, get_market_chart, get_current_snapshot
from indicators import calculate_all_indicators
from decision import make_decision
from history_logger import log_decision
from evaluate_signals import evaluate_pending_signals
from news_sentiment import compute_all_sentiments
from market_regime import calculate_market_regime
from portfolio_tracker import run as run_portfolio_update
from volume_news_alert import run as run_alerts

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "analysis.json")
SENTIMENT_OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "sentiment.json")
DELAY_BETWEEN_COINS_SECONDS = 2

BTC_COIN_ID = "bitcoin"


def _get_btc_trend_diff_pct():
    """
    روند خود BTC رو جدا محاسبه می‌کنه تا به‌عنوان مبنای فاکتور btc_alignment در
    decision.py هر کوین دیگه استفاده بشه. اگه خطا بده، None برمی‌گردونه —
    یعنی فاکتور btc_alignment برای همه‌ی کوین‌ها خنثی می‌مونه (دقیقاً رفتار
    نسخه ۳، بدون کرش).
    """
    try:
        btc_chart = get_market_chart(BTC_COIN_ID, days=100)
        btc_indicators = calculate_all_indicators(btc_chart)
        return btc_indicators["trend"]["diff_pct"]
    except Exception as exc:
        print(f"[main] نتونستم روند BTC رو برای فاکتور btc_alignment بگیرم: {exc} — این فاکتور خنثی می‌مونه.")
        return None


def run_analysis():
    snapshot = get_current_snapshot(DEFAULT_COINS)
    btc_trend_diff_pct = _get_btc_trend_diff_pct()

    try:
        sentiments = compute_all_sentiments(DEFAULT_COINS)
    except Exception as exc:
        print(f"[main] خطا در تحلیل احساسات اخبار: {exc} — امتیاز خنثی (۰) برای همه در نظر گرفته می‌شه.")
        sentiments = {}

    results = []
    had_error = False

    for coin_id in DEFAULT_COINS:
        try:
            market_chart = get_market_chart(coin_id, days=100)
            indicators = calculate_all_indicators(market_chart)

            coin_sentiment = sentiments.get(coin_id, {})
            news_sentiment_score = coin_sentiment.get("score", 0.0)

            # برای خود BTC، مقایسه‌ی روند با روند خودش بی‌معنیه — پس None پاس داده
            # می‌شه (فاکتور btc_alignment برای BTC خودش خنثی می‌مونه).
            coin_btc_diff = None if coin_id == BTC_COIN_ID else btc_trend_diff_pct

            # نسخه ۵: رژیم بازار باید قبل از تصمیم‌گیری مشخص بشه، چون خود
            # make_decision از regime برای وزن‌دهی پویای فاکتورها استفاده می‌کنه.
            regime_info = calculate_market_regime(indicators, market_chart["prices"])

            decision_result = make_decision(
                indicators,
                news_sentiment=news_sentiment_score,
                btc_trend_diff_pct=coin_btc_diff,
                risk_profile="balanced",  # پیش‌فرض سراسری؛ سوییچ ریسک در frontend سمت کاربر انجام می‌شه
                market_regime=regime_info["regime"],
            )

            coin_snapshot = snapshot.get(coin_id, {})
            current_price = coin_snapshot.get("usd", indicators["last_price"])

            results.append({
                "id": coin_id,
                "current_price": current_price,
                "change_24h": coin_snapshot.get("usd_24h_change"),
                "decision": decision_result["decision"],
                "score": decision_result["score"],
                "score_percent": decision_result.get("score_percent"),
                "reasons": decision_result["reasons"],
                "factors": decision_result.get("factors", {}),
                "disclaimer": decision_result["disclaimer"],
                "agreement_ratio": decision_result.get("agreement_ratio"),
                "trend_gate_triggered": decision_result.get("trend_gate_triggered", False),
                "risk_profile": decision_result.get("risk_profile", "balanced"),
                "market_regime": regime_info,
                "news_sentiment": coin_sentiment,
                "indicators": {
                    "rsi": round(indicators["rsi"], 2),
                    "macd": indicators["macd"],
                    "trend": indicators["trend"],
                    "volume_trend": indicators["volume_trend"],
                    "support": indicators["support"],
                    "resistance": indicators["resistance"],
                    "bollinger": indicators["bollinger"],
                    "stochastic_rsi": round(indicators["stochastic_rsi"], 2),
                    "obv_trend": indicators["obv_trend"],
                    "ema_cross": indicators["ema_cross"],
                    "trend_strength": round(indicators["trend_strength"], 1),
                },
                "price_history": market_chart["prices"],
            })

            # نکته‌ی مهم برای optimize_weights.py (دسته C): این تصمیم رو کامل لاگ کن،
            # از جمله فیلد "factors" — اگه log_decision فعلی این فیلد رو ذخیره نمی‌کنه،
            # باید داخل history_logger.py اضافه‌ش کنی وگرنه optimize_weights.py همیشه
            # insufficient_data می‌مونه.
            log_decision(coin_id, current_price, decision_result)

        except Exception as exc:
            had_error = True
            print(f"[main] خطا در تحلیل {coin_id}: {exc}")

        time.sleep(DELAY_BETWEEN_COINS_SECONDS)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "had_error": had_error,
        "coins": results,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[main] تحلیل کامل شد. {len(results)} رمزارز پردازش شد. خروجی: {OUTPUT_PATH}")

    sentiment_output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "coins": sentiments,
    }
    os.makedirs(os.path.dirname(SENTIMENT_OUTPUT_PATH), exist_ok=True)
    with open(SENTIMENT_OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(sentiment_output, f, ensure_ascii=False, indent=2)
    print(f"[main] تحلیل احساسات اخبار ذخیره شد: {SENTIMENT_OUTPUT_PATH}")

    try:
        eval_result = evaluate_pending_signals()
        print(f"[main] ارزیابی سیگنال‌های قدیمی: {eval_result['updated_records']} رکورد به‌روزرسانی شد.")
    except Exception as exc:
        print(f"[main] خطا در ارزیابی سیگنال‌های قدیمی: {exc}")

    # دسته D: بعد از هر ارزیابی، پرتفوی فرضی سراسری هم به‌روز بشه (سبک، فقط از
    # history.json می‌خونه، هزینه‌ی اضافه‌ای نداره)
    try:
        portfolio_result = run_portfolio_update()
        print(f"[main] پرتفوی فرضی به‌روز شد: {portfolio_result['total_trades']} معامله، "
              f"سود/زیان {portfolio_result['total_pnl_usd']}$")
    except Exception as exc:
        print(f"[main] خطا در به‌روزرسانی پرتفوی فرضی: {exc}")

    # دسته B: هشدار جهش حجم/خبر — سبک و مستقل، هیچ‌کدوم به خروجی اصلی وابسته نیست
    try:
        alerts = run_alerts(coin_ids=DEFAULT_COINS)
        print(f"[main] بررسی هشدار حجم/خبر انجام شد: {len(alerts)} هشدار فعال.")
    except Exception as exc:
        print(f"[main] خطا در بررسی هشدار حجم/خبر: {exc}")


if __name__ == "__main__":
    run_analysis()
