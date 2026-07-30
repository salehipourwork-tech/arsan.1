"""
آرسان - آزمایشگاه تشخیصی افق ارزیابی (کاملاً مستقل، بخشی از «آزمایشگاه»)

هدف: یه سوال مشخص و تشخیصی — «آیا سیگنال‌های آرسان به‌خاطر تاخیر ذاتی
EMA20/50 دقیقاً سر نقاط برگشت روند اشتباه می‌کنن، یا مشکل جای دیگه‌ایه؟»
این فایل هیچ چیزی رو تغییر نمی‌ده یا تصمیم نمی‌گیره؛ فقط همون سیگنال‌هایی
که make_decision می‌ده رو با افق‌های ارزیابی مختلف (۱، ۳، ۵ روز) می‌سنجه
و نتیجه رو کنار هم می‌ذاره تا مقایسه ممکن بشه.

--- قوانین جداسازی (دقیقاً هم‌راستا با backtest_lab.py) ---
۱) هیچ‌کدوم از فایل‌های data/analysis.json, data/history.json,
   data/accuracy_summary.json, data/portfolio.json, data/sentiment.json,
   data/backtest_summary.json رو نمی‌خونه یا نمی‌نویسه.
   فقط یک فایل جدید می‌سازه: data/backtest_horizon_summary.json
۲) decision.py و weights.json دست‌نخورده می‌مونن — فقط با داده‌ی گذشته صدا
   زده می‌شن، دقیقاً مثل backtest_lab.py.
۳) اجرا فقط دستی (workflow_dispatch) — چون این یه ابزار تشخیصیه، نه بخشی
   از چرخه‌ی هفتگی/زنده‌ی سیستم.

--- منطق افق‌ها ---
افق ۱ روزه + آستانه ۰.۵٪  = دقیقاً همون قانون evaluate_signals.py / backtest_lab.py
افق ۳ روزه + آستانه ۱.۵٪  = تشخیصی
افق ۵ روزه + آستانه ۲.۰٪  = تشخیصی
اگه دقت با افق‌های بلندتر به‌وضوح بهتر بشه، فرضیه‌ی «تاخیر EMA» تأیید می‌شه.
"""

import json
import os
import time
from datetime import datetime, timezone

from fetch_data import get_market_chart
from indicators import calculate_all_indicators
from decision import make_decision
from market_regime import calculate_market_regime

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "backtest_horizon_summary.json")

BACKTEST_COINS = ["bitcoin", "ethereum", "binancecoin", "ripple", "solana", "cardano"]
BTC_COIN_ID = "bitcoin"

# (نام نمایشی, تعداد روز جلوتر برای ارزیابی, حداقل درصد حرکت لازم)
HORIZONS = [
    {"key": "1d", "label_fa": "۱ روزه (استاندارد)", "days_ahead": 1, "min_move_percent": 0.5},
    {"key": "3d", "label_fa": "۳ روزه (تشخیصی)", "days_ahead": 3, "min_move_percent": 1.5},
    {"key": "5d", "label_fa": "۵ روزه (تشخیصی)", "days_ahead": 5, "min_move_percent": 2.0},
]

WINDOW_DAYS = 60             # فقط یک بازه (۶۰ روزه) برای این تست — کافیه برای مقایسه
MIN_LOOKBACK_DAYS = 60
FETCH_DAYS = 150
DELAY_BETWEEN_COINS_SECONDS = 2
MAX_DAYS_AHEAD = max(h["days_ahead"] for h in HORIZONS)


def _slice(prices, volumes, upto_idx):
    return {"prices": prices[: upto_idx + 1], "volumes": volumes[: upto_idx + 1]}


def _daily_trend_diff(prices, volumes, upto_idx):
    chart = _slice(prices, volumes, upto_idx)
    if len(chart["prices"]) < 15:
        return None
    try:
        ind = calculate_all_indicators(chart)
        return ind["trend"]["diff_pct"]
    except Exception:
        return None


def _simulate_coin(coin_id, prices, volumes, btc_prices, btc_volumes):
    """
    درست مثل backtest_lab.py، با یه فرق: به‌جای این‌که فقط روز t+1 رو چک کنه،
    برای هر روز t، تصمیم رو یک‌بار می‌سازه و نتیجه‌ش رو با قیمتِ t+1، t+3 و t+5
    (هر کدوم که داده داشته باشه) مقایسه می‌کنه — یعنی تصمیم عوض نمی‌شه، فقط
    «چند روز بعد چک می‌کنیم» عوض می‌شه.
    """
    n = len(prices)
    last_valid_t = n - 1 - MAX_DAYS_AHEAD
    first_valid_t = MIN_LOOKBACK_DAYS
    if last_valid_t < first_valid_t:
        return []

    start_t = max(first_valid_t, last_valid_t - WINDOW_DAYS + 1)

    records = []
    for t in range(start_t, last_valid_t + 1):
        chart = _slice(prices, volumes, t)
        try:
            indicators = calculate_all_indicators(chart)
        except Exception:
            continue

        coin_btc_diff = (
            None if coin_id == BTC_COIN_ID
            else _daily_trend_diff(btc_prices, btc_volumes, t)
        )

        # نسخه ۵: رژیم بازار هم فقط با داده‌ی تا همون روز t محاسبه می‌شه
        # (chart بالا از قبل با _slice تا t بریده شده) تا نگاه‌به‌آینده رخ نده.
        regime_info = calculate_market_regime(indicators, chart["prices"])

        decision_result = make_decision(
            indicators,
            news_sentiment=0.0,
            btc_trend_diff_pct=coin_btc_diff,
            risk_profile="balanced",
            market_regime=regime_info["regime"],
            # این تست فقط اثر «افق ارزیابی» رو می‌سنجه، نه فیلتر momentum رو —
            # پس اون فیلتر رو موقتاً خاموش می‌کنیم تا نمونه کامل بمونه و دو
            # متغیر با هم قاطی نشن. سیستم زنده و backtest_lab.py هیچ‌کدوم از
            # این سوییچ استفاده نمی‌کنن؛ پیش‌فرضشون (True) دست‌نخورده می‌مونه.
            apply_momentum_gate=False,
        )
        decision = decision_result["decision"]
        entry_price = prices[t][1]
        entry_date = datetime.fromtimestamp(prices[t][0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")

        by_horizon = {}
        if decision in ("buy", "sell"):
            for h in HORIZONS:
                exit_idx = t + h["days_ahead"]
                if exit_idx >= n:
                    continue
                exit_price = prices[exit_idx][1]
                change_percent = (exit_price - entry_price) / entry_price * 100
                correct = (
                    change_percent >= h["min_move_percent"] if decision == "buy"
                    else change_percent <= -h["min_move_percent"]
                )
                by_horizon[h["key"]] = {"exit_price": exit_price, "correct": correct}

        records.append({
            "coin": coin_id,
            "date": entry_date,
            "day_index": t,
            "decision": decision,
            "entry_price": entry_price,
            "by_horizon": by_horizon,
        })

    return records


def _build_summary(all_records):
    summary_by_horizon = {}
    for h in HORIZONS:
        key = h["key"]
        evaluated = [r for r in all_records if key in r["by_horizon"]]
        by_decision = {}
        for decision in ("buy", "sell"):
            subset = [r for r in evaluated if r["decision"] == decision]
            correct = sum(1 for r in subset if r["by_horizon"][key]["correct"])
            by_decision[decision] = {
                "total": len(subset),
                "correct": correct,
                "accuracy_percent": round(correct / len(subset) * 100, 1) if subset else None,
            }
        total = sum(v["total"] for v in by_decision.values())
        correct_total = sum(v["correct"] for v in by_decision.values())
        summary_by_horizon[key] = {
            "label_fa": h["label_fa"],
            "days_ahead": h["days_ahead"],
            "min_move_percent": h["min_move_percent"],
            "overall": {
                "total": total,
                "correct": correct_total,
                "accuracy_percent": round(correct_total / total * 100, 1) if total else None,
            },
            "by_decision": by_decision,
        }
    return summary_by_horizon


def run_horizon_backtest():
    all_records = []

    print(f"[backtest_horizon_lab] دریافت تاریخچه‌ی {BTC_COIN_ID} ({FETCH_DAYS} روز)...")
    btc_chart = get_market_chart(BTC_COIN_ID, days=FETCH_DAYS)
    btc_prices, btc_volumes = btc_chart["prices"], btc_chart["volumes"]

    for coin_id in BACKTEST_COINS:
        try:
            if coin_id == BTC_COIN_ID:
                prices, volumes = btc_prices, btc_volumes
            else:
                print(f"[backtest_horizon_lab] دریافت تاریخچه‌ی {coin_id} ({FETCH_DAYS} روز)...")
                chart = get_market_chart(coin_id, days=FETCH_DAYS)
                prices, volumes = chart["prices"], chart["volumes"]

            records = _simulate_coin(coin_id, prices, volumes, btc_prices, btc_volumes)
            all_records.extend(records)
            print(f"[backtest_horizon_lab] {coin_id}: {len(records)} روز شبیه‌سازی شد.")
        except Exception as exc:
            print(f"[backtest_horizon_lab] خطا در {coin_id}: {exc}")

        time.sleep(DELAY_BETWEEN_COINS_SECONDS)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "type": "horizon_diagnostic",
        "purpose": (
            "این یه ابزار تشخیصیه، نه بخشی از سیستم زنده. سوالی که جواب می‌ده: "
            "آیا با چک‌کردن نتیجه‌ی سیگنال بعد از ۳ یا ۵ روز (به‌جای ۱ روز)، دقت "
            "بهتر می‌شه؟ اگه بله، یعنی تاخیر ذاتی EMA۲۰/۵۰ علت اصلی خطاهای فعلیه."
        ),
        "coins": BACKTEST_COINS,
        "window_days": WINDOW_DAYS,
        "horizons": _build_summary(all_records),
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[backtest_horizon_lab] کامل شد. خروجی: {OUTPUT_PATH}")


if __name__ == "__main__":
    run_horizon_backtest()
