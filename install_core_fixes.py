import os

FILES = {
    "RSP/regime_switch/__init__.py": "",
    "RSP/regime_switch/regime_switch.py": r'''#!/usr/bin/env python3
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
''',

    "RSP/signal_engine/__init__.py": "",
    "RSP/signal_engine/confluence.py": r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP Signal Engine — Confluence Detector v2.0
"""

from RSP.market_regime.regime_engine import detect_regime
from RSP.regime_switch.regime_switch import (
    filter_signals_by_regime,
    is_trade_allowed,
    REGIME_BASE_CONFIDENCE,
)

NEUTRAL_ZONE = 0.0
MIN_AGREEMENTS = 2

def _ema_cross(df, fast=20, slow=50):
    ema_f = df['close'].ewm(span=fast).mean()
    ema_s = df['close'].ewm(span=slow).mean()
    if len(ema_f) < 2:
        return None
    if ema_f.iloc[-1] > ema_s.iloc[-1] and ema_f.iloc[-2] <= ema_s.iloc[-2]:
        return "BUY"
    if ema_f.iloc[-1] < ema_s.iloc[-1] and ema_f.iloc[-2] >= ema_s.iloc[-2]:
        return "SELL"
    return None

def _rsi_mr(df, period=14, os=30, ob=70):
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    if rsi.iloc[-1] < os and rsi.iloc[-2] >= os:
        return "BUY"
    if rsi.iloc[-1] > ob and rsi.iloc[-2] <= ob:
        return "SELL"
    return None

def _macd_hist(df, fast=12, slow=26, signal=9):
    ema_f = df['close'].ewm(span=fast).mean()
    ema_s = df['close'].ewm(span=slow).mean()
    macd = ema_f - ema_s
    sig = macd.ewm(span=signal).mean()
    hist = macd - sig
    if hist.iloc[-1] > 0 and hist.iloc[-2] <= 0:
        return "BUY"
    if hist.iloc[-1] < 0 and hist.iloc[-2] >= 0:
        return "SELL"
    return None

def _bb_mr(df, period=20, std=2.0):
    sma = df['close'].rolling(period).mean()
    std_dev = df['close'].rolling(period).std()
    up = sma + std * std_dev
    lo = sma - std * std_dev
    if df['close'].iloc[-1] < lo.iloc[-1] and df['close'].iloc[-2] >= lo.iloc[-2]:
        return "BUY"
    if df['close'].iloc[-1] > up.iloc[-1] and df['close'].iloc[-2] <= up.iloc[-2]:
        return "SELL"
    return None

INDICATOR_FUNCS = {
    "EMA_CROSS_20_50": _ema_cross,
    "RSI_MR_30_70": _rsi_mr,
    "MACD_HIST": _macd_hist,
    "BB_MR": _bb_mr,
}

def generate_confluence(df):
    regime = detect_regime(df)
    raw_signals = {name: fn(df) for name, fn in INDICATOR_FUNCS.items()}
    filtered = filter_signals_by_regime(raw_signals, regime)
    
    buys = sum(1 for s in filtered.values() if s == "BUY")
    sells = sum(1 for s in filtered.values() if s == "SELL")
    total = len(filtered)
    
    trade_allowed, block_reason = is_trade_allowed(regime, total)
    
    if buys >= sells and buys > 0:
        direction = "BUY"
        agreement_ratio = buys / total if total > 0 else 0
    elif sells > buys:
        direction = "SELL"
        agreement_ratio = sells / total if total > 0 else 0
    else:
        direction = None
        agreement_ratio = 0.0
    
    base_conf = REGIME_BASE_CONFIDENCE.get(regime, 0.5)
    confidence = round(base_conf * agreement_ratio, 3) if direction else 0.0
    
    if total < MIN_AGREEMENTS:
        trade_allowed = False
        block_reason = f"Only {total} indicators active (min {MIN_AGREEMENTS})"
        direction = None
        confidence = 0.0
    
    return {
        "regime": regime,
        "raw_signals": raw_signals,
        "filtered_signals": filtered,
        "direction": direction,
        "agreement_ratio": round(agreement_ratio, 3),
        "confidence": confidence,
        "trade_allowed": trade_allowed,
        "block_reason": block_reason if not trade_allowed else None,
        "active_indicators": list(filtered.keys()),
    }
''',

    "RSP/signal_fusion/__init__.py": "",
    "RSP/signal_fusion/fusion_engine.py": r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP Fusion Engine v2.0
Dynamic weights per regime.
"""

from RSP.regime_switch.regime_switch import get_regime_weights, REGIME_BASE_CONFIDENCE

THRESHOLD_BUY = 0.35
THRESHOLD_SELL = -0.35

def compute_fusion_score(confluence_result, volume_conf=1.0, momentum_score=0.0):
    regime = confluence_result["regime"]
    filtered = confluence_result["filtered_signals"]
    direction = confluence_result["direction"]
    agreement_ratio = confluence_result["agreement_ratio"]
    
    if not direction or not filtered:
        return {
            "final_direction": None,
            "fusion_score": 0.0,
            "meta": {"reason": "No confluence or blocked"}
        }
    
    dynamic_weights = get_regime_weights(regime)
    scored = {}
    for ind, sig in filtered.items():
        w = dynamic_weights.get(ind, 0.0)
        val = 1.0 if sig == "BUY" else -1.0
        scored[ind] = val * w
    
    weighted_sum = sum(scored.values())
    base_conf = REGIME_BASE_CONFIDENCE.get(regime, 0.5)
    volume_confidence = min(max(volume_conf, 0.3), 1.0)
    
    momentum_boost = 0.0
    if "UPTREND" in regime and momentum_score > 0:
        momentum_boost = momentum_score * 0.15
    elif "DOWNTREND" in regime and momentum_score < 0:
        momentum_boost = abs(momentum_score) * 0.15
    
    final_score = weighted_sum * base_conf * volume_confidence
    final_score += momentum_boost if direction == "BUY" else -momentum_boost
    final_score = round(final_score, 4)
    
    if final_score >= THRESHOLD_BUY:
        final_direction = "BUY"
    elif final_score <= THRESHOLD_SELL:
        final_direction = "SELL"
    else:
        final_direction = None
    
    return {
        "final_direction": final_direction,
        "fusion_score": final_score,
        "meta": {
            "regime": regime,
            "dynamic_weights": dynamic_weights,
            "scored": scored,
            "base_confidence": base_conf,
            "volume_confidence": volume_confidence,
            "momentum_boost": round(momentum_boost, 4),
            "threshold_used": THRESHOLD_BUY if direction == "BUY" else abs(THRESHOLD_SELL),
        }
    }
''',
}

def main():
    for path, content in FILES.items():
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"[OK] {path} ({len(content)} bytes)")
    print("\nAll core fixes installed.")
    print("Next: update your main.py to use generate_confluence() + compute_fusion_score()")

if __name__ == "__main__":
    main()