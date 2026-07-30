"""
آرسان - آزمایشگاه بک‌تست (نسخه ۵، کاملاً مستقل از روند اصلی)

هدف: پاسخ به این سوال بدون نیاز به هفته‌ها صبر برای جمع‌شدن داده‌ی زنده —
«اگه آرسان ۳۰ یا ۶۰ روز پیش وجود داشت و فقط داده‌ی همون‌موقع رو می‌دید،
تصمیم‌هاش چقدر درست از آب درمی‌اومد؟»

--- قوانین جداسازی (خیلی مهم، طبق درخواست صریح کاربر) ---
۱) این فایل هرگز از main.py صدا زده نمی‌شه و هیچ‌کدوم از فایل‌های
   data/analysis.json, data/history.json, data/accuracy_summary.json,
   data/portfolio.json, data/sentiment.json رو نمی‌خونه یا نمی‌نویسه.
   فقط و فقط یک فایل جدید می‌سازه: data/backtest_summary.json
۲) اجرا با ورک‌فلوی گیت‌هاب اکشن کاملاً جدا و جدا از analyze.yml انجام می‌شه
   (.github/workflows/backtest_lab.yml) — هفتگی + دستی.
۳) weights.json دست‌نخورده می‌مونه؛ فقط تابع make_decision (از decision.py،
   بدون هیچ تغییری) با داده‌ی گذشته صدا زده می‌شه — یعنی هر بهبودی که بعداً
   در موتور تصمیم‌گیری زنده اعمال بشه، خودکار به این آزمایشگاه هم می‌رسه،
   بدون این‌که این آزمایشگاه چیزی از رفتار زنده رو عوض کنه.

--- محدودیت صادقانه‌ای که همیشه در خروجی JSON نوشته می‌شه ---
فاکتور «احساسات اخبار» قابل شبیه‌سازی تاریخی نیست (تیتر خبر واقعی هر روز
گذشته در دسترس نیست)، پس همیشه خنثی (۰.۰) پاس داده می‌شه. یعنی دقت این
آزمایشگاه، دقت «۱۰ فاکتور تکنیکال از ۱۱ فاکتور واقعی سیستم» است، نه دقت کامل
سیستم زنده با اخبار.

--- جلوگیری از نگاه‌به‌آینده (lookahead bias) ---
برای شبیه‌سازی «روز t» یک کوین، فقط از prices[0..t] و volumes[0..t] همون کوین
(و برای فاکتور btc_alignment، همون بازه از BTC) استفاده می‌شه — هیچ داده‌ای
بعد از روز t دیده نمی‌شه. نتیجه‌ی سیگنال آن روز، ۲۴ ساعت بعد (روز t+1) با
همون قانون evaluate_signals.py (حداقل ۰.۵٪ حرکت در جهت پیش‌بینی‌شده) ارزیابی
می‌شود. فقط سیگنال‌های «خرید»/«فروش» ارزیابی می‌شوند؛ «صبر»/«نامشخص» — دقیقاً
مثل سیستم زنده — در محاسبه‌ی دقت شمرده نمی‌شوند.
"""

import json
import os
import time
from datetime import datetime, timezone

from fetch_data import get_market_chart
from indicators import calculate_all_indicators
from decision import make_decision
from market_regime import calculate_market_regime

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "backtest_summary.json")

# زیرمجموعه‌ی کوچیک‌تر برای سرعت بیشتر (طبق تصمیم صریح در گفت‌وگو با کاربر)
BACKTEST_COINS = ["bitcoin", "ethereum", "binancecoin", "ripple", "solana", "cardano"]
BTC_COIN_ID = "bitcoin"

WINDOWS = [30, 60]           # هر دو بازه، قابل‌انتخاب در خود صفحه
MAX_WINDOW = max(WINDOWS)
MIN_LOOKBACK_DAYS = 60       # حداقل تاریخچه قبل از اولین روز شبیه‌سازی‌شده
FETCH_DAYS = 150             # >۹۰ روز یعنی CoinGecko خودکار داده‌ی روزانه می‌ده
MIN_MOVE_PERCENT = 0.5       # دقیقاً همون قانون evaluate_signals.py
DELAY_BETWEEN_COINS_SECONDS = 2


def _slice(prices, volumes, upto_idx):
    """فقط داده‌ی تا اندیس upto_idx (شامل خودش) — خط دفاعی اصلی در برابر
    نگاه‌به‌آینده. هیچ‌جای دیگه‌ی این فایل نباید مستقیم prices/volumes کامل
    رو به calculate_all_indicators بده."""
    return {"prices": prices[: upto_idx + 1], "volumes": volumes[: upto_idx + 1]}


def _daily_trend_diff(prices, volumes, upto_idx):
    """روند diff_pct در یک لحظه‌ی مشخص از گذشته — فقط برای فاکتور btc_alignment."""
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
    برای یک کوین، حداکثر MAX_WINDOW روز اخیر رو روز‌به‌روز شبیه‌سازی می‌کنه.
    خروجی: لیستی از رکوردهای روزانه (فقط buy/sell قابل‌ارزیابی‌ان؛ hold/uncertain
    با correct=None ثبت می‌شن، دقیقاً برای شفافیت آماری، نه برای محاسبه‌ی دقت).
    """
    n = len(prices)
    # آخرین اندیس قابل‌شبیه‌سازی = n-2 (چون به روز t+1 برای ارزیابی ۲۴ ساعته نیازه)
    last_valid_t = n - 2
    first_valid_t = MIN_LOOKBACK_DAYS
    if last_valid_t < first_valid_t:
        return []  # داده‌ی کافی نیست

    start_t = max(first_valid_t, last_valid_t - MAX_WINDOW + 1)

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
            news_sentiment=0.0,  # محدودیت شناخته‌شده: بدون داده‌ی خبری تاریخی — همیشه خنثی
            btc_trend_diff_pct=coin_btc_diff,
            risk_profile="balanced",
            market_regime=regime_info["regime"],
        )

        entry_price = prices[t][1]
        exit_price = prices[t + 1][1]
        entry_date = datetime.fromtimestamp(prices[t][0] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")

        decision = decision_result["decision"]
        correct = None
        if decision in ("buy", "sell"):
            change_percent = (exit_price - entry_price) / entry_price * 100
            correct = (
                change_percent >= MIN_MOVE_PERCENT if decision == "buy"
                else change_percent <= -MIN_MOVE_PERCENT
            )

        records.append({
            "coin": coin_id,
            "date": entry_date,
            "day_index": t,
            "decision": decision,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "correct": correct,
        })

    return records


def _build_window_summary(all_records, window_days):
    """از انتهای رکوردهای هر کوین، window_days روز آخر رو برمی‌داره و آمار می‌سازه."""
    by_coin_records = {}
    for r in all_records:
        by_coin_records.setdefault(r["coin"], []).append(r)

    windowed = []
    for recs in by_coin_records.values():
        recs_sorted = sorted(recs, key=lambda x: x["day_index"])
        windowed.extend(recs_sorted[-window_days:])

    evaluated = [r for r in windowed if r["correct"] is not None]
    by_decision = {}
    for decision in ("buy", "sell"):
        subset = [r for r in evaluated if r["decision"] == decision]
        correct = sum(1 for r in subset if r["correct"])
        by_decision[decision] = {
            "total": len(subset),
            "correct": correct,
            "accuracy_percent": round(correct / len(subset) * 100, 1) if subset else None,
        }
    total_correct = sum(v["correct"] for v in by_decision.values())
    total_count = sum(v["total"] for v in by_decision.values())

    by_coin = {}
    for coin, recs in by_coin_records.items():
        recs_sorted = sorted(recs, key=lambda x: x["day_index"])[-window_days:]
        coin_evaluated = [r for r in recs_sorted if r["correct"] is not None]
        coin_correct = sum(1 for r in coin_evaluated if r["correct"])
        by_coin[coin] = {
            "total": len(coin_evaluated),
            "correct": coin_correct,
            "accuracy_percent": round(coin_correct / len(coin_evaluated) * 100, 1) if coin_evaluated else None,
            "hold_or_uncertain_days": len(recs_sorted) - len(coin_evaluated),
        }

    sample_trades = sorted(
        [r for r in windowed if r["correct"] is not None],
        key=lambda x: x["day_index"], reverse=True,
    )[:20]

    return {
        "window_days": window_days,
        "overall": {
            "total": total_count,
            "correct": total_correct,
            "accuracy_percent": round(total_correct / total_count * 100, 1) if total_count else None,
        },
        "by_decision": by_decision,
        "by_coin": by_coin,
        "sample_trades": sample_trades,
    }


def run_backtest():
    all_records = []

    print(f"[backtest_lab] دریافت تاریخچه‌ی {BTC_COIN_ID} ({FETCH_DAYS} روز)...")
    btc_chart = get_market_chart(BTC_COIN_ID, days=FETCH_DAYS)
    btc_prices, btc_volumes = btc_chart["prices"], btc_chart["volumes"]

    for coin_id in BACKTEST_COINS:
        try:
            if coin_id == BTC_COIN_ID:
                prices, volumes = btc_prices, btc_volumes
            else:
                print(f"[backtest_lab] دریافت تاریخچه‌ی {coin_id} ({FETCH_DAYS} روز)...")
                chart = get_market_chart(coin_id, days=FETCH_DAYS)
                prices, volumes = chart["prices"], chart["volumes"]

            records = _simulate_coin(coin_id, prices, volumes, btc_prices, btc_volumes)
            all_records.extend(records)
            print(f"[backtest_lab] {coin_id}: {len(records)} روز شبیه‌سازی شد.")
        except Exception as exc:
            print(f"[backtest_lab] خطا در {coin_id}: {exc}")

        time.sleep(DELAY_BETWEEN_COINS_SECONDS)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "type": "historical_simulation",
        "coins": BACKTEST_COINS,
        "note": (
            "این یک شبیه‌سازی روی داده‌ی تاریخی قیمت/حجم است، نه عملکرد زنده‌ی سایت. "
            "کاملاً مستقل از data/analysis.json و data/accuracy_summary.json محاسبه شده."
        ),
        "limitations": [
            "فاکتور «احساسات اخبار» در این شبیه‌سازی خنثی (۰) در نظر گرفته شده، چون تیتر خبر "
            "واقعی روزهای گذشته در دسترس نیست — یعنی این عدد، دقت ۱۰ فاکتور تکنیکال از ۱۱ "
            "فاکتور واقعی سیستم است، نه دقت کامل سیستم زنده.",
            "برای هر روز شبیه‌سازی‌شده فقط از داده‌ی تا همون روز استفاده شده (بدون نگاه به آینده).",
            "فقط سیگنال‌های «خرید»/«فروش» ارزیابی می‌شوند (دقیقاً مثل سیستم زنده)؛ «صبر»/«نامشخص» "
            "در محاسبه‌ی دقت شمرده نمی‌شوند.",
        ],
        "windows": {
            str(w): _build_window_summary(all_records, w) for w in WINDOWS
        },
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"[backtest_lab] کامل شد. خروجی: {OUTPUT_PATH}")


if __name__ == "__main__":
    run_backtest()
