"""
RSP — Research & Strategy Playground
config/settings.py v2.0 — Profitability Engineering Patch
"""

from dataclasses import dataclass, field
from typing import Dict
from contextlib import contextmanager as _contextmanager

# ---------------------------------------------------------------------------
# PROFITABILITY FIX v2.0
# ---------------------------------------------------------------------------

RR_TARGET = 2.5
SL_ATR_MULTIPLIER = 1.5
TP_ATR_MULTIPLIER = 3.75

REGIME_RR_TARGETS = {
    "STRONG_UPTREND": 3.0,
    "STRONG_DOWNTREND": 3.0,
    "UPTREND": 2.5,
    "DOWNTREND": 2.5,
    "WEAK_UPTREND": 2.0,
    "WEAK_DOWNTREND": 2.0,
    "RANGE": 1.5,
    "LOW_VOLATILITY": 2.0,
    "BREAKOUT": 2.5,
    "BREAKDOWN": 2.5,
    "RECOVERY": 2.0,
    "TRANSITION": 1.5,
    "HIGH_VOLATILITY": 1.5,
    "CRASH": 1.0,
    "FAKE_BREAKOUT": 1.0,
    "UNKNOWN": 1.0,
}

MAX_SL_DISTANCE_PCT = 0.05

MIN_OPPORTUNITY_SCORE_FOR_TRADE = 75.0
FUZZY_OPPORTUNITY_THRESHOLD = 75.0
FUZZY_OPPORTUNITY_THRESHOLD_BY_METHOD = {"rules": 75.0, "ahp": 75.0}
FUZZY_ADAPTIVE_OPPORTUNITY_PERCENTILE = 0.75

TRX_BLACKLIST = ["tron", "TRX", "tronix"]

CONSERVATIVE_SL_TP_SAME_CANDLE = "PROPORTIONAL"
SAME_CANDLE_CONSERVATIVE_BIAS = True

REGIME_RULE_OVERRIDES = {
    "STRONG_UPTREND": {"disable": ["R14", "R15", "R16"], "enable": ["R17", "R18"], "note": "Trend clean"},
    "STRONG_DOWNTREND": {"disable": ["R14", "R15", "R16"], "enable": ["R17", "R18"], "note": "Trend clean"},
    "RANGE": {"disable": ["R17", "R18"], "enable": ["R14", "R15", "R16"], "note": "Range only"},
    "UPTREND": {"disable": [], "enable": [], "note": "Mixed"},
    "DOWNTREND": {"disable": [], "enable": [], "note": "Mixed"},
}

MIN_TRADE_DISTANCE_BARS = 12
COOLDOWN_BARS_AFTER_STOP_LOSS = 6
COOLDOWN_BARS_AFTER_TAKE_PROFIT = 3
DAILY_MAX_TRADES = 5

STRONG_REGIME_ONLY_MODE = True
ALLOWED_REGIMES_FOR_TRADING = [
    "WEAK_DOWNTREND", "UPTREND", "LOW_VOLATILITY",
    "STRONG_DOWNTREND", "STRONG_UPTREND"
]

MIN_VOLUME_USD = 1000000
VOLUME_FILTER_ENABLED = True

TIMEFRAMES = ["1D", "4H", "1H", "15M"]
BARS_PER_DAY = {"15M": 96, "1H": 24, "4H": 6, "1D": 1}
DEFAULT_HISTORY_LIMIT = 300
MAX_HISTORY_DAYS = 120

def bars_needed_for_days(days: int) -> dict:
    days = max(1, min(days, MAX_HISTORY_DAYS))
    return {tf: days * BARS_PER_DAY[tf] for tf in TIMEFRAMES}

TIMEFRAME_ROLE = {"1D": "context", "4H": "trend", "1H": "trend", "15M": "entry"}
TIMEFRAME_SOURCE = {
    "1D": "coingecko_market_chart_90d_resampled",
    "4H": "coingecko_market_chart_90d_resampled",
    "1H": "coingecko_market_chart_1d_resampled",
    "15M": "coingecko_market_chart_1d_resampled",
}
TIMEFRAME_MINUTES = {"15M": 15, "1H": 60, "4H": 240, "1D": 1440}
DEFAULT_LOOKBACK_DAYS = 90

MAX_WARMUP_BARS = 400
RANGE_REGIME_NO_TRADE = True
EXHAUSTION_NET_SCORE_THRESHOLD = 0.70
EXHAUSTION_FILTER_ENABLED = True

FUZZY_ENGINE_ENABLED = True
FUZZY_BACKTEST_ENABLED = True

# NEW v2.2 — both default OFF: wiring in two previously-orphaned subsystems
# (RSP/meta_controller/meta_controller.py and RSP/exit_manager.py) that
# were fully built but never called from anywhere. Off by default so every
# already-reported backtest number is unchanged unless explicitly enabled.
META_CONTROLLER_ENABLED = False   # per-bar adaptive Rules/AHP blending by market context
TRAILING_STOP_ENABLED = False     # ATR-based trailing stop instead of fixed SL/TP
TRAILING_ACTIVATE_ATR = 1.0       # profit (in ATR multiples) before the trailing stop arms
TRAILING_ATR = 1.0                # trailing distance behind price, in ATR multiples
FUZZY_INFERENCE_METHOD = "Sugeno"
FUZZY_CONFLICT_METHOD = "conservative_weighted"
FUZZY_OPPORTUNITY_THRESHOLD = 75.0
FUZZY_ADAPTIVE_OPPORTUNITY_THRESHOLD = True
FUZZY_DECISION_HISTORY_LEN = 5
FUZZY_STABILITY_MIN_CONSISTENT = 3
FUZZY_HYSTERESIS_DROP = 25.0
FUZZY_SIGNAL_WEAK_END = 0.20
FUZZY_SIGNAL_MODERATE_CENTER = 0.375
FUZZY_SIGNAL_STRONG_CENTER = 0.55
FUZZY_SIGNAL_EXTREME_START = 0.70
FUZZY_TRADE_PERMISSION_MIN = 50.0

OPPORTUNITY_SCORING_METHOD = "ahp"

VOLATILITY_REGIME_PRIOR_WEIGHT = 0.35
USE_PERCENTILE_RISK_VOLATILITY = True
VOLATILITY_PERCENTILE_MIN_SAMPLES = 30
VOLATILITY_PERCENTILE_TARGET_SAMPLES = 300
RISK_QUALITY_PERCENTILE_MIN_SAMPLES = 30

CONTRADICTION_SCORING_MODE = "continuous"

def candles_needed(timeframe: str, days: float) -> int:
    minutes = TIMEFRAME_MINUTES[timeframe]
    return max(1, int((days * 24 * 60) / minutes))

REQUIRED_DATA_FIELDS = ["open", "high", "low", "close", "volume"]
OPTIONAL_DATA_FIELDS = [
    "trade_count", "market_dominance", "market_breadth", "correlation",
    "relative_strength", "funding_rate", "open_interest",
    "liquidation_data", "order_book",
]
PERMANENTLY_UNAVAILABLE_WITH_CURRENT_SOURCE = [
    "funding_rate", "open_interest", "liquidation_data", "order_book", "trade_count",
]

MAX_ALLOWED_GAP_RATIO = 0.05
MIN_BARS_REQUIRED = {"1D": 20, "4H": 30, "1H": 48, "15M": 48}
ABNORMAL_SPIKE_STD_MULTIPLIER = 6.0

REGIME_LABELS = [
    "STRONG_UPTREND", "UPTREND", "WEAK_UPTREND", "RANGE",
    "WEAK_DOWNTREND", "DOWNTREND", "STRONG_DOWNTREND",
    "TRANSITION", "BREAKOUT", "FAKE_BREAKOUT", "BREAKDOWN",
    "RECOVERY", "CRASH", "HIGH_VOLATILITY", "LOW_VOLATILITY", "UNKNOWN",
]

REGIME_STRATEGY_COMPATIBILITY = {
    "STRONG_UPTREND": ["trend_following", "momentum"],
    "UPTREND": ["trend_following", "pullback"],
    "WEAK_UPTREND": ["pullback", "mean_reversion"],
    "RANGE": ["mean_reversion"],
    "WEAK_DOWNTREND": ["pullback", "mean_reversion"],
    "DOWNTREND": ["trend_following", "pullback"],
    "STRONG_DOWNTREND": ["trend_following", "momentum"],
    "TRANSITION": [], "BREAKOUT": ["breakout"], "FAKE_BREAKOUT": [],
    "BREAKDOWN": ["trend_following"], "RECOVERY": ["reversal", "mean_reversion"],
    "CRASH": [], "HIGH_VOLATILITY": [], "LOW_VOLATILITY": ["mean_reversion"], "UNKNOWN": [],
}

@dataclass
class EvidenceWeights:
    trend: float; momentum: float; volume: float
    structure: float; volatility: float; mtf: float
    def as_dict(self):
        return {"trend": self.trend, "momentum": self.momentum, "volume": self.volume,
                "structure": self.structure, "volatility": self.volatility, "mtf": self.mtf}

DEFAULT_WEIGHTS = EvidenceWeights(trend=0.25, momentum=0.20, volume=0.15,
                                   structure=0.20, volatility=0.10, mtf=0.10)

REGIME_WEIGHT_OVERRIDES = {
    "STRONG_UPTREND": EvidenceWeights(trend=0.35, momentum=0.20, volume=0.10, structure=0.15, volatility=0.05, mtf=0.15),
    "STRONG_DOWNTREND": EvidenceWeights(trend=0.35, momentum=0.20, volume=0.10, structure=0.15, volatility=0.05, mtf=0.15),
    "RANGE": EvidenceWeights(trend=0.10, momentum=0.15, volume=0.15, structure=0.35, volatility=0.15, mtf=0.10),
    "HIGH_VOLATILITY": EvidenceWeights(trend=0.15, momentum=0.15, volume=0.15, structure=0.15, volatility=0.30, mtf=0.10),
    "BREAKOUT": EvidenceWeights(trend=0.15, momentum=0.25, volume=0.30, structure=0.20, volatility=0.05, mtf=0.05),
}

def get_weights_for_regime(regime: str) -> EvidenceWeights:
    return REGIME_WEIGHT_OVERRIDES.get(regime, DEFAULT_WEIGHTS)

ATR_PERIOD = 14
STOP_LOSS_ATR_MULTIPLIER = 2.5
TAKE_PROFIT_RR_TARGET = 2.0
MAX_RISK_PERCENT_PER_TRADE = 1.0
MIN_ACCEPTABLE_RISK_REWARD = 1.5

# FIX v2.1: mtf_brain.py's tf_trend() used to require 3 strictly monotonic
# consecutive closes to call a trend — on noisy 15M candles that's nearly
# always NEUTRAL, which meant MTF agreement almost never happened and the
# backtest produced ~0 trades regardless of market conditions (confirmed via
# RSP/diagnose_pipeline.py: 100% of rejections were CONFLICT DETECTED at the
# decision gate, not a risk/fuzzy/volume gate). Replaced with a fast/slow SMA
# cross + noise threshold, tunable here.
MTF_TREND_SMA_FAST = 10
MTF_TREND_SMA_SLOW = 20
MTF_TREND_THRESHOLD_PCT = 0.001  # 0.1% separation between fast/slow SMA to call UP/DOWN

MIN_CONFIDENCE_TO_TRADE = 55.0
MIN_TRADE_QUALITY_SCORE = 60.0
CONTRADICTION_BLOCK_THRESHOLD = 0.15
CONTRADICTION_SEVERE_THRESHOLD = 0.70

SIMULATED_FEE_PCT = 0.001
SIMULATED_SLIPPAGE_PCT = 0.0005

LIVE_TRADING_ENABLED = False
REAL_TRADING_API_KEYS_ALLOWED = False

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
