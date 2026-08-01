"""
RSP — Research & Strategy Playground
config/settings.py

تمام مقادیر قابل‌تنظیم موتور RSP در همین‌جا متمرکز هستند تا:
  1) هیچ عددی به‌صورت hardcoded وسط منطق پنهان نشود.
  2) هر تغییر وزن/آستانه ثبت و قابل ردیابی باشد (Phase 13 - Adaptive Weighting).

این فایل به هیچ فایلی از آرسان اصلی (analyzer/) وابسته نیست و آرسان اصلی هم
به این فایل وابسته نیست. کاملاً مستقل.
"""

from dataclasses import dataclass, field
from typing import Dict


# ---------------------------------------------------------------------------
# Timeframes مورد استفاده در Multi-Timeframe Brain (Phase 6)
# ---------------------------------------------------------------------------
TIMEFRAMES = ["1D", "4H", "1H", "15M"]

TIMEFRAME_ROLE = {
    "1D": "context",   # تایم‌فریم بالا -> زمینه‌ی کلی بازار
    "4H": "trend",     # تایم‌فریم میانی -> جهت روند
    "1H": "trend",      # کمکی برای تایید روند میانی
    "15M": "entry",    # تایم‌فریم پایین -> نقطه‌ی ورود
}

# منبع داده‌ی هر تایم‌فریم (صادقانه مستند شده - نگاه کن به ingestion/coingecko_client.py)
TIMEFRAME_SOURCE = {
    "1D": "coingecko_market_chart_90d_resampled",
    "4H": "coingecko_market_chart_90d_resampled",
    "1H": "coingecko_market_chart_1d_resampled",
    "15M": "coingecko_market_chart_1d_resampled",
}


# ---------------------------------------------------------------------------
# Data Universe (Phase 2) — REQUIRED vs OPTIONAL
# ---------------------------------------------------------------------------
REQUIRED_DATA_FIELDS = ["open", "high", "low", "close", "volume"]

OPTIONAL_DATA_FIELDS = [
    "trade_count",
    "market_dominance",
    "market_breadth",
    "correlation",
    "relative_strength",
    "funding_rate",
    "open_interest",
    "liquidation_data",
    "order_book",
]

# این‌ها با API رایگان CoinGecko اصلاً در دسترس نیستند - صادقانه علامت‌گذاری می‌شوند
PERMANENTLY_UNAVAILABLE_WITH_CURRENT_SOURCE = [
    "funding_rate",
    "open_interest",
    "liquidation_data",
    "order_book",
    "trade_count",
]


# ---------------------------------------------------------------------------
# Data Quality Engine (Phase 3)
# ---------------------------------------------------------------------------
MAX_ALLOWED_GAP_RATIO = 0.05          # بیش از ۵٪ کندل‌های گمشده => کیفیت پایین
MIN_BARS_REQUIRED = {
    "1D": 20,
    "4H": 30,
    "1H": 48,
    "15M": 48,
}
ABNORMAL_SPIKE_STD_MULTIPLIER = 6.0    # تغییر قیمت بیش از ۶ انحراف معیار => Spike مشکوک


# ---------------------------------------------------------------------------
# Regime Engine (Phase 4 / 5)
# ---------------------------------------------------------------------------
REGIME_LABELS = [
    "STRONG_UPTREND", "UPTREND", "WEAK_UPTREND",
    "RANGE",
    "WEAK_DOWNTREND", "DOWNTREND", "STRONG_DOWNTREND",
    "TRANSITION", "BREAKOUT", "FAKE_BREAKOUT", "BREAKDOWN",
    "RECOVERY", "CRASH",
    "HIGH_VOLATILITY", "LOW_VOLATILITY",
    "UNKNOWN",
]

# نگاشت رژیم -> استراتژی‌های سازگار (Regime-Aware Strategy Selection - Phase 5/15)
REGIME_STRATEGY_COMPATIBILITY: Dict[str, list] = {
    "STRONG_UPTREND": ["trend_following", "momentum"],
    "UPTREND": ["trend_following", "pullback"],
    "WEAK_UPTREND": ["pullback", "mean_reversion"],
    "RANGE": ["mean_reversion"],
    "WEAK_DOWNTREND": ["pullback", "mean_reversion"],
    "DOWNTREND": ["trend_following", "pullback"],
    "STRONG_DOWNTREND": ["trend_following", "momentum"],
    "TRANSITION": [],                       # عمداً خالی -> صبر کن
    "BREAKOUT": ["breakout"],
    "FAKE_BREAKOUT": [],                    # عمداً خالی -> هیچ استراتژی اعتماد نمی‌کند
    "BREAKDOWN": ["trend_following"],
    "RECOVERY": ["reversal", "mean_reversion"],
    "CRASH": [],                            # عمداً خالی -> NO TRADE
    "HIGH_VOLATILITY": [],                  # ریسک بالا -> نیاز به تایید بیشتر
    "LOW_VOLATILITY": ["mean_reversion"],
    "UNKNOWN": [],
}


# ---------------------------------------------------------------------------
# Adaptive Weighting (Phase 13)
# وزن دسته‌های شواهد در Signal Fusion، بسته به رژیم بازار تغییر می‌کند.
# مجموع هر ردیف باید ۱٫۰ باشد (تست می‌شود در tests).
# ---------------------------------------------------------------------------
@dataclass
class EvidenceWeights:
    trend: float
    momentum: float
    volume: float
    structure: float
    volatility: float
    mtf: float

    def as_dict(self):
        return {
            "trend": self.trend, "momentum": self.momentum, "volume": self.volume,
            "structure": self.structure, "volatility": self.volatility, "mtf": self.mtf,
        }


DEFAULT_WEIGHTS = EvidenceWeights(trend=0.25, momentum=0.20, volume=0.15,
                                   structure=0.20, volatility=0.10, mtf=0.10)

REGIME_WEIGHT_OVERRIDES: Dict[str, EvidenceWeights] = {
    "STRONG_UPTREND": EvidenceWeights(trend=0.35, momentum=0.20, volume=0.10, structure=0.15, volatility=0.05, mtf=0.15),
    "STRONG_DOWNTREND": EvidenceWeights(trend=0.35, momentum=0.20, volume=0.10, structure=0.15, volatility=0.05, mtf=0.15),
    "RANGE": EvidenceWeights(trend=0.10, momentum=0.15, volume=0.15, structure=0.35, volatility=0.15, mtf=0.10),
    "HIGH_VOLATILITY": EvidenceWeights(trend=0.15, momentum=0.15, volume=0.15, structure=0.15, volatility=0.30, mtf=0.10),
    "BREAKOUT": EvidenceWeights(trend=0.15, momentum=0.25, volume=0.30, structure=0.20, volatility=0.05, mtf=0.05),
}

def get_weights_for_regime(regime: str) -> EvidenceWeights:
    return REGIME_WEIGHT_OVERRIDES.get(regime, DEFAULT_WEIGHTS)


# ---------------------------------------------------------------------------
# Risk Engine (Phase 16)
# ---------------------------------------------------------------------------
ATR_PERIOD = 14
STOP_LOSS_ATR_MULTIPLIER = 1.5
TAKE_PROFIT_RR_TARGET = 2.0          # حداقل Risk/Reward قابل قبول
MAX_RISK_PERCENT_PER_TRADE = 1.0     # % از سرمایه‌ی فرضی
MIN_ACCEPTABLE_RISK_REWARD = 1.5


# ---------------------------------------------------------------------------
# Trade Quality / Confidence thresholds (Phase 12 / 17)
# ---------------------------------------------------------------------------
MIN_CONFIDENCE_TO_TRADE = 55.0        # زیر این عدد => WAIT
MIN_TRADE_QUALITY_SCORE = 60.0        # زیر این عدد => NO TRADE
CONTRADICTION_BLOCK_THRESHOLD = 0.45  # اگر نسبت شواهد متناقض بیش از این باشد => CONFLICT DETECTED


# ---------------------------------------------------------------------------
# Backtest / Simulator (Phase 18/19)
# ---------------------------------------------------------------------------
SIMULATED_FEE_PCT = 0.001      # 0.1% (نمونه‌ی معمول کارمزد اسپات)
SIMULATED_SLIPPAGE_PCT = 0.0005
CONSERVATIVE_SL_TP_SAME_CANDLE = "SL_FIRST"  # اگر SL و TP در یک کندل لمس شدند، فرض محافظه‌کارانه: SL زودتر خورده


# ---------------------------------------------------------------------------
# Execution restriction (طبق «محدودیت‌های اجرایی» در اسپک)
# ---------------------------------------------------------------------------
LIVE_TRADING_ENABLED = False   # همیشه False. این موتور هرگز نباید سفارش واقعی بفرستد.
REAL_TRADING_API_KEYS_ALLOWED = False
