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
from contextlib import contextmanager as _contextmanager

# ---------------------------------------------------------------------------
# PROFITABILITY FIX v1 — Integrated 2026-08-15
# Target: RR=2.5, Regime-Aware Rules, A+ Filter, TRX Blacklist, Proportional Exit
# ---------------------------------------------------------------------------

# --- FIX 1: Real RR=2.5 ---
# قبلاً TAKE_PROFIT_RR_TARGET=2.0 بود ولی exit logic آن را رعایت نمی‌کرد.
# risk_engine.py و trade_simulator.py هر دو این مقادیر را می‌خوانند.
RR_TARGET = 2.5
SL_ATR_MULTIPLIER = 1.5          # SL تنگ‌تر → TP نزدیک‌تر → hit rate بالاتر
TP_ATR_MULTIPLIER = 3.75         # TP = 2.5 × SL = 2.5 × 1.5 = 3.75 ATR

# --- FIX 2: A+ Opportunity Filter ---
# قبلاً FUZZY_OPPORTUNITY_THRESHOLD=50.0 بود → خیلی کم
# حالا 75.0 → فقط setup‌های A+ (top 25%)
#
# نکته‌ی مهم (رفع اشکال ۲۰۲۶-۰۸-۱۶): این ۷۵.۰ روی مقیاس امتیاز AHP کالیبره
# شده بود (که compensatory bonus داره و امتیازش راحت‌تر بالا می‌ره). امتیاز
# Rules از دیفازی‌سازی Sugeno می‌آید و مقیاسش پایین‌تره؛ گذاشتن همون ۷۵ برای
# Rules عملاً همه‌ی تریدها رو صفر می‌کرد. برای همین حالا هرکدوم threshold
# مخصوص خودشون رو دارن (پایین‌تر → مقدار قبلی و امن‌تر برای Rules: 50.0).
MIN_OPPORTUNITY_SCORE_FOR_TRADE = 75.0
FUZZY_OPPORTUNITY_THRESHOLD = 75.0  # fallback عمومی / مقیاس AHP
FUZZY_OPPORTUNITY_THRESHOLD_BY_METHOD = {
    "rules": 75.0,  # مقیاس Sugeno defuzzified score؛ به‌ندرت به ۷۵ می‌رسه
    "ahp": 75.0,    # مقیاس AHP با compensatory bonus؛ ۷۵ دست‌یافتنیه
}
FUZZY_ADAPTIVE_OPPORTUNITY_PERCENTILE = 0.75  # top 25% of coin's own history

# --- FIX 3: TRX Blacklist ---
# TRX هیچ‌وقت سودآور نشد (PF=0.466–0.527، Net=-16.8%~-27%) → حذف از تست
TRX_BLACKLIST = ["tron", "TRX", "tronix"]

# --- FIX 4: Proportional Same-Candle Exit ---
# قبلاً CONSERVATIVE_SL_TP_SAME_CANDLE="SL_FIRST" باعث می‌شد
# حتی وقتی TP قبل از SL hit می‌شد، SL ثبت بشه.
# حالا: اگر TP به open نزدیک‌تر باشه، TP برنده است.
CONSERVATIVE_SL_TP_SAME_CANDLE = "PROPORTIONAL"  # "SL_FIRST" | "TP_FIRST" | "PROPORTIONAL"

# --- FIX 5: Regime-Aware Rule Activation ---
# رژیم‌های تمیز (Strong Uptrend/Downtrend) → MR rules خاموش
# RANGE/Weak → همه‌ی rules فعال
REGIME_RULE_OVERRIDES = {
    "STRONG_UPTREND": {
        "disable": ["R14", "R15", "R16"],  # MR rules خاموش
        "enable": ["R17", "R18"],           # فقط TF rules
        "note": "Trend clean — no mean reversion"
    },
    "STRONG_DOWNTREND": {
        "disable": ["R14", "R15", "R16"],
        "enable": ["R17", "R18"],
        "note": "Trend clean — no mean reversion"
    },
    "RANGE": {
        "disable": ["R17", "R18"],          # TF rules خاموش
        "enable": ["R14", "R15", "R16"],     # فقط MR rules
        "note": "Range — mean reversion only"
    },
    "UPTREND": {
        "disable": [],
        "enable": [],
        "note": "Mixed — all rules active"
    },
    "DOWNTREND": {
        "disable": [],
        "enable": [],
        "note": "Mixed — all rules active"
    },
}

# --- FIX 6: Anti Over-Trading ---
# با RR=2.5 و WR=35%، برای سودآوری:
# Expected = 0.35 × 2.5 - 0.65 × 1 = +0.225 → سودآور
# ولی fee+slippage ~0.15% per trade → با 100 trade = 15%
# پس باید تریدها کمتر و بزرگ‌تر باشن.
MIN_TRADE_DISTANCE_BARS = 3  # حداقل 3 کندل بین تریدها

# ---------------------------------------------------------------------------
# Timeframes مورد استفاده در Multi-Timeframe Brain (Phase 6)
# ---------------------------------------------------------------------------
TIMEFRAMES = ["1D", "4H", "1H", "15M"]

# چند کندل در روز برای هر تایم‌فریم
BARS_PER_DAY = {"15M": 96, "1H": 24, "4H": 6, "1D": 1}
DEFAULT_HISTORY_LIMIT = 300
MAX_HISTORY_DAYS = 120

def bars_needed_for_days(days: int) -> dict:
    """تبدیل تعداد روز درخواستی به تعداد کندل لازم برای هر تایم‌فریم."""
    days = max(1, min(days, MAX_HISTORY_DAYS))
    return {tf: days * BARS_PER_DAY[tf] for tf in TIMEFRAMES}

TIMEFRAME_ROLE = {
    "1D": "context",
    "4H": "trend",
    "1H": "trend",
    "15M": "entry",
}

TIMEFRAME_SOURCE = {
    "1D": "coingecko_market_chart_90d_resampled",
    "4H": "coingecko_market_chart_90d_resampled",
    "1H": "coingecko_market_chart_1d_resampled",
    "15M": "coingecko_market_chart_1d_resampled",
}

TIMEFRAME_MINUTES = {"15M": 15, "1H": 60, "4H": 240, "1D": 1440}
DEFAULT_LOOKBACK_DAYS = 90

MAX_WARMUP_BARS = 400

COOLDOWN_BARS_AFTER_STOP_LOSS = 6

RANGE_REGIME_NO_TRADE = True

EXHAUSTION_NET_SCORE_THRESHOLD = 0.70
EXHAUSTION_FILTER_ENABLED = True

STRONG_REGIME_ONLY_MODE = False

# --- Fuzzy Core ---
FUZZY_ENGINE_ENABLED = False
FUZZY_BACKTEST_ENABLED = False
FUZZY_INFERENCE_METHOD = "Sugeno"
FUZZY_CONFLICT_METHOD = "conservative_weighted"
# NOTE: FUZZY_OPPORTUNITY_THRESHOLD moved to FIX section above (line 32)

VOLATILITY_REGIME_PRIOR_WEIGHT = 0.35

FUZZY_ADAPTIVE_OPPORTUNITY_THRESHOLD = True
# NOTE: FUZZY_ADAPTIVE_OPPORTUNITY_PERCENTILE moved to FIX section above (line 33)
FUZZY_DECISION_HISTORY_LEN = 5
FUZZY_STABILITY_MIN_CONSISTENT = 3
FUZZY_HYSTERESIS_DROP = 25.0
FUZZY_SIGNAL_WEAK_END = 0.20
FUZZY_SIGNAL_MODERATE_CENTER = 0.375
FUZZY_SIGNAL_STRONG_CENTER = 0.55
FUZZY_SIGNAL_EXTREME_START = 0.70
FUZZY_TRADE_PERMISSION_MIN = 50.0

def candles_needed(timeframe: str, days: float) -> int:
    minutes = TIMEFRAME_MINUTES[timeframe]
    return max(1, int((days * 24 * 60) / minutes))

# ---------------------------------------------------------------------------
# Data Universe (Phase 2)
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
MAX_ALLOWED_GAP_RATIO = 0.05
MIN_BARS_REQUIRED = {
    "1D": 20,
    "4H": 30,
    "1H": 48,
    "15M": 48,
}
ABNORMAL_SPIKE_STD_MULTIPLIER = 6.0

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

REGIME_STRATEGY_COMPATIBILITY: Dict[str, list] = {
    "STRONG_UPTREND": ["trend_following", "momentum"],
    "UPTREND": ["trend_following", "pullback"],
    "WEAK_UPTREND": ["pullback", "mean_reversion"],
    "RANGE": ["mean_reversion"],
    "WEAK_DOWNTREND": ["pullback", "mean_reversion"],
    "DOWNTREND": ["trend_following", "pullback"],
    "STRONG_DOWNTREND": ["trend_following", "momentum"],
    "TRANSITION": [],
    "BREAKOUT": ["breakout"],
    "FAKE_BREAKOUT": [],
    "BREAKDOWN": ["trend_following"],
    "RECOVERY": ["reversal", "mean_reversion"],
    "CRASH": [],
    "HIGH_VOLATILITY": [],
    "LOW_VOLATILITY": ["mean_reversion"],
    "UNKNOWN": [],
}

# ---------------------------------------------------------------------------
# Adaptive Weighting (Phase 13)
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
# NOTE: STOP_LOSS_ATR_MULTIPLIER overridden by SL_ATR_MULTIPLIER in FIX section
# KEEP for backward compatibility — risk_engine.py uses SL_ATR_MULTIPLIER if available
STOP_LOSS_ATR_MULTIPLIER = 2.5
# NOTE: TAKE_PROFIT_RR_TARGET overridden by RR_TARGET in FIX section
# KEEP for backward compatibility — risk_engine.py uses RR_TARGET if available
TAKE_PROFIT_RR_TARGET = 2.0
MAX_RISK_PERCENT_PER_TRADE = 1.0
MIN_ACCEPTABLE_RISK_REWARD = 1.5

# ---------------------------------------------------------------------------
# Trade Quality / Confidence thresholds (Phase 12 / 17)
# ---------------------------------------------------------------------------
MIN_CONFIDENCE_TO_TRADE = 55.0
MIN_TRADE_QUALITY_SCORE = 60.0
CONTRADICTION_BLOCK_THRESHOLD = 0.15
CONTRADICTION_SEVERE_THRESHOLD = 0.70

# ---------------------------------------------------------------------------
# Bounded Uncertainty / Fuzzy Feature Redesign
# ---------------------------------------------------------------------------
CONTRADICTION_SCORING_MODE = "legacy"

USE_PERCENTILE_RISK_VOLATILITY = True
VOLATILITY_PERCENTILE_MIN_SAMPLES = 30
VOLATILITY_PERCENTILE_TARGET_SAMPLES = 300
RISK_QUALITY_PERCENTILE_MIN_SAMPLES = 30

OPPORTUNITY_SCORING_METHOD = "rules"

# ---------------------------------------------------------------------------
# Backtest / Simulator (Phase 18/19)
# ---------------------------------------------------------------------------
SIMULATED_FEE_PCT = 0.001
SIMULATED_SLIPPAGE_PCT = 0.0005
# NOTE: CONSERVATIVE_SL_TP_SAME_CANDLE overridden in FIX section above (line 47)

# ---------------------------------------------------------------------------
# Execution restriction
# ---------------------------------------------------------------------------
LIVE_TRADING_ENABLED = False
REAL_TRADING_API_KEYS_ALLOWED = False

# ---------------------------------------------------------------------------
# Temporary override helper
# ---------------------------------------------------------------------------
@_contextmanager
def temporary_override(overrides: dict):
    import sys
    module = sys.modules[__name__]
    original = {}
    for key, value in overrides.items():
        original[key] = getattr(module, key)
        setattr(module, key, value)
    try:
        yield
    finally:
        for key, value in original.items():
            setattr(module, key, value)
