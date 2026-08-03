"""
RSP — ingestion/sources/kucoin_source.py

KuCoin Public REST API — /api/v1/market/candles — رایگان، بدون API Key.
پوشش خوبی برای آلت‌کوین‌ها دارد (fallback خوب برای وقتی Binance در دسترس
جغرافیایی نیست یا rate-limit خورده).
مستندات: https://docs.kucoin.com/#get-klines

Pagination: با startAt/endAt (ثانیه) - هر درخواست معمولاً تا ~۱۵۰۰ کندل
برمی‌گرداند، ولی برای اطمینان پنجره‌های کوچک‌تر و چندباره می‌زنیم.
"""

import time
import requests
import pandas as pd

from RSP.ingestion.symbol_map import get_symbol
from RSP.ingestion.sources.base import SourceResult

BASE_URL = "https://api.kucoin.com/api/v1/market/candles"

TYPE_MAP = {"15M": "15min", "1H": "1hour", "4H": "4hour", "1D": "1day"}
INTERVAL_SECONDS = {"15M": 15 * 60, "1H": 60 * 60, "4H": 4 * 60 * 60, "1D": 24 * 60 * 60}
MAX_PER_CALL = 1500


def _fetch_page(symbol, kline_type, start_at=None, end_at=None, max_retries=3):
    params = {"symbol": symbol, "type": kline_type}
    if start_at is not None:
        params["startAt"] = start_at
    if end_at is not None:
        params["endAt"] = end_at

    last_exc = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(BASE_URL, params=params, timeout=15)
            if resp.status_code == 429 or resp.status_code >= 500:
                # rate limit یا خطای موقت سرور -> ارزش retry دارد
                last_exc = RuntimeError(f"HTTP_{resp.status_code}:{resp.text[:150]}")
                time.sleep(0.5 * (2 ** attempt))  # backoff نمایی: 0.5s, 1s, 2s
                continue
            if resp.status_code != 200:
                raise RuntimeError(f"HTTP_{resp.status_code}:{resp.text[:150]}")
            break
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(0.5 * (2 ** attempt))
    else:
        raise last_exc if last_exc else RuntimeError("KUCOIN_FETCH_FAILED_AFTER_RETRIES")

    payload = resp.json()
    raw = payload.get("data", [])
    if not raw:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    # KuCoin row: [time, open, close, high, low, volume, turnover] (newest first)
    df = pd.DataFrame(raw, columns=["time", "open", "close", "high", "low", "volume", "turnover"])
    df["ts"] = pd.to_datetime(df["time"].astype(float), unit="s", utc=True)
    df = df.set_index("ts")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df[["open", "high", "low", "close", "volume"]].sort_index()


def fetch_ohlcv(coin_id: str, timeframe: str, limit: int = 300) -> SourceResult:
    symbol = get_symbol(coin_id, "kucoin")
    if not symbol:
        return SourceResult(source_name="kucoin", ok=False, error="SYMBOL_NOT_MAPPED")
    kline_type = TYPE_MAP.get(timeframe)
    if not kline_type:
        return SourceResult(source_name="kucoin", ok=False, error="TIMEFRAME_NOT_SUPPORTED")

    interval_sec = INTERVAL_SECONDS[timeframe]
    now = int(time.time())
    end_at = now
    pages = []
    remaining = limit
    max_pages = 15

    try:
        for _ in range(max_pages):
            start_at = end_at - MAX_PER_CALL * interval_sec
            page = _fetch_page(symbol, kline_type, start_at=start_at, end_at=end_at)
            if page.empty:
                break
            pages.append(page)
            remaining -= len(page)
            if remaining <= 0:
                break
            oldest_ts = int(page.index[0].timestamp())
            new_end_at = oldest_ts - interval_sec
            if new_end_at >= end_at:
                break
            end_at = new_end_at
            time.sleep(0.2)
    except (requests.RequestException, RuntimeError) as exc:
        if not pages:
            return SourceResult(source_name="kucoin", ok=False, error=str(exc))

    if not pages:
        return SourceResult(source_name="kucoin", ok=False, error="EMPTY_RESPONSE")

    df = pd.concat(pages).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df = df.iloc[-limit:]

    return SourceResult(source_name="kucoin", ok=True, df=df, is_reconstructed=False)
