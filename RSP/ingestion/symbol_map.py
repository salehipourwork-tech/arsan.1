"""
RSP — ingestion/symbol_map.py

نگاشت coin_id (فرمت CoinGecko که در آرسان اصلی هم استفاده می‌شود) به نماد
هر صرافی. اگر یک صرافی نماد یک کوین را نداشته باشد، مقدار None می‌گذاریم و
router خودش آن صرافی را برای آن کوین رد می‌کند (بدون خطا).
"""

SYMBOL_MAP = {
    "bitcoin":     {"binance": "BTCUSDT", "kucoin": "BTC-USDT", "kraken": "XBTUSD",  "coinbase": "BTC-USD"},
    "ethereum":    {"binance": "ETHUSDT", "kucoin": "ETH-USDT", "kraken": "ETHUSD",  "coinbase": "ETH-USD"},
    "binancecoin": {"binance": "BNBUSDT", "kucoin": "BNB-USDT", "kraken": None,      "coinbase": None},
    "ripple":      {"binance": "XRPUSDT", "kucoin": "XRP-USDT", "kraken": "XRPUSD",  "coinbase": "XRP-USD"},
    "solana":      {"binance": "SOLUSDT", "kucoin": "SOL-USDT", "kraken": "SOLUSD",  "coinbase": "SOL-USD"},
    "dogecoin":    {"binance": "DOGEUSDT", "kucoin": "DOGE-USDT", "kraken": "DOGEUSD", "coinbase": "DOGE-USD"},
    "cardano":     {"binance": "ADAUSDT", "kucoin": "ADA-USDT", "kraken": "ADAUSD",  "coinbase": "ADA-USD"},
    "tron":        {"binance": "TRXUSDT", "kucoin": "TRX-USDT", "kraken": None,      "coinbase": None},
}


def get_symbol(coin_id: str, exchange: str):
    return SYMBOL_MAP.get(coin_id, {}).get(exchange)
