"""
RSP — ingestion/sources/coinbase_source.py

Coinbase Exchange Public API — /products/{id}/candles — رایگان، بدون Key.
محدودیت: granularity مجاز فقط {60,300,900,3600,21600,86400} است، یعنی
4H بومی ندارد. برای 4H از تجمیع (resample) کندل‌های واقعی 1H همین صرافی
استفاده می‌کنیم - همچنان داده‌ی واقعی صرافی است، فقط دانه‌بندی‌اش با
resample درشت‌تر شده (متفاوت از بازسازی از سری قیمت CoinGecko).
"""

import requests
import pandas as pd

from RSP.ingestion.symbol_map import get_symbol
from RSP.ingestion.sources.base import SourceResult

BASE_URL = "https://api.exchange.coinbase.com/products/{product}/candles"

GRANULARITY_SECONDS = {"15M": 900, "1H": 3600, "1D": 86400}   # 4H ندارد


def _fetch_raw(product: str, granularity: int):
    resp = requests.get(BASE_URL.format(product=product), params={"granularity": granularity}, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP_{resp.status_code}:{resp.text[:150]}")
    raw = resp.json()
    if not raw:
        raise RuntimeError("EMPTY_RESPONSE")
    # Coinbase row: [time, low, high, open, close, volume]  (newest first)
    df = pd.DataFrame(raw, columns=["time", "low", "high", "open", "close", "volume"])
    df["ts"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("ts")
    df = df[["open", "high", "low", "close", "volume"]].astype(float).sort_index()
    return df


def fetch_ohlcv(coin_id: str, timeframe: str, limit: int = 300) -> SourceResult:
    product = get_symbol(coin_id, "coinbase")
    if not product:
        return SourceResult(source_name="coinbase", ok=False, error="SYMBOL_NOT_MAPPED")

    try:
        if timeframe == "4H":
            hourly = _fetch_raw(product, GRANULARITY_SECONDS["1H"])
            df = hourly.resample("4h").agg({"open": "first", "high": "max",
                                              "low": "min", "close": "last", "volume": "sum"}).dropna()
        else:
            granularity = GRANULARITY_SECONDS.get(timeframe)
            if not granularity:
                return SourceResult(source_name="coinbase", ok=False, error="TIMEFRAME_NOT_SUPPORTED")
            df = _fetch_raw(product, granularity)
    except (requests.RequestException, RuntimeError) as exc:
        return SourceResult(source_name="coinbase", ok=False, error=str(exc))

    df = df.iloc[-limit:]
    return SourceResult(source_name="coinbase", ok=True, df=df, is_reconstructed=False)
