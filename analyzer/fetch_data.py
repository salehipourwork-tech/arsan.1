"""
ماژول دریافت داده بازار از CoinGecko (رایگان، بدون نیاز به API Key)
"""
import requests
import time

BASE_URL = "https://api.coingecko.com/api/v3"

# لیست رمزارزهایی که آرسان در MVP روی آن‌ها تحلیل انجام می‌دهد
# id ها باید دقیقاً همان id رسمی CoinGecko باشند
DEFAULT_COINS = [
    {"id": "bitcoin", "symbol": "BTC", "name": "Bitcoin"},
    {"id": "ethereum", "symbol": "ETH", "name": "Ethereum"},
    {"id": "binancecoin", "symbol": "BNB", "name": "BNB"},
    {"id": "ripple", "symbol": "XRP", "name": "XRP"},
    {"id": "solana", "symbol": "SOL", "name": "Solana"},
    {"id": "dogecoin", "symbol": "DOGE", "name": "Dogecoin"},
    {"id": "cardano", "symbol": "ADA", "name": "Cardano"},
    {"id": "tron", "symbol": "TRX", "name": "TRON"},
]


def _get(url, params=None, retries=3, backoff=5):
    """درخواست HTTP با تلاش مجدد ساده در صورت خطای موقت (مثل rate limit)"""
    for attempt in range(retries):
        resp = requests.get(url, params=params, timeout=20)
        if resp.status_code == 200:
            return resp.json()
        if resp.status_code == 429:
            time.sleep(backoff * (attempt + 1))
            continue
        resp.raise_for_status()
    resp.raise_for_status()


def get_market_chart(coin_id: str, days: int = 30, vs_currency: str = "usd"):
    """
    دریافت تاریخچه قیمت و حجم معاملات یک رمزارز.
    خروجی: لیستی از دیکشنری‌ها با کلیدهای timestamp, price, volume
    """
    url = f"{BASE_URL}/coins/{coin_id}/market_chart"
    params = {"vs_currency": vs_currency, "days": days}
    data = _get(url, params)

    prices = data.get("prices", [])
    volumes = data.get("total_volumes", [])

    merged = []
    for i in range(len(prices)):
        merged.append({
            "timestamp": prices[i][0],
            "price": prices[i][1],
            "volume": volumes[i][1] if i < len(volumes) else None,
        })
    return merged


def get_current_snapshot(coin_ids):
    """دریافت قیمت لحظه‌ای و تغییرات ۲۴ ساعته برای چند رمزارز همزمان"""
    url = f"{BASE_URL}/coins/markets"
    params = {
        "vs_currency": "usd",
        "ids": ",".join(coin_ids),
        "order": "market_cap_desc",
        "price_change_percentage": "24h",
    }
    return _get(url, params)
