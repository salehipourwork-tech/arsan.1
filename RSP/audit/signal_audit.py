#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP — Signal Audit Tool
هر اندیکاتور رو جداگانه بک‌تست می‌کنه تا ببینیم کدوم واقعاً predictive است.
"""

import os
import sys
import json
import time
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from RSP.config import settings
from RSP.ingestion.data_universe import build_data_universe
from RSP.execution_simulator.trade_simulator import simulate_trade

COINS = ["bitcoin", "ethereum", "binancecoin", "ripple", "solana", "dogecoin", "cardano"]
DAYS = 90
BASE_TF = "15M"

def _ema_signal(df, fast=20, slow=50):
    ema_fast = df['close'].ewm(span=fast).mean()
    ema_slow = df['close'].ewm(span=slow).mean()
    if len(ema_fast) < 2 or len(ema_slow) < 2:
        return None
    if ema_fast.iloc[-1] > ema_slow.iloc[-1] and ema_fast.iloc[-2] <= ema_slow.iloc[-2]:
        return "BUY"
    if ema_fast.iloc[-1] < ema_slow.iloc[-1] and ema_fast.iloc[-2] >= ema_slow.iloc[-2]:
        return "SELL"
    return None

def _rsi_signal(df, period=14, oversold=30, overbought=70):
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    if rsi.iloc[-1] < oversold and rsi.iloc[-2] >= oversold:
        return "BUY"
    if rsi.iloc[-1] > overbought and rsi.iloc[-2] <= overbought:
        return "SELL"
    return None

def _macd_signal(df, fast=12, slow=26, signal=9):
    ema_fast = df['close'].ewm(span=fast).mean()
    ema_slow = df['close'].ewm(span=slow).mean()
    macd = ema_fast - ema_slow
    signal_line = macd.ewm(span=signal).mean()
    hist = macd - signal_line
    if hist.iloc[-1] > 0 and hist.iloc[-2] <= 0:
        return "BUY"
    if hist.iloc[-1] < 0 and hist.iloc[-2] >= 0:
        return "SELL"
    return None

def _bb_signal(df, period=20, std=2.0):
    sma = df['close'].rolling(period).mean()
    std_dev = df['close'].rolling(period).std()
    upper = sma + std * std_dev
    lower = sma - std * std_dev
    if df['close'].iloc[-1] < lower.iloc[-1] and df['close'].iloc[-2] >= lower.iloc[-2]:
        return "BUY"
    if df['close'].iloc[-1] > upper.iloc[-1] and df['close'].iloc[-2] <= upper.iloc[-2]:
        return "SELL"
    return None

INDICATORS = {
    "EMA_CROSS_20_50": _ema_signal,
    "RSI_MR_30_70": _rsi_signal,
    "MACD_HIST": _macd_signal,
    "BB_MR": _bb_signal,
}

def audit_indicator(coin, name, signal_fn):
    result = {"name": name, "trades": 0, "wr": 0.0, "net": 0.0, "pf": 0.0, "max_dd": 0.0}
    try:
        universe = build_data_universe(coin, lookback_days=DAYS)
        df = universe.bars.get(BASE_TF)
        if df is None or len(df) < 60:
            return result
        
        trades = []
        equity = [0.0]
        
        for i in range(50, len(df) - 1):
            slice_df = df.iloc[:i+1]
            signal = signal_fn(slice_df)
            if signal is None:
                continue
            
            atr = (slice_df['high'].rolling(14).max() - slice_df['low'].rolling(14).min()).iloc[-1]
            if pd.isna(atr) or atr <= 0:
                continue
            sl = 1.5 * atr
            tp = 2.5 * sl
            entry = slice_df['close'].iloc[-1]
            
            if signal == "BUY":
                stop, target = entry - sl, entry + tp
            else:
                stop, target = entry + sl, entry - tp
            
            future = df.iloc[i+1:]
            trade = simulate_trade(signal, entry, stop, target, future)
            
            if trade.outcome in ("WIN", "LOSS"):
                trades.append(trade)
                equity.append(equity[-1] + trade.pnl_pct)
        
        if not trades:
            return result
        
        wins = sum(1 for t in trades if t.outcome == "WIN")
        result["trades"] = len(trades)
        result["wr"] = round(wins / len(trades) * 100, 1)
        result["net"] = round(sum(t.pnl_pct for t in trades), 2)
        
        gp = sum(t.pnl_pct for t in trades if t.pnl_pct > 0)
        gl = abs(sum(t.pnl_pct for t in trades if t.pnl_pct < 0))
        result["pf"] = round(gp / gl, 3) if gl > 0 else 0.0
        
        peak, max_dd = equity[0], 0.0
        for v in equity:
            peak = max(peak, v)
            max_dd = max(max_dd, peak - v)
        result["max_dd"] = round(max_dd, 2)
        
    except Exception as e:
        print(f"    ERROR {name}: {e}")
    
    return result

def main():
    print("="*70)
    print("SIGNAL AUDIT — Individual Indicator Backtest (90 days, 15M)")
    print("="*70)
    
    all_results = {}
    for coin in COINS:
        print(f"\n>>> {coin.upper()}")
        coin_res = {}
        for name, fn in INDICATORS.items():
            audit = audit_indicator(coin, name, fn)
            coin_res[name] = audit
            pf_str = f"{audit['pf']:.3f}" if audit['pf'] else "N/A"
            dd_str = f"{audit['max_dd']:.1f}%" if audit['max_dd'] else "N/A"
            print(f"  {name:18s} | T={audit['trades']:3d} | WR={audit['wr']:5.1f}% | "
                  f"Net={audit['net']:+.2f}% | PF={pf_str:>6s} | DD={dd_str:>6s}")
        all_results[coin] = coin_res
        time.sleep(2)
    
    # Summary
    print("\n" + "="*70)
    print("AVERAGE ACROSS ALL COINS")
    print("="*70)
    print(f"{'Indicator':18s} {'Trades':>8} {'WR':>8} {'Net':>10} {'PF':>8} {'MaxDD':>10}")
    print("-"*70)
    
    for name in INDICATORS.keys():
        vals = [all_results[c][name] for c in COINS if all_results[c][name]["trades"] > 0]
        if vals:
            avg_trades = sum(v['trades'] for v in vals) / len(vals)
            avg_wr = sum(v['wr'] for v in vals) / len(vals)
            avg_net = sum(v['net'] for v in vals) / len(vals)
            avg_pf = sum(v['pf'] for v in vals) / len(vals)
            avg_dd = sum(v['max_dd'] for v in vals) / len(vals)
            print(f"{name:18s} {avg_trades:>8.0f} {avg_wr:>7.1f}% {avg_net:>+9.2f}% "
                  f"{avg_pf:>7.3f} {avg_dd:>9.1f}%")
    
    # Save
    os.makedirs("RSP/audit", exist_ok=True)
    with open("RSP/audit/indicator_audit.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] Saved: RSP/audit/indicator_audit.json")

if __name__ == "__main__":
    main()