"""
RSP — ingestion/sources/base.py

هر منبع (Binance, KuCoin, Kraken, Coinbase, CoinGecko) باید یک تابع
fetch_ohlcv(coin_id, timeframe, limit) پیاده کند که یک SourceResult
برمی‌گرداند. این قرارداد مشترک است تا multi_source_router بتواند بدون
دانستن جزئیات هر صرافی، بین آن‌ها fallback کند.
"""

from dataclasses import dataclass, field
from typing import Optional
import pandas as pd


@dataclass
class SourceResult:
    source_name: str
    ok: bool
    df: pd.DataFrame = field(default_factory=pd.DataFrame)
    is_reconstructed: bool = False   # True فقط برای CoinGecko (بازسازی از سری قیمت)
    error: Optional[str] = None
