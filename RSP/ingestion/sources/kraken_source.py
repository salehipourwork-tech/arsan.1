"""
RSP — ingestion/sources/kraken_source.py

Kraken Public REST API — /0/public/OHLC — رایگان، بدون API Key.
مستندات: https://docs.kraken.com/rest/#tag/Market-Data/operation/getOHLCData

Kraken هر درخواست را حداکثر تا ~۷۲۰ کندل برمی‌گرداند و به‌جای بازه (start/end)
فقط `since` (نقطه‌ی شروع) می‌گیرد و از آنجا رو به جلو می‌دهد. برای پوشش
بازه‌ی طولانی، از قدیمی‌ترین `since` ممکن (بر اساس تعداد کندل خواسته‌شده)
شروع می‌کنیم و رو به جلو صفحه‌بندی می‌کنیم.
"""

import time
import requests
import pandas as pd

from RSP.ingestion.symbol_map import get_symbol
from RSP.ingestion.sources.base import SourceResult

BASE_URL = "https://api.kraken.com/0/public/OHLC"

INTERVAL_MINUTES = {"15M": 15, "1H": 60, "4H": 240, "1D": 1440}
MAX_PER_CALL = 720


def _fetch_page(pair, interval_min, since=None):
    params = {"pair": pair, "interval": interval_min}
    if since is not None:
        params["since"] = since
    resp = requests.get(BASE_URL, params=params, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"HTTP_{resp.status_code}:{resp.text[:150]}")
    payload = resp.json()
    if payload.get("error"):
        raise RuntimeError(str(payload["error"]))
    result = payload.get("result", {})
    data_key = next((k for k in result.keys() if k != "last"), None)
    raw = result.get(data_key, []) if data_key else []
    last_cursor = result.get("last")
    if not raw:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"]), last_cursor
    df = pd.DataFrame(raw, columns=["time", "open", "high", "low", "close", "vwap", "volume", "count"])
    df["ts"] = pd.to_datetime(df["time"].astype(float), unit="s", utc=True)
    df = df.set_index("ts")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df[["open", "high", "low", "close", "volume"]].sort_index(), last_cursor


def fetch_ohlcv(coin_id: str, timeframe: str, limit: int = 300) -> SourceResult:
    pair = get_symbol(coin_id, "kraken")
    if not pair:
        return SourceResult(source_name="kraken", ok=False, error="SYMBOL_NOT_MAPPED")
    interval_min = INTERVAL_MINUTES.get(timeframe)
    if not interval_min:
        return SourceResult(source_name="kraken", ok=False, error="TIMEFRAME_NOT_SUPPORTED")

    interval_sec = interval_min * 60
    n_pages_needed = max(1, -(-limit // MAX_PER_CALL))  # ceil division
    now = int(time.time())
    since = now - (n_pages_needed * MAX_PER_CALL * interval_sec)

    pages = []
    remaining = limit
    max_pages = 20

    try:
        for _ in range(max_pages):
            page, last_cursor = _fetch_page(pair, interval_min, since=since)
            if page.empty:
                break
            pages.append(page)
            remaining -= len(page)
            if remaining <= 0:
                break
            if last_cursor is None:
                break
            new_since = int(float(last_cursor))
            if new_since <= since:
                break
            since = new_since
            time.sleep(0.3)  # Kraken نسبت به rate limit حساس‌تر است
    except (requests.RequestException, RuntimeError) as exc:
        if not pages:
            return SourceResult(source_name="kraken", ok=False, error=str(exc))

    if not pages:
        return SourceResult(source_name="kraken", ok=False, error="EMPTY_RESPONSE")

    df = pd.concat(pages).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    df = df.iloc[-limit:]

    return SourceResult(source_name="kraken", ok=True, df=df, is_reconstructed=False)
