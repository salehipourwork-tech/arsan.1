"""
RSP — ingestion/multi_source_router.py

برای هر تایم‌فریم، به‌ترتیب اولویت بین چند منبع رایگان fallback می‌کند.
ترتیب اولویت (همه رایگان/بدون کلید):

  1) Binance   -> کندل واقعی، همه‌ی تایم‌فریم‌ها، Pagination تا ۱۰۰۰/درخواست
  2) KuCoin    -> کندل واقعی، پوشش آلت‌کوین بهتر
  3) Kraken    -> کندل واقعی
  4) Coinbase  -> کندل واقعی (4H از تجمیع 1H واقعی)
  5) CoinGecko -> آخرین fallback؛ بازسازی‌شده از سری قیمت (صادقانه علامت‌گذاری می‌شود)

هر منبع خودش با Pagination داخلی تلاش می‌کند به تعداد کندل خواسته‌شده
(limit) برسد. نتیجه شامل این است که واقعاً کدام منبع استفاده شده
(source_used) و آیا داده بازسازی‌شده بوده (is_reconstructed).
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict
import pandas as pd

from RSP.config import settings
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
    best_partial = None  # اگر هیچ منبعی کامل نبود، بهترین نتیجه‌ی جزئی را نگه می‌داریم
    for source_module in SOURCE_PRIORITY:
        r = source_module.fetch_ohlcv(coin_id, timeframe, limit=limit)
        got = len(r.df) if r.ok else 0
        result.attempted.append(f"{r.source_name}:{'OK(' + str(got) + ')' if r.ok else 'FAIL(' + str(r.error) + ')'}")
        if r.ok and not r.df.empty:
            # اگر این منبع حداقل ۹۰٪ از تعداد درخواستی را داد، همین را قطعی می‌گیریم
            if got >= limit * 0.9:
                result.df = r.df
                result.source_used = r.source_name
                result.is_reconstructed = r.is_reconstructed
                return result
            # وگرنه به‌عنوان بهترین نتیجه‌ی جزئی تا الان نگه می‌داریم و ادامه می‌دهیم
            if best_partial is None or got > len(best_partial.df):
                best_partial = r
    if best_partial is not None:
        result.df = best_partial.df
        result.source_used = best_partial.source_name
        result.is_reconstructed = best_partial.is_reconstructed
        return result
    result.all_failed = True
    return result


def fetch_all_timeframes(coin_id: str, timeframes: List[str], limit: int = 300,
                          limits_per_tf: Optional[Dict[str, int]] = None) -> dict:
    """خروجی: {tf: RoutedResult}. اگر limits_per_tf داده شود (تعداد کندل
    مورد نیاز هر تایم‌فریم بر اساس lookback_days)، به‌جای `limit` یکسان
    برای همه، مقدار اختصاصی هر تایم‌فریم استفاده می‌شود."""
    limits_per_tf = limits_per_tf or {}
    return {tf: fetch_with_fallback(coin_id, tf, limit=limits_per_tf.get(tf, limit)) for tf in timeframes}
