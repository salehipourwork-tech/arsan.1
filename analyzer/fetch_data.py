"""
آرسان - دریافت داده‌های بازار از CoinGecko
نسخه ۲: بدون تغییر عمده نسبت به نسخه ۱ (فقط سازگار با ماژول‌های جدید indicators/decision)
"""

import time
import requests

COINGECKO_BASE = "https://api.coingecko.com/api/v3"

DEFAULT_COINS = [
    "bitcoin",
    "ethereum",
    "binancecoin",
    "ripple",
    "solana",
    "dogecoin",
    "cardano",
    "tron",
]

MAX_RETRIES = 5
BASE_BACKOFF_SECONDS = 5


def _get_with_retry(url, params=None):
    """درخواست GET با retry و backoff نمایی در صورت خطای 429 (rate limit)."""
    for attempt in range(1, MAX_RETRIES + 1):
        response = requests.get(url, params=params, timeout=30)
        if response.status_code == 200:
            return response.json()
        if response.status_code == 429:
            wait_time = BASE_BACKOFF_SECONDS * attempt
            print(f"[fetch_data] Rate limited (429). Waiting {wait_time}s (attempt {attempt}/{MAX_RETRIES})...")
            time.sleep(wait_time)
            continue
        response.raise_for_status()
    raise RuntimeError(f"Failed to fetch {url} after {MAX_RETRIES} retries (rate limited).")


def get_market_chart(coin_id, days=30):
    """
    تاریخچه قیمت و حجم برای coin_id در days روز اخیر.
    خروجی: {"prices": [[timestamp_ms, price], ...], "volumes": [[timestamp_ms, volume], ...]}
    """
    url = f"{COINGECKO_BASE}/coins/{coin_id}/market_chart"
    params = {"vs_currency": "usd", "days": days}
    data = _get_with_retry(url, params)
    return {
        "prices": data.get("prices", []),
        "volumes": data.get("total_volumes", []),
    }


def get_current_snapshot(coin_ids):
    """
    قیمت لحظه‌ای و درصد تغییر ۲۴ ساعته برای لیستی از coin_id ها.
    خروجی: {coin_id: {"usd": price, "usd_24h_change": percent}, ...}
    """
    url = f"{COINGECKO_BASE}/simple/price"
    params = {
        "ids": ",".join(coin_ids),
        "vs_currencies": "usd",
        "include_24hr_change": "true",
    }
    return _get_with_retry(url, params)
