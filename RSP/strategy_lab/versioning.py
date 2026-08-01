"""
RSP — strategy_lab/versioning.py  (Phase 27: VERSIONED STRATEGY LAB)

نسخه‌های مختلف موتور RSP را به‌صورت مستقل نگه می‌دارد و امکان مقایسه و
بازگشت می‌دهد. چون موتور rule-based است (نه ML با فایل وزن جداگانه)،
«نسخه» در این پیاده‌سازی یعنی یک بسته‌ی مشخص از Override روی تنظیمات
تصمیم‌گیری (آستانه‌ها، ضرایب ریسک، وزن‌های Fusion) - هر نسخه با
`config.settings.temporary_override` به‌صورت موقت اعمال و بعد از اجرا
دقیقاً به حالت قبل برمی‌گردد؛ یعنی «قابل بازگشت» طبق اسپک تضمین‌شده است.

هر نسخه یک شرح دارد تا معلوم باشد چه تفاوت مفهومی با نسخه‌ی قبل دارد -
نه فقط عدد خام.
"""

from dataclasses import dataclass, field
from typing import Dict, Optional

from RSP.config import settings
from RSP.backtest_engine.backtest_engine import BacktestSummary, run_backtest


@dataclass
class EngineVersion:
    version_id: str
    description: str
    overrides: Dict[str, float] = field(default_factory=dict)


ENGINE_VERSIONS: Dict[str, EngineVersion] = {
    "V1": EngineVersion(
        version_id="V1",
        description="نسخه‌ی پایه (Baseline) - همان تنظیمات پیش‌فرض config/settings.py",
        overrides={},
    ),
    "V2": EngineVersion(
        version_id="V2",
        description="محافظه‌کارتر: آستانه‌ی Confidence و Trade Quality بالاتر، "
                     "Risk/Reward حداقل بیشتر - فرضیه: معاملات کمتر ولی با کیفیت بالاتر",
        overrides={
            "MIN_CONFIDENCE_TO_TRADE": 65.0,
            "MIN_TRADE_QUALITY_SCORE": 70.0,
            "MIN_ACCEPTABLE_RISK_REWARD": 2.0,
        },
    ),
    "V3": EngineVersion(
        version_id="V3",
        description="تهاجمی‌تر روی مومنتوم: آستانه‌ی تضاد سخت‌گیرتر (کمتر WAIT می‌دهد) "
                     "و Stop Loss تنگ‌تر - فرضیه: ورود سریع‌تر با ریسک کوچک‌تر",
        overrides={
            "CONTRADICTION_BLOCK_THRESHOLD": 0.6,
            "STOP_LOSS_ATR_MULTIPLIER": 1.1,
            "MIN_CONFIDENCE_TO_TRADE": 50.0,
        },
    ),
}


@dataclass
class VersionRunResult:
    version_id: str
    description: str
    summary: BacktestSummary


def register_version(version_id: str, description: str, overrides: Dict[str, float]) -> None:
    """امکان اضافه‌کردن نسخه‌ی جدید بدون دست‌زدن به نسخه‌های قبلی."""
    ENGINE_VERSIONS[version_id] = EngineVersion(version_id, description, overrides)


def run_version(version_id: str, bars_by_tf, base_tf: str = "15M", min_history: int = 60) -> VersionRunResult:
    version = ENGINE_VERSIONS[version_id]
    with settings.temporary_override(version.overrides):
        summary = run_backtest(bars_by_tf, base_tf=base_tf, min_history=min_history)
    return VersionRunResult(version_id=version.version_id, description=version.description, summary=summary)


def compare_versions(version_ids, bars_by_tf, base_tf: str = "15M", min_history: int = 60):
    return {vid: run_version(vid, bars_by_tf, base_tf=base_tf, min_history=min_history) for vid in version_ids}
