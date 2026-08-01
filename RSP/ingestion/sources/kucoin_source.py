"""
RSP — ingestion/sources/kucoin_source.py

KuCoin Public REST API — /api/v1/market/candles — رایگان، بدون API Key.
پوشش خوبی برای آلت‌کوین‌ها دارد (fallback خوب برای وقتی Binance در دسترس
جغرافیایی نیست یا rate-limit خورده).
مستندات: https://docs.kucoin.com/#get-klines
"""

import requests
import pandas as pd

from RSP.ingestion.symbol_map import get_symbol
from RSP.ingestion.sources.base import SourceResult

BASE_URL = "https://api.kucoin.com/api/v1/market/candles"

TYPE_MAP = {"15M": "15min", "1H": "1hour", "4H": "4hour", "1D": "1day"}


def fetch_ohlcv(coin_id: str, timeframe: str, limit: int = 300) -> SourceResult:
    symbol = get_symbol(coin_id, "kucoin")
    if not symbol:
        return SourceResult(source_name="kucoin", ok=False, error="SYMBOL_NOT_MAPPED")
    kline_type = TYPE_MAP.get(timeframe)
    if not kline_type:
        return SourceResult(source_name="kucoin", ok=False, error="TIMEFRAME_NOT_SUPPORTED")

    try:
        resp = requests.get(BASE_URL, params={"symbol": symbol, "type": kline_type}, timeout=15)
    except requests.RequestException as exc:
        return SourceResult(source_name="kucoin", ok=False, error=str(exc))

    if resp.status_code != 200:
        return SourceResult(source_name="kucoin", ok=False, error=f"HTTP_{resp.status_code}:{resp.text[:150]}")

    payload = resp.json()
    raw = payload.get("data", [])
    if not raw:
        return SourceResult(source_name="kucoin", ok=False, error="EMPTY_RESPONSE")

    # KuCoin format per row: [time, open, close, high, low, volume, turnover] (newest first)
    df = pd.DataFrame(raw, columns=["time", "open", "close", "high", "low", "volume", "turnover"])
    df["ts"] = pd.to_datetime(df["time"].astype(float), unit="s", utc=True)
    df = df.set_index("ts")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df = df[["open", "high", "low", "close", "volume"]].sort_index()
    df = df.iloc[-limit:]

    return SourceResult(source_name="kucoin", ok=True, df=df, is_reconstructed=False)
