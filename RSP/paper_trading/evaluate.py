#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP — paper_trading/evaluate.py

گزارش عملکرد فقط پس از رسیدن به یک نمونه‌ی آماری معنادار (پیش‌فرض: حداقل
۳۰ پوزیشن کاغذیِ بسته‌شده — قابل تغییر با --min-trades، اما پیش‌فرض را
پایین نیاورید مگر دلیل صریح داشته باشید). قبل از رسیدن به آن آستانه، فقط
پیشرفت را گزارش می‌کند، نه verdict را.

هیچ پارامتری اینجا تغییر نمی‌کند — این ماژول فقط می‌خواند و جمع می‌بندد.
"""

import argparse
from collections import defaultdict
from typing import Any, Dict, List

from RSP.paper_trading import ledger


def compute_stats(trades: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(trades)
    wins = [t for t in trades if t["outcome"] == "TP"]
    losses = [t for t in trades if t["outcome"] == "SL"]
    win_rate = (len(wins) / n * 100.0) if n else 0.0

    gross_profit = sum(t["pnl_pct"] for t in wins if t["pnl_pct"] > 0)
    gross_loss = abs(sum(t["pnl_pct"] for t in losses if t["pnl_pct"] < 0))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else (
        float("inf") if gross_profit > 0 else 0.0
    )

    net_return_pct = sum(t["pnl_pct"] for t in trades)
    expectancy_pct = (net_return_pct / n) if n else 0.0

    # equity curve → max drawdown, in cumulative-% terms
    running = 0.0
    peak = 0.0
    max_dd = 0.0
    for t in trades:
        running += t["pnl_pct"]
        peak = max(peak, running)
        max_dd = max(max_dd, peak - running)

    regime_breakdown = defaultdict(lambda: {"trades": 0, "wins": 0, "net_pct": 0.0})
    for t in trades:
        r = t.get("regime_at_entry") or "UNKNOWN"
        rb = regime_breakdown[r]
        rb["trades"] += 1
        rb["wins"] += 1 if t["outcome"] == "TP" else 0
        rb["net_pct"] += t["pnl_pct"]
    for r, rb in regime_breakdown.items():
        rb["win_rate"] = (rb["wins"] / rb["trades"] * 100.0) if rb["trades"] else 0.0

    return {
        "trade_count": n, "win_rate_pct": round(win_rate, 2),
        "net_return_pct": round(net_return_pct, 3),
        "profit_factor": round(profit_factor, 3) if profit_factor != float("inf") else "inf",
        "expectancy_pct": round(expectancy_pct, 4),
        "max_drawdown_pct": round(max_dd, 3),
        "regime_breakdown": {k: {**v, "win_rate_pct": round(v["win_rate"], 2)}
                              for k, v in regime_breakdown.items()},
    }


def evaluate_coin(coin: str, min_trades: int = 30) -> Dict[str, Any]:
    trades = ledger.load_closed_trades(coin)
    decisions = ledger.load_decisions(coin)
    no_trade_count = sum(1 for d in decisions if d.get("action") in ("NO_TRADE", "WAIT"))

    result = {
        "coin": coin, "closed_paper_trades": len(trades),
        "total_decision_cycles_logged": len(decisions),
        "no_trade_or_wait_cycles": no_trade_count,
        "min_trades_required": min_trades,
        "statistically_meaningful": len(trades) >= min_trades,
    }
    if len(trades) >= min_trades:
        result["stats"] = compute_stats(trades)
    else:
        result["note"] = (
            f"فقط {len(trades)}/{min_trades} پوزیشن کاغذی بسته شده — هنوز برای گزارش "
            f"verdict آماری زود است. اجرای runner را طبق زمان‌بندی ادامه دهید."
        )
    return result


def main():
    ap = argparse.ArgumentParser(description="RSP paper-trading evaluation report.")
    ap.add_argument("--coins", nargs="+", default=["bitcoin"])
    ap.add_argument("--min-trades", type=int, default=30,
                     help="Minimum closed paper trades before reporting a verdict "
                          "(default 30 — a statistically thin but conventional floor).")
    args = ap.parse_args()

    for coin in args.coins:
        r = evaluate_coin(coin, min_trades=args.min_trades)
        print(f"\n=== {coin} ===")
        print(f"decision cycles logged: {r['total_decision_cycles_logged']} "
              f"(NO_TRADE/WAIT: {r['no_trade_or_wait_cycles']})")
        print(f"closed paper trades: {r['closed_paper_trades']} "
              f"(need {r['min_trades_required']} for a verdict)")
        if r["statistically_meaningful"]:
            s = r["stats"]
            print(f"  win_rate:      {s['win_rate_pct']}%")
            print(f"  net_return:    {s['net_return_pct']}%")
            print(f"  profit_factor: {s['profit_factor']}")
            print(f"  expectancy:    {s['expectancy_pct']}% / trade")
            print(f"  max_drawdown:  {s['max_drawdown_pct']}%")
            print(f"  trade_count:   {s['trade_count']}")
            print(f"  regime breakdown:")
            for reg, rb in s["regime_breakdown"].items():
                print(f"    {reg:15s} trades={rb['trades']:3d} win_rate={rb['win_rate_pct']:6.2f}% "
                      f"net={rb['net_pct']:+.3f}%")
        else:
            print(f"  {r['note']}")


if __name__ == "__main__":
    main()
