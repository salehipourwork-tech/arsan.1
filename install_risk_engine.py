# install_risk_engine.py
import os

CONTENT = r'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP Risk Engine v2.0
- True ATR (Wilder)
- Dynamic SL/TP per regime
- Hard filters: RANGE / HIGH_VOLATILITY
- Daily circuit breaker + portfolio heat fuse
- Fixed fractional position sizing
"""

import os
import json
import numpy as np
import pandas as pd
from datetime import datetime

# --- Global Constants ---
MAX_DAILY_LOSS_PCT = 5.0
MAX_PORTFOLIO_HEAT = 60.0
MAX_SINGLE_EXPOSURE = 20.0
MIN_RISK_REWARD_RATIO = 1.5

# SL/TP multipliers per regime (x ATR14)
REGIME_SL_TP_MULTS = {
    "STRONG_UPTREND":   {"sl": 2.5, "tp": 3.5},
    "UPTREND":          {"sl": 2.0, "tp": 3.0},
    "RANGE":            {"sl": 1.2, "tp": 1.8},
    "DOWNTREND":        {"sl": 2.0, "tp": 3.0},
    "STRONG_DOWNTREND": {"sl": 2.5, "tp": 3.5},
    "HIGH_VOLATILITY":  {"sl": 0.0, "tp": 0.0},
}

# --- 1. True ATR ---
def calculate_atr(df, period=14):
    """Wilder's ATR."""
    if len(df) < period + 2:
        return None
    high, low, close = df['high'], df['low'], df['close']
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0/period, min_periods=period, adjust=False).mean()
    return float(atr.iloc[-1])

# --- 2. Dynamic SL/TP ---
def get_stop_loss_take_profit(entry_price, direction, atr14, regime):
    mults = REGIME_SL_TP_MULTS.get(regime, {"sl": 2.0, "tp": 3.0})
    if mults["sl"] == 0 or not atr14 or atr14 <= 0 or entry_price <= 0:
        return None, None, 0.0, "HIGH_VOLATILITY or invalid ATR/entry"
    sl_dist = mults["sl"] * atr14
    tp_dist = mults["tp"] * atr14
    if direction == "BUY":
        sl = entry_price - sl_dist
        tp = entry_price + tp_dist
    elif direction == "SELL":
        sl = entry_price + sl_dist
        tp = entry_price - tp_dist
    else:
        return None, None, 0.0, "Invalid direction"
    rr = round(tp_dist / sl_dist, 2) if sl_dist > 0 else 0.0
    return round(sl, 8), round(tp, 8), rr, None

# --- 3. Position Size (Fixed Fractional) ---
def calculate_position_size(equity, risk_per_trade_pct, entry, stop, max_leverage=1.0):
    if stop is None or entry is None or entry == stop:
        return {"size": 0, "notional": 0, "risk_amount": 0, "leverage_used": 0, "error": "No valid stop"}
    risk_amount = equity * (risk_per_trade_pct / 100.0)
    risk_per_unit = abs(entry - stop)
    if risk_per_unit == 0:
        return {"size": 0, "notional": 0, "risk_amount": 0, "leverage_used": 0, "error": "Zero risk distance"}
    raw_size = risk_amount / risk_per_unit
    notional = raw_size * entry
    max_notional = equity * (MAX_SINGLE_EXPOSURE / 100.0)
    leverage_used = 1.0
    if notional > max_notional and max_leverage > 1.0:
        leverage_used = min(notional / max_notional, max_leverage)
        notional = notional / leverage_used
        raw_size = notional / entry
    elif notional > max_notional:
        raw_size = max_notional / entry
        notional = max_notional
        leverage_used = 1.0
    return {
        "size": round(raw_size, 8),
        "notional": round(notional, 2),
        "risk_amount": round(risk_amount, 2),
        "leverage_used": round(leverage_used, 2),
        "risk_per_unit": round(risk_per_unit, 6),
        "error": None,
    }

# --- 4. Regime & Risk Filters ---
def check_regime_risk(regime, confidence, max_range_dd_percent=15.0):
    if regime == "HIGH_VOLATILITY":
        return False, "RiskEngine: High volatility regime — mandatory block"
    if regime == "RANGE" and confidence < 0.35:
        return False, f"RiskEngine: RANGE confidence {confidence:.3f} below 0.35"
    return True, None

def check_daily_limits(equity, daily_pnl_log, today=None):
    if today is None:
        today = datetime.now().strftime("%Y-%m-%d")
    today_trades = [t for t in daily_pnl_log if t.get("date_iso") == today]
    if not today_trades:
        return True, None
    total_pnl_pct = sum(t.get("pnl_pct", 0) for t in today_trades)
    if total_pnl_pct <= -MAX_DAILY_LOSS_PCT:
        return False, f"Daily circuit breaker: {total_pnl_pct:.2f}% loss (limit: -{MAX_DAILY_LOSS_PCT}%)"
    return True, None

def check_portfolio_heat(current_exposures_usd, equity):
    total_exposure = sum(current_exposures_usd)
    heat_pct = (total_exposure / equity) * 100 if equity > 0 else 0
    if heat_pct > MAX_PORTFOLIO_HEAT:
        return False, f"Portfolio heat {heat_pct:.1f}% exceeds {MAX_PORTFOLIO_HEAT}%"
    return True, None

def check_min_risk_reward(rr_ratio):
    if rr_ratio is None or rr_ratio < MIN_RISK_REWARD_RATIO:
        return False, f"RR {rr_ratio} below min {MIN_RISK_REWARD_RATIO}"
    return True, None

# --- 5. Main Risk Evaluator ---
def evaluate_trade_risk(df, entry_price, direction, equity, regime, confidence,
                    daily_pnl_log=None, current_exposures_usd=None,
                    risk_per_trade_pct=2.0, max_leverage=1.0):
    result = {
        "timestamp": datetime.now().isoformat(),
        "allowed": False,
        "reason": None,
        "regime": regime,
        "direction": direction,
        "entry": entry_price,
        "sl": None,
        "tp": None,
        "rr_ratio": 0.0,
        "position": None,
        "checks": {},
    }
    ok, reason = check_regime_risk(regime, confidence)
    result["checks"]["regime"] = {"ok": ok, "reason": reason}
    if not ok:
        result["reason"] = reason
        return result
    atr14 = calculate_atr(df, period=14)
    sl, tp, rr, err = get_stop_loss_take_profit(entry_price, direction, atr14, regime)
    result["checks"]["atr_sl_tp"] = {"ok": err is None, "atr14": round(atr14, 6) if atr14 else None, "reason": err}
    if err:
        result["reason"] = err
        return result
    result["sl"] = sl
    result["tp"] = tp
    result["rr_ratio"] = rr
    ok, reason = check_min_risk_reward(rr)
    result["checks"]["min_rr"] = {"ok": ok, "reason": reason}
    if not ok:
        result["reason"] = reason
        return result
    if daily_pnl_log is not None:
        ok, reason = check_daily_limits(equity, daily_pnl_log)
        result["checks"]["daily_limit"] = {"ok": ok, "reason": reason}
        if not ok:
            result["reason"] = reason
            return result
    if current_exposures_usd is not None:
        ok, reason = check_portfolio_heat(current_exposures_usd, equity)
        result["checks"]["portfolio_heat"] = {"ok": ok, "reason": reason}
        if not ok:
            result["reason"] = reason
            return result
    pos = calculate_position_size(equity, risk_per_trade_pct, entry_price, sl, max_leverage)
    result["checks"]["position_size"] = {"ok": pos.get("error") is None, "reason": pos.get("error")}
    if pos.get("error"):
        result["reason"] = pos["error"]
        return result
    result["position"] = pos
    result["allowed"] = True
    result["reason"] = "All risk checks passed"
    return result

# --- 6. Daily PNL Logger ---
def log_daily_trade(daily_log_path, date_iso, pnl_usd, pnl_pct, coin, direction):
    os.makedirs(os.path.dirname(daily_log_path), exist_ok=True)
    entry = {
        "date_iso": date_iso,
        "coin": coin,
        "direction": direction,
        "pnl_usd": round(pnl_usd, 2),
        "pnl_pct": round(pnl_pct, 4),
        "logged_at": datetime.now().isoformat(),
    }
    with open(daily_log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")

def load_daily_log(daily_log_path):
    if not os.path.exists(daily_log_path):
        return []
    logs = []
    with open(daily_log_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    logs.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return logs

# --- 7. Self-test ---
if __name__ == "__main__":
    np.random.seed(42)
    n = 200
    base = 100 + np.cumsum(np.random.randn(n) * 0.5)
    df_test = pd.DataFrame({
        "open": base,
        "close": base + np.random.randn(n) * 0.3,
        "high": base + 1.0,
        "low": base - 1.0,
        "volume": 1000,
    })
    df_test["high"] = df_test[["open", "close", "high"]].max(axis=1) + 0.5
    df_test["low"] = df_test[["open", "close", "low"]].min(axis=1) - 0.5

    entry = float(df_test["close"].iloc[-1])
    equity = 10000.0

    print("=" * 50)
    print("RISK ENGINE SELF-TEST")
    print("=" * 50)

    for regime in ["STRONG_UPTREND", "RANGE", "HIGH_VOLATILITY"]:
        conf = 0.6 if regime != "RANGE" else 0.3
        res = evaluate_trade_risk(
            df=df_test, entry_price=entry, direction="BUY",
            equity=equity, regime=regime, confidence=conf,
            risk_per_trade_pct=2.0,
        )
        print(f"\nRegime: {regime}")
        print(f"  Allowed: {res['allowed']}")
        print(f"  Reason:  {res['reason']}")
        if res['sl']:
            print(f"  SL: {res['sl']} | TP: {res['tp']} | RR: {res['rr_ratio']}")
        if res['position']:
            print(f"  Size: {res['position']['size']:.4f} | Notional: {res['position']['notional']}")

    print("\n[OK] Self-test completed.")
'''

TARGET = os.path.join("RSP", "risk_engine", "risk_engine.py")
INIT = os.path.join("RSP", "risk_engine", "__init__.py")

def main():
    os.makedirs(os.path.dirname(TARGET), exist_ok=True)
    with open(TARGET, "w", encoding="utf-8") as f:
        f.write(CONTENT)
    with open(INIT, "w", encoding="utf-8") as f:
        f.write("")
    print(f"[OK] Created: {TARGET}")
    print(f"[OK] Created: {INIT}")
    print(f"[OK] Size: {os.path.getsize(TARGET)} bytes")
    print("Now run: python -m RSP.risk_engine.risk_engine")

if __name__ == "__main__":
    main()