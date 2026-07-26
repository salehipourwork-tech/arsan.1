"""
اسکریپت اصلی آرسان.
این فایل توسط GitHub Actions به صورت زمان‌بندی‌شده اجرا می‌شود:
۱) داده بازار را از CoinGecko می‌گیرد
۲) شاخص‌های تکنیکال را محاسبه می‌کند
۳) تصمیم خرید/فروش/صبر را تولید می‌کند
۴) همه چیز را در data/analysis.json ذخیره می‌کند تا فرانت‌اند آن را نمایش دهد
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

from fetch_data import DEFAULT_COINS, get_market_chart, get_current_snapshot
import indicators as ind
import decision as dec

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "analysis.json")


def analyze_coin(coin):
    chart = get_market_chart(coin["id"], days=30)
    prices = [p["price"] for p in chart]
    volumes = [p["volume"] for p in chart if p["volume"] is not None]

    if len(prices) < 30:
        return None

    computed = ind.compute_all(prices, volumes)
    result = dec.decide(computed)

    return {
        "id": coin["id"],
        "symbol": coin["symbol"],
        "name": coin["name"],
        "indicators": computed,
        "decision": result,
        "price_history": [
            {"t": p["timestamp"], "p": round(p["price"], 6)} for p in chart
        ],
    }


def main():
    print("Arsan: شروع تحلیل...")
    results = []

    snapshot = {}
    try:
        snap_data = get_current_snapshot([c["id"] for c in DEFAULT_COINS])
        snapshot = {item["id"]: item for item in snap_data}
    except Exception as e:
        print(f"هشدار: دریافت snapshot لحظه‌ای ناموفق بود: {e}")

    for coin in DEFAULT_COINS:
        try:
            print(f"در حال تحلیل {coin['symbol']}...")
            analysis = analyze_coin(coin)
            if analysis is None:
                print(f"  داده کافی برای {coin['symbol']} نبود، رد شد.")
                continue

            snap = snapshot.get(coin["id"], {})
            analysis["change_24h"] = snap.get("price_change_percentage_24h")
            analysis["market_cap"] = snap.get("market_cap")

            results.append(analysis)
            time.sleep(2)  # جلوگیری از rate-limit CoinGecko
        except Exception as e:
            print(f"خطا در تحلیل {coin['symbol']}: {e}")

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "coins": results,
    }

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"Arsan: تحلیل {len(results)} رمزارز کامل شد. خروجی در {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
