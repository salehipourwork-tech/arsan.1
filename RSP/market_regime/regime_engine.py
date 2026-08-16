#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import pandas as pd

def detect_regime(df):
    if len(df) < 50:
        return "UNKNOWN"
    close = df["close"]
    ema20 = close.ewm(span=20).mean()
    ema50 = close.ewm(span=50).mean()
    diff_pct = (ema20.iloc[-1] - ema50.iloc[-1]) / ema50.iloc[-1] * 100
    high, low, close_s = df["high"], df["low"], df["close"]
    tr1 = high - low
    tr2 = (high - close_s.shift(1)).abs()
    tr3 = (low - close_s.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/14, min_periods=14).mean()
    volatility = (atr.iloc[-1] / close.iloc[-1]) * 100 if atr.iloc[-1] and close.iloc[-1] else 0
    price_change = (close.iloc[-1] - close.iloc[-20]) / close.iloc[-20] * 100 if len(close) >= 20 else 0
    if volatility > 5.0:
        return "HIGH_VOLATILITY"
    if diff_pct > 2.0 and price_change > 5:
        return "STRONG_UPTREND"
    elif diff_pct > 0.8:
        return "UPTREND"
    elif diff_pct < -2.0 and price_change < -5:
        return "STRONG_DOWNTREND"
    elif diff_pct < -0.8:
        return "DOWNTREND"
    else:
        return "RANGE"
