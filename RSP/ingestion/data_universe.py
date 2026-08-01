"""
RSP — ingestion/data_universe.py  (Phase 2: DATA UNIVERSE)

هر تایم‌فریم از طریق multi_source_router با زنجیره‌ی fallback رایگان
(Binance -> KuCoin -> Kraken -> Coinbase -> CoinGecko) گرفته می‌شود.
وضعیت در دسترس‌بودن هر نوع داده به‌صورت صریح گزارش می‌شود:
DATA_AVAILABLE / DATA_MISSING / DATA_QUALITY_UNKNOWN، به‌همراه اینکه
واقعاً از کدام منبع گرفته شده و آیا بازسازی‌شده بوده (source_used /
is_reconstructed) - برای شفافیت کامل در Explainability.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional
import pandas as pd

from RSP.config import settings
from RSP.ingestion.multi_source_router import fetch_all_timeframes

AVAILABLE = "DATA_AVAILABLE"
MISSING = "DATA_MISSING"
UNKNOWN = "DATA_QUALITY_UNKNOWN"


@dataclass
class DataUniverse:
    coin_id: str
    bars: Dict[str, pd.DataFrame] = field(default_factory=dict)         # timeframe -> OHLCV DataFrame
    availability: Dict[str, str] = field(default_factory=dict)          # field_name -> status
    source_used: Dict[str, Optional[str]] = field(default_factory=dict) # timeframe -> نام منبع استفاده‌شده
    is_reconstructed: Dict[str, bool] = field(default_factory=dict)     # timeframe -> آیا بازسازی‌شده بود
    attempted_sources: Dict[str, list] = field(default_factory=dict)    # timeframe -> لاگ تلاش‌های fallback


def build_data_universe(coin_id: str) -> DataUniverse:
    universe = DataUniverse(coin_id=coin_id)

    routed = fetch_all_timeframes(coin_id, settings.TIMEFRAMES, limit=300)

    for tf, routed_result in routed.items():
        universe.bars[tf] = routed_result.df
        universe.source_used[tf] = routed_result.source_used
        universe.is_reconstructed[tf] = routed_result.is_reconstructed
        universe.attempted_sources[tf] = routed_result.attempted

        min_needed = settings.MIN_BARS_REQUIRED[tf]
        if routed_result.df.empty:
            universe.availability[f"ohlcv_{tf}"] = MISSING
        elif len(routed_result.df) < min_needed:
            universe.availability[f"ohlcv_{tf}"] = UNKNOWN
        elif routed_result.is_reconstructed:
            universe.availability[f"ohlcv_{tf}"] = UNKNOWN
        else:
            universe.availability[f"ohlcv_{tf}"] = AVAILABLE

    for field_name in settings.OPTIONAL_DATA_FIELDS:
        universe.availability[field_name] = MISSING

    return universe
