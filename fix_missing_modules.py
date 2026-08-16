import os

# ۱. ساخت __init__.py برای market_regime
os.makedirs("RSP/market_regime", exist_ok=True)
with open("RSP/market_regime/__init__.py", "w", encoding="utf-8") as f:
    f.write("")

# ۲. اگر regime_engine.py نبود، می‌سازیمش
regime_engine = "RSP/market_regime/regime_engine.py"
if not os.path.exists(regime_engine):
    with open(regime_engine, "w", encoding="utf-8") as f:
        f.write('''#!/usr/bin/env python3
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
''')
    print("[OK] Created regime_engine.py")
else:
    print("[SKIP] regime_engine.py exists")

# ۳. چک کردن همهٔ __init__.pyها
for pkg in ["audit", "config", "execution_simulator", "ingestion", 
            "regime_switch", "signal_engine", "signal_fusion", "risk_engine", "market_regime"]:
    init_path = f"RSP/{pkg}/__init__.py"
    if not os.path.exists(init_path):
        with open(init_path, "w", encoding="utf-8") as f:
            f.write("")
        print(f"[OK] {pkg}/__init__.py created")
    else:
        print(f"[OK] {pkg}/__init__.py exists")

print("\nDone. Now run the test again.")