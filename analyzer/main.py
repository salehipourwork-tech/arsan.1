"""
آرسان - اجرای کامل زنجیره تحلیل (نسخه ۳)
دریافت داده -> محاسبه شاخص‌ها -> تصمیم‌گیری -> ذخیره در data/analysis.json
                                              -> ثبت در data/history.json
                                              -> ارزیابی سیگنال‌های قدیمی‌تر
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

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "analysis.json")
DELAY_BETWEEN_COINS_SECONDS = 2


def run_analysis():
    snapshot = get_current_snapshot(DEFAULT_COINS)
    results = []
    had_error = False

    for coin_id in DEFAULT_COINS:
        try:
            market_chart = get_market_chart(coin_id, days=30)
            indicators = calculate_all_indicators(market_chart)
            decision_result = make_decision(indicators)

            coin_snapshot = snapshot.get(coin_id, {})
            current_price = coin_snapshot.get("usd", indicators["last_price"])

            results.append({
                "id": coin_id,
                "current_price": current_price,
                "change_24h": coin_snapshot.get("usd_24h_change"),
                "decision": decision_result["decision"],
                "score": decision_result["score"],
                "reasons": decision_result["reasons"],
                "disclaimer": decision_result["disclaimer"],
                "agreement_ratio": decision_result.get("agreement_ratio"),
                "trend_gate_triggered": decision_result.get("trend_gate_triggered", False),
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

            # ثبت این تصمیم در تاریخچه، برای ارزیابی دقت در آینده (مشکل ۵ و ۷ گزارش)
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

    # بررسی سیگنال‌های قدیمی‌تر که به موعد ارزیابی (۲۴ ساعت) رسیدن
    try:
        eval_result = evaluate_pending_signals()
        print(f"[main] ارزیابی سیگنال‌های قدیمی: {eval_result['updated_records']} رکورد به‌روزرسانی شد.")
    except Exception as exc:
        print(f"[main] خطا در ارزیابی سیگنال‌های قدیمی: {exc}")


if __name__ == "__main__":
    run_analysis()
