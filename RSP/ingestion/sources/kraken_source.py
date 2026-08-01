"""
RSP — ingestion/sources/kraken_source.py

Kraken Public REST API — /0/public/OHLC — رایگان، بدون API Key.
مستندات: https://docs.kraken.com/rest/#tag/Market-Data/operation/getOHLCData

نکته: Kraken فاصله‌ی زمانی را به‌صورت دقیقه می‌گیرد و برای بعضی جفت‌ارزها
عمق تاریخی محدودی دارد (حداکثر ~720 کندل آخر) - برای RSP کافی‌ست.
"""

import requests
import pandas as pd

from RSP.ingestion.symbol_map import get_symbol
from RSP.ingestion.sources.base import SourceResult

BASE_URL = "https://api.kraken.com/0/public/OHLC"

INTERVAL_MINUTES = {"15M": 15, "1H": 60, "4H": 240, "1D": 1440}


def fetch_ohlcv(coin_id: str, timeframe: str, limit: int = 300) -> SourceResult:
    pair = get_symbol(coin_id, "kraken")
    if not pair:
        return SourceResult(source_name="kraken", ok=False, error="SYMBOL_NOT_MAPPED")
    interval = INTERVAL_MINUTES.get(timeframe)
    if not interval:
        return SourceResult(source_name="kraken", ok=False, error="TIMEFRAME_NOT_SUPPORTED")

    try:
        resp = requests.get(BASE_URL, params={"pair": pair, "interval": interval}, timeout=15)
    except requests.RequestException as exc:
        return SourceResult(source_name="kraken", ok=False, error=str(exc))

    if resp.status_code != 200:
        return SourceResult(source_name="kraken", ok=False, error=f"HTTP_{resp.status_code}:{resp.text[:150]}")

    payload = resp.json()
    if payload.get("error"):
        return SourceResult(source_name="kraken", ok=False, error=str(payload["error"]))

    result = payload.get("result", {})
    # کلید داده معمولاً همان pair (یا نسخه‌ی نرمالایز شده‌ی آن) است، نه "last"
    data_key = next((k for k in result.keys() if k != "last"), None)
    raw = result.get(data_key, []) if data_key else []
    if not raw:
        return SourceResult(source_name="kraken", ok=False, error="EMPTY_RESPONSE")

    # Kraken row: [time, open, high, low, close, vwap, volume, count]
    df = pd.DataFrame(raw, columns=["time", "open", "high", "low", "close", "vwap", "volume", "count"])
    df["ts"] = pd.to_datetime(df["time"].astype(float), unit="s", utc=True)
    df = df.set_index("ts")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df = df[["open", "high", "low", "close", "volume"]].sort_index()
    df = df.iloc[-limit:]

    return SourceResult(source_name="kraken", ok=True, df=df, is_reconstructed=False)
