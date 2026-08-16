#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP — Signal Audit Tool (Fixed v2)
هر اندیکاتور را جداگانه و به‌تفکیک رژیم بازار بک‌تست می‌کند.
"""

import os
import sys
import json
import time
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from RSP.config import settings
from RSP.ingestion.data_universe import build_data_universe
from RSP.execution_simulator.trade_simulator import simulate_trade

COINS = ["bitcoin", "ethereum", "binancecoin", "ripple", "solana", "dogecoin", "cardano"]
DAYS = 90
BASE_TF = "15M"

# ---------------------------------------------------------------------------
# ۱. ATR واقعی (Wilder's True Range) — رفع باگ اصلی
# ---------------------------------------------------------------------------
def _calculate_atr(df, period=14):
    """
    Average True Range استاندارد:
    TR = max(high-low, |high-prev_close|, |low-prev_close|)
    ATR = EMA(TR, period)
    """
    if len(df) < period + 2:
        return None
    
    high = df['high']
    low = df['low']
    close = df['close']
    
    tr1 = high - low
    tr2 = (high - close.shift(1)).abs()
    tr3 = (low - close.shift(1)).abs()
    
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/period, min_periods=period).mean()
    
    return float(atr.iloc[-1])

# ---------------------------------------------------------------------------
# ۲. تشخیص رژیم بازار (سبک و مستقل — هم‌راستا با RSP Regime Engine)
# ---------------------------------------------------------------------------
def _detect_regime(df):
    """
    رژیم را بر اساس EMA Spread + Volatility + Momentum تشخیص می‌دهد.
    خروجی: STRONG_UPTREND | UPTREND | RANGE | DOWNTREND | STRONG_DOWNTREND | HIGH_VOLATILITY
    """
    if len(df) < 50:
        return "UNKNOWN"
    
    close = df['close']
    ema20 = close.ewm(span=20).mean()
    ema50 = close.ewm(span=50).mean()
    
    diff_pct = (ema20.iloc[-1] - ema50.iloc[-1]) / ema50.iloc[-1] * 100
    atr = _calculate_atr(df, period=14)
    volatility = (atr / close.iloc[-1]) * 100 if atr else 0
    
    # تغییر ۲۰ کندل اخیر
    price_change = (close.iloc[-1] - close.iloc[-20]) / close.iloc[-20] * 100 if len(close) >= 20 else 0
    
    # High Volatility اولویت دارد (هر رژیمی با نوسان شدید پرریسک است)
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

# ---------------------------------------------------------------------------
# سیگنال‌دهنده‌های ساده (بدون تغییر منطق، فقط تمیزتر)
# ---------------------------------------------------------------------------
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

# ---------------------------------------------------------------------------
# موتور اصلی Audit — حالا با رژیم و ATR واقعی
# ---------------------------------------------------------------------------
def audit_indicator(coin, name, signal_fn):
    """
    خروجی: دیکشنری شامل 'overall' و 'by_regime'
    """
    empty = {
        "overall": {"trades": 0, "wr": 0.0, "net": 0.0, "pf": 0.0, "max_dd": 0.0},
        "by_regime": {}
    }
    
    try:
        universe = build_data_universe(coin, lookback_days=DAYS)
        df = universe.bars.get(BASE_TF)
        if df is None or len(df) < 60:
            print(f"  [!] {coin}/{name}: دادهٔ کافی نیست ({len(df) if df is not None else 0} بار)")
            return empty
        
        trades = []  # لیستی از dict: {regime, outcome, pnl_pct, ...}
        
        for i in range(50, len(df) - 1):
            slice_df = df.iloc[:i+1]
            signal = signal_fn(slice_df)
            if signal is None:
                continue
            
            # ATR واقعی
            atr = _calculate_atr(slice_df, period=14)
            if atr is None or atr <= 0:
                continue
            
            # رژیم در لحظهٔ ورود
            regime = _detect_regime(slice_df)
            
            sl = 1.5 * atr
            tp = 2.5 * sl  # RR=2.5 هم‌راستا با تنظیمات RSP
            entry = slice_df['close'].iloc[-1]
            
            if signal == "BUY":
                stop, target = entry - sl, entry + tp
            else:
                stop, target = entry + sl, entry - tp
            
            future = df.iloc[i+1:]
            trade = simulate_trade(signal, entry, stop, target, future)
            
            if trade.outcome in ("WIN", "LOSS"):
                trades.append({
                    "regime": regime,
                    "outcome": trade.outcome,
                    "pnl_pct": trade.pnl_pct,
                })
        
        if not trades:
            return empty
        
        def _calc_stats(trade_list):
            if not trade_list:
                return {"trades": 0, "wr": 0.0, "net": 0.0, "pf": 0.0, "max_dd": 0.0}
            
            wins = sum(1 for t in trade_list if t["outcome"] == "WIN")
            net = sum(t["pnl_pct"] for t in trade_list)
            
            gains = sum(t["pnl_pct"] for t in trade_list if t["pnl_pct"] > 0)
            losses = abs(sum(t["pnl_pct"] for t in trade_list if t["pnl_pct"] < 0))
            pf = round(gains / losses, 3) if losses > 0 else 0.0
            
            # Max Drawdown از equity curve
            equity = [0.0]
            for t in trade_list:
                equity.append(equity[-1] + t["pnl_pct"])
            
            peak, max_dd = equity[0], 0.0
            for v in equity:
                peak = max(peak, v)
                max_dd = max(max_dd, peak - v)
            
            return {
                "trades": len(trade_list),
                "wr": round(wins / len(trade_list) * 100, 1),
                "net": round(net, 2),
                "pf": pf,
                "max_dd": round(max_dd, 2),
            }
        
        # محاسبهٔ کلی
        overall = _calc_stats(trades)
        
        # محاسبهٔ به‌تفکیک رژیم
        by_regime = {}
        for regime in set(t["regime"] for t in trades):
            regime_trades = [t for t in trades if t["regime"] == regime]
            by_regime[regime] = _calc_stats(regime_trades)
        
        return {"overall": overall, "by_regime": by_regime}
        
    except Exception as e:
        print(f"  [ERROR] {coin}/{name}: {e}")
        return empty

# ---------------------------------------------------------------------------
# اجرا و گزارش‌دهی
# ---------------------------------------------------------------------------
def main():
    print("=" * 80)
    print("SIGNAL AUDIT — Regime-Aware Individual Indicator Backtest (90 days, 15M)")
    print("ATR: Wilder's True Range | RR: 2.5 | Regime Detection: Enabled")
    print("=" * 80)
    
    all_results = {}
    
    for coin in COINS:
        print(f"\n>>> {coin.upper()}")
        coin_res = {}
        
        for name, fn in INDICATORS.items():
            audit = audit_indicator(coin, name, fn)
            coin_res[name] = audit
            
            o = audit["overall"]
            pf_str = f"{o['pf']:.3f}" if o['trades'] > 0 else "N/A"
            dd_str = f"{o['max_dd']:.1f}%" if o['trades'] > 0 else "N/A"
            
            print(f"  {name:18s} | T={o['trades']:3d} | WR={o['wr']:5.1f}% | "
                  f"Net={o['net']:+.2f}% | PF={pf_str:>6s} | DD={dd_str:>6s}")
            
            # نمایش رژیم‌های غالب
            if audit["by_regime"]:
                regimes_sorted = sorted(
                    audit["by_regime"].items(),
                    key=lambda x: x[1]["trades"],
                    reverse=True
                )
                for reg, st in regimes_sorted[:3]:  # ۳ رژیم اول
                    if st["trades"] > 0:
                        print(f"      └─ {reg:18s}: T={st['trades']:3d} WR={st['wr']:5.1f}% "
                              f"Net={st['net']:+.2f}% PF={st['pf']:.2f}")
            
            time.sleep(1.5)
        
        all_results[coin] = coin_res
    
    # -----------------------------------------------------------------------
    # خلاصهٔ میانگین کل
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("AVERAGE ACROSS ALL COINS — OVERALL")
    print("=" * 80)
    print(f"{'Indicator':18s} {'Trades':>8} {'WR':>8} {'Net':>10} {'PF':>8} {'MaxDD':>10}")
    print("-" * 80)
    
    for name in INDICATORS.keys():
        vals = [all_results[c][name]["overall"] for c in COINS 
                if all_results[c][name]["overall"]["trades"] > 0]
        if vals:
            avg_trades = sum(v['trades'] for v in vals) / len(vals)
            avg_wr = sum(v['wr'] for v in vals) / len(vals)
            avg_net = sum(v['net'] for v in vals) / len(vals)
            avg_pf = sum(v['pf'] for v in vals) / len(vals)
            avg_dd = sum(v['max_dd'] for v in vals) / len(vals)
            print(f"{name:18s} {avg_trades:>8.0f} {avg_wr:>7.1f}% {avg_net:>+9.2f}% "
                  f"{avg_pf:>7.3f} {avg_dd:>9.1f}%")
    
    # -----------------------------------------------------------------------
    # خلاصهٔ میانگین به‌تفکیک رژیم
    # -----------------------------------------------------------------------
    print("\n" + "=" * 80)
    print("AVERAGE ACROSS ALL COINS — BY REGIME (Top Regimes Only)")
    print("=" * 80)
    
    # جمع‌آوری همهٔ رژیم‌ها
    all_regimes = set()
    for coin in COINS:
        for name in INDICATORS:
            all_regimes.update(all_results[coin][name]["by_regime"].keys())
    
    for regime in sorted(all_regimes):
        print(f"\n--- Regime: {regime} ---")
        print(f"{'Indicator':18s} {'Trades':>8} {'WR':>8} {'Net':>10} {'PF':>8}")
        print("-" * 60)
        
        for name in INDICATORS.keys():
            regime_vals = []
            for c in COINS:
                r = all_results[c][name]["by_regime"].get(regime)
                if r and r["trades"] > 0:
                    regime_vals.append(r)
            
            if regime_vals:
                avg_t = sum(v['trades'] for v in regime_vals) / len(regime_vals)
                avg_w = sum(v['wr'] for v in regime_vals) / len(regime_vals)
                avg_n = sum(v['net'] for v in regime_vals) / len(regime_vals)
                avg_p = sum(v['pf'] for v in regime_vals) / len(regime_vals)
                print(f"{name:18s} {avg_t:>8.0f} {avg_w:>7.1f}% {avg_n:>+9.2f}% {avg_p:>7.3f}")
            else:
                print(f"{name:18s} {'—':>8} {'—':>7} {'—':>9} {'—':>7}")
    
    # -----------------------------------------------------------------------
    # ذخیره
    # -----------------------------------------------------------------------
    os.makedirs("RSP/audit", exist_ok=True)
    with open("RSP/audit/indicator_audit_regime_aware.json", "w", encoding="utf-8") as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    
    print(f"\n[OK] Saved: RSP/audit/indicator_audit_regime_aware.json")

if __name__ == "__main__":
    main()