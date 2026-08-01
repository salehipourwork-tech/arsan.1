"""
RSP — ingestion/multi_source_router.py

هسته‌ی درخواست شما: برای هر تایم‌فریم، به‌ترتیب اولویت بین چند منبع رایگان
fallback می‌کند. ترتیب اولویت (همه رایگان/بدون کلید):

  1) Binance   -> کندل واقعی، همه‌ی تایم‌فریم‌ها
  2) KuCoin    -> کندل واقعی، پوشش آلت‌کوین بهتر
  3) Kraken    -> کندل واقعی
  4) Coinbase  -> کندل واقعی (4H از تجمیع 1H واقعی)
  5) CoinGecko -> آخرین fallback؛ بازسازی‌شده از سری قیمت (صادقانه علامت‌گذاری می‌شود)

نتیجه شامل این است که واقعاً کدام منبع استفاده شده (source_used) و آیا
داده بازسازی‌شده بوده (is_reconstructed) - برای Explainability و Data
Quality Engine حیاتی است.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import pandas as pd

from RSP.ingestion.sources import binance_source, kucoin_source, kraken_source, coinbase_source, coingecko_source

SOURCE_PRIORITY = [binance_source, kucoin_source, kraken_source, coinbase_source, coingecko_source]


@dataclass
class RoutedResult:
    timeframe: str
    df: pd.DataFrame = field(default_factory=pd.DataFrame)
    source_used: Optional[str] = None
    is_reconstructed: bool = False
    attempted: List[str] = field(default_factory=list)
    all_failed: bool = False


def fetch_with_fallback(coin_id: str, timeframe: str, limit: int = 300) -> RoutedResult:
    result = RoutedResult(timeframe=timeframe)
    for source_module in SOURCE_PRIORITY:
        r = source_module.fetch_ohlcv(coin_id, timeframe, limit=limit)
        result.attempted.append(f"{r.source_name}:{'OK' if r.ok else 'FAIL(' + str(r.error) + ')'}")
        if r.ok and not r.df.empty:
            result.df = r.df
            result.source_used = r.source_name
            result.is_reconstructed = r.is_reconstructed
            return result
    result.all_failed = True
    return result


def fetch_all_timeframes(coin_id: str, timeframes: List[str], limit: int = 300) -> dict:
    """خروجی: {tf: RoutedResult}"""
    return {tf: fetch_with_fallback(coin_id, tf, limit=limit) for tf in timeframes}
