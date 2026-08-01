"""
RSP — ingestion/sources/coinbase_source.py

Coinbase Exchange Public API — /products/{id}/candles — رایگان، بدون Key.
محدودیت: granularity مجاز فقط {60,300,900,3600,21600,86400} است (4H بومی
ندارد؛ از تجمیع کندل‌های واقعی 1H ساخته می‌شود) و هر درخواست حداکثر ۳۰۰
کندل برمی‌گرداند. برای بازه‌ی طولانی، با start/end (ISO8601) رو به عقب
صفحه‌بندی می‌کنیم.
"""

import time
from datetime import datetime, timedelta, timezone
import requests
import pandas as pd

from RSP.ingestion.symbol_map import get_symbol
from RSP.ingestion.sources.base import SourceResult

BASE_URL = "https://api.exchange.coinbase.com/products/{product}/candles"

GRANULARITY_SECONDS = {"15M": 900, "1H": 3600, "1D": 86400}   # 4H ندارد
MAX_PER_CALL = 300


def _fetch_page(product, granularity, start_iso, end_iso):
    resp = requests.get(BASE_URL.format(product=product),
                         params={"granularity": granularity, "start": start_iso, "end": end_iso},
                         timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP_{resp.status_code}:{resp.text[:150]}")
    raw = resp.json()
    if not raw:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    # Coinbase row: [time, low, high, open, close, volume]  (newest first)
    df = pd.DataFrame(raw, columns=["time", "low", "high", "open", "close", "volume"])
    df["ts"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.set_index("ts")
    return df[["open", "high", "low", "close", "volume"]].astype(float).sort_index()


def _fetch_paginated(product, granularity, target_count):
    pages = []
    remaining = target_count
    end_dt = datetime.now(timezone.utc)
    max_pages = 25

    for _ in range(max_pages):
        start_dt = end_dt - timedelta(seconds=granularity * MAX_PER_CALL)
        page = _fetch_page(product, granularity, start_dt.isoformat(), end_dt.isoformat())
        if page.empty:
            break
        pages.append(page)
        remaining -= len(page)
        if remaining <= 0:
            break
        oldest = page.index[0].to_pydatetime()
        new_end_dt = oldest - timedelta(seconds=granularity)
        if new_end_dt >= end_dt:
            break
        end_dt = new_end_dt
        time.sleep(0.25)  # Coinbase rate limit عمومی محدودتر است

    if not pages:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.concat(pages).sort_index()
    return df[~df.index.duplicated(keep="last")]


def fetch_ohlcv(coin_id: str, timeframe: str, limit: int = 300) -> SourceResult:
    product = get_symbol(coin_id, "coinbase")
    if not product:
        return SourceResult(source_name="coinbase", ok=False, error="SYMBOL_NOT_MAPPED")

    try:
        if timeframe == "4H":
            hourly = _fetch_paginated(product, GRANULARITY_SECONDS["1H"], limit * 4 + 20)
            df = hourly.resample("4h").agg({"open": "first", "high": "max",
                                              "low": "min", "close": "last", "volume": "sum"}).dropna()
        else:
            granularity = GRANULARITY_SECONDS.get(timeframe)
            if not granularity:
                return SourceResult(source_name="coinbase", ok=False, error="TIMEFRAME_NOT_SUPPORTED")
            df = _fetch_paginated(product, granularity, limit)
    except (requests.RequestException, RuntimeError) as exc:
        return SourceResult(source_name="coinbase", ok=False, error=str(exc))

    if df.empty:
        return SourceResult(source_name="coinbase", ok=False, error="EMPTY_RESPONSE")

    df = df.iloc[-limit:]
    return SourceResult(source_name="coinbase", ok=True, df=df, is_reconstructed=False)
