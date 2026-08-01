"""
RSP — ingestion/sources/binance_source.py

Binance Public REST API — /api/v3/klines — رایگان، بدون نیاز به API Key
برای داده‌ی عمومی بازار. کندل‌های واقعی صرافی (نه بازسازی‌شده).
مستندات: https://binance-docs.github.io/apidocs/spot/en/#kline-candlestick-data
"""

import requests
import pandas as pd

from RSP.ingestion.symbol_map import get_symbol
from RSP.ingestion.sources.base import SourceResult

BASE_URL = "https://api.binance.com/api/v3/klines"

INTERVAL_MAP = {"15M": "15m", "1H": "1h", "4H": "4h", "1D": "1d"}

COLUMNS = ["open_time", "open", "high", "low", "close", "volume",
           "close_time", "quote_asset_volume", "n_trades",
           "taker_buy_base", "taker_buy_quote", "ignore"]


def fetch_ohlcv(coin_id: str, timeframe: str, limit: int = 300) -> SourceResult:
    symbol = get_symbol(coin_id, "binance")
    if not symbol:
        return SourceResult(source_name="binance", ok=False, error="SYMBOL_NOT_MAPPED")
    interval = INTERVAL_MAP.get(timeframe)
    if not interval:
        return SourceResult(source_name="binance", ok=False, error="TIMEFRAME_NOT_SUPPORTED")

    try:
        resp = requests.get(BASE_URL, params={"symbol": symbol, "interval": interval, "limit": limit}, timeout=15)
    except requests.RequestException as exc:
        return SourceResult(source_name="binance", ok=False, error=str(exc))

    if resp.status_code != 200:
        return SourceResult(source_name="binance", ok=False, error=f"HTTP_{resp.status_code}:{resp.text[:150]}")

    raw = resp.json()
    if not raw or not isinstance(raw, list):
        return SourceResult(source_name="binance", ok=False, error="EMPTY_RESPONSE")

    df = pd.DataFrame(raw, columns=COLUMNS)
    df["ts"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df = df.set_index("ts")
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    df = df[["open", "high", "low", "close", "volume"]].sort_index()

    return SourceResult(source_name="binance", ok=True, df=df, is_reconstructed=False)
