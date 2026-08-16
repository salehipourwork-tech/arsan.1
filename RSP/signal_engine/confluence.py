#!/usr/bin/env python3
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
