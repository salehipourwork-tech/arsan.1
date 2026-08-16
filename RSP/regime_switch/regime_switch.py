#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP Regime Switch v1.0
Every indicator only active in its "home" regime.
"""

from RSP.market_regime.regime_engine import detect_regime

REGIME_INDICATOR_MAP = {
    "STRONG_UPTREND":   ["EMA_CROSS_20_50"],
    "UPTREND":          ["EMA_CROSS_20_50", "MACD_HIST"],
    "RANGE":            ["RSI_MR_30_70", "BB_MR"],
    "DOWNTREND":        ["BB_MR", "RSI_MR_30_70"],
    "STRONG_DOWNTREND": ["BB_MR"],
    "HIGH_VOLATILITY":  [],
}

REGIME_BASE_CONFIDENCE = {
    "STRONG_UPTREND":   0.85,
    "UPTREND":          0.75,
    "RANGE":            0.45,
    "DOWNTREND":        0.55,
    "STRONG_DOWNTREND": 0.60,
    "HIGH_VOLATILITY":  0.0,
}

def get_allowed_indicators(regime):
    return REGIME_INDICATOR_MAP.get(regime, [])

def filter_signals_by_regime(raw_signals, regime):
    allowed = set(get_allowed_indicators(regime))
    filtered = {}
    for ind, sig in raw_signals.items():
        if ind in allowed and sig is not None:
            filtered[ind] = sig
    return filtered

def is_trade_allowed(regime, signal_count):
    if regime == "HIGH_VOLATILITY":
        return False, "High volatility — no trade"
    if regime == "RANGE" and signal_count < 3:
        return False, f"RANGE with only {signal_count} agreements — need >=3"
    return True, "OK"

def get_regime_weights(regime):
    allowed = get_allowed_indicators(regime)
    if not allowed:
        return {}
    w = 1.0 / len(allowed)
    return {ind: round(w, 3) for ind in allowed}
