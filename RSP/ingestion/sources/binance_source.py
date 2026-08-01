"""
RSP — ingestion/sources/binance_source.py

Binance Public REST API — /api/v3/klines — رایگان، بدون نیاز به API Key
برای داده‌ی عمومی بازار. کندل‌های واقعی صرافی (نه بازسازی‌شده).
مستندات: https://binance-docs.github.io/apidocs/spot/en/#kline-candlestick-data

Pagination: هر درخواست حداکثر ۱۰۰۰ کندل برمی‌گرداند. برای بازه‌های طولانی
(مثلاً ۹۰ روز از کندل ۱۵ دقیقه‌ای = ۸۶۴۰ کندل)، با حرکت `endTime` به عقب
چند درخواست پشت‌سرهم می‌زنیم تا به تعداد کندل خواسته‌شده برسیم.
"""

import time
import requests
import pandas as pd

from RSP.ingestion.symbol_map import get_symbol
from RSP.ingestion.sources.base import SourceResult

BASE_URL = "https://api.binance.com/api/v3/klines"

INTERVAL_MAP = {"15M": "15m", "1H": "1h", "4H": "4h", "1D": "1d"}
INTERVAL_MS = {"15M": 15 * 60_000, "1H": 60 * 60_000, "4H": 4 * 60 * 60_000, "1D": 24 * 60 * 60_000}
MAX_PER_CALL = 1000

COLUMNS = ["open_time", "open", "high", "low", "close", "volume",
           "close_time", "quote_asset_volume", "n_trades",
           "taker_buy_base", "taker_buy_quote", "ignore"]


def _fetch_page(symbol, interval, end_time_ms=None, limit=1000):
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    if end_time_ms is not None:
        params["endTime"] = end_time_ms
    resp = requests.get(BASE_URL, params=params, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP_{resp.status_code}:{resp.text[:150]}")
    raw = resp.json()
    if not raw or not isinstance(raw, list):
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    df = pd.DataFrame(raw, columns=COLUMNS)
    df["ts"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("ts")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df[["open", "high", "low", "close", "volume"]]


def fetch_ohlcv(coin_id: str, timeframe: str, limit: int = 300) -> SourceResult:
    symbol = get_symbol(coin_id, "binance")
    if not symbol:
        return SourceResult(source_name="binance", ok=False, error="SYMBOL_NOT_MAPPED")
    interval = INTERVAL_MAP.get(timeframe)
    if not interval:
        return SourceResult(source_name="binance", ok=False, error="TIMEFRAME_NOT_SUPPORTED")

    interval_ms = INTERVAL_MS[timeframe]
    pages = []
    end_time_ms = None
    remaining = limit
    max_pages = 30  # سقف امنیتی تا در صورت خطای داده به حلقه‌ی بی‌پایان نیفتیم

    try:
        for _ in range(max_pages):
            page_limit = min(MAX_PER_CALL, remaining)
            page = _fetch_page(symbol, interval, end_time_ms=end_time_ms, limit=page_limit)
            if page.empty:
                break
            pages.append(page)
            remaining -= len(page)
            if remaining <= 0:
                break
            # صفحه‌ی بعدی: قبل از قدیمی‌ترین کندلِ همین صفحه
            oldest_ts_ms = int(page.index[0].timestamp() * 1000)
            new_end_time_ms = oldest_ts_ms - interval_ms
            if end_time_ms is not None and new_end_time_ms >= end_time_ms:
                break  # جلوگیری از حلقه‌ی بی‌پایان اگر داده تمام شده باشد
            end_time_ms = new_end_time_ms
            time.sleep(0.15)  # رعایت ادب Rate Limit بین صفحات
    except requests.RequestException as exc:
        if not pages:
            return SourceResult(source_name="binance", ok=False, error=str(exc))
        # اگر بخشی از صفحات گرفته شده بود، همان‌ها را برمی‌گردانیم (بهتر از هیچ)
    except RuntimeError as exc:
        if not pages:
            return SourceResult(source_name="binance", ok=False, error=str(exc))

    if not pages:
        return SourceResult(source_name="binance", ok=False, error="EMPTY_RESPONSE")

    df = pd.concat(pages).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df = df.iloc[-limit:]

    return SourceResult(source_name="binance", ok=True, df=df, is_reconstructed=False)
