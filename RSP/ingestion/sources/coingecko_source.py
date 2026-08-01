"""
RSP — ingestion/sources/coingecko_source.py

آخرین fallback در زنجیره‌ی چند-منبعی. برخلاف بقیه‌ی منابع، این یکی کندل
واقعی صرافی نمی‌دهد؛ از سری قیمت CoinGecko با resample کندل می‌سازد
(is_reconstructed=True) - دقیقاً همان منطقی که در data_universe.py اولیه
پیاده‌سازی شده بود، اینجا فقط در قالب SourceResult یکسان با بقیه‌ی منابع
بسته‌بندی شده تا router بتواند یکسان با آن رفتار کند.
"""

import pandas as pd

from RSP.ingestion.coingecko_client import fetch_fine_and_coarse
from RSP.ingestion.sources.base import SourceResult

_RESAMPLE_RULE = {"15M": "15min", "1H": "1h", "4H": "4h", "1D": "1D"}

# نگاشت coin_id به همان coin_id (CoinGecko از coin_id استفاده می‌کند، نه نماد صرافی)
COINGECKO_SUPPORTED = {
    "bitcoin", "ethereum", "binancecoin", "ripple", "solana",
    "dogecoin", "cardano", "tron",
}


def _series_to_df(prices, volumes):
    if not prices:
        return pd.DataFrame(columns=["price", "volume"])
    p = pd.DataFrame(prices, columns=["ts", "price"])
    p["ts"] = pd.to_datetime(p["ts"], unit="ms", utc=True)
    p = p.set_index("ts")
    if volumes:
        v = pd.DataFrame(volumes, columns=["ts", "volume"])
        v["ts"] = pd.to_datetime(v["ts"], unit="ms", utc=True)
        v = v.set_index("ts")
        df = p.join(v, how="outer")
    else:
        df = p
        df["volume"] = float("nan")
    return df.sort_index()


def _resample_to_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
    ohlc = df["price"].resample(rule).ohlc()
    vol = df["volume"].resample(rule).sum(min_count=1)
    out = ohlc.join(vol).dropna(subset=["open", "high", "low", "close"])
    return out


def fetch_ohlcv(coin_id: str, timeframe: str, limit: int = 300) -> SourceResult:
    if coin_id not in COINGECKO_SUPPORTED:
        return SourceResult(source_name="coingecko", ok=False, error="COIN_NOT_MAPPED")

    raw = fetch_fine_and_coarse(coin_id)
    if timeframe in ("15M", "1H"):
        source_df = _series_to_df(raw["fine"].get("prices", []), raw["fine"].get("volumes", []))
        err = raw["fine"].get("error")
    else:
        source_df = _series_to_df(raw["coarse"].get("prices", []), raw["coarse"].get("volumes", []))
        err = raw["coarse"].get("error")

    if err and source_df.empty:
        return SourceResult(source_name="coingecko", ok=False, error=err)

    rule = _RESAMPLE_RULE.get(timeframe)
    if not rule:
        return SourceResult(source_name="coingecko", ok=False, error="TIMEFRAME_NOT_SUPPORTED")

    df = _resample_to_ohlcv(source_df, rule)
    if df.empty:
        return SourceResult(source_name="coingecko", ok=False, error="EMPTY_AFTER_RESAMPLE")

    df = df.iloc[-limit:]
    return SourceResult(source_name="coingecko", ok=True, df=df, is_reconstructed=True)
