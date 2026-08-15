#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP — Multi-Coin Meta Test v2 (Profitability Fix)

تغییرات نسبت به v1:
1. TRX blacklisted (removed from COINS)
2. A+ filter (score >= 75) integrated in backtest_engine
3. RR=2.5 enforced via risk_engine
4. Proportional same-candle exit in trade_simulator
5. Regime-aware rule filtering ready (backtest_engine supports it)

Run: python RSP/multi_coin_meta_test.py
"""

import os
import sys
import json
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from RSP.config import settings
from RSP.ingestion.coingecko_client import fetch_ohlc
from RSP.backtest_engine.backtest_engine import run_backtest
from RSP.meta_controller.meta_controller import MetaController

# FIX v1: TRX removed from list
COINS = [
    {"id": "bitcoin", "symbol": "BTC"},
    {"id": "ethereum", "symbol": "ETH"},
    {"id": "binancecoin", "symbol": "BNB"},
    {"id": "ripple", "symbol": "XRP"},
    {"id": "solana", "symbol": "SOL"},
    {"id": "dogecoin", "symbol": "DOGE"},
    {"id": "cardano", "symbol": "ADA"},
    # {"id": "tron", "symbol": "TRX"},  # BLACKLISTED
]

DAYS = 90
BASE_TF = "15M"
RATE_LIMIT_SECONDS = 2


def fetch_and_backtest(coin: dict, use_fuzzy: bool = False, use_ahp: bool = False) -> dict:
    """Fetch data and run backtest for a single coin."""
    print(f"\n>>> [{coin['symbol']}] Fetching {DAYS} days of {BASE_TF} data...")

    try:
        df = fetch_ohlc(coin["id"], days=DAYS)
        if df is None or df.empty:
            print(f"    [!] No data for {coin['symbol']}")
            return None
    except Exception as e:
        print(f"    [!] Fetch error: {e}")
        return None

    # FIX v1: Pass coin_id for blacklist check
    bars_by_tf = {BASE_TF: df}

    # Temporarily override fuzzy setting
    original_fuzzy = settings.FUZZY_BACKTEST_ENABLED
    settings.FUZZY_BACKTEST_ENABLED = use_fuzzy

    try:
        summary = run_backtest(bars_by_tf, base_tf=BASE_TF, coin_id=coin["id"])
    finally:
        settings.FUZZY_BACKTEST_ENABLED = original_fuzzy

    return {
        "coin": coin["id"],
        "symbol": coin["symbol"],
        "total_trades": summary.total_trades,
        "win_rate": summary.win_rate,
        "net_return_pct": summary.net_return_pct,
        "profit_factor": summary.profit_factor,
        "max_drawdown_pct": summary.max_drawdown_pct,
        "average_trade_pct": summary.average_trade_pct,
        "fuzzy_steps": summary.fuzzy_diagnostics.get("fuzzy_steps", 0),
        "fuzzy_overrides": summary.fuzzy_diagnostics.get("fuzzy_overrides", 0),
        "opportunity_score_avg": summary.fuzzy_diagnostics.get("opportunity_score_avg", 0),
    }


def run_all_scenarios(coin: dict) -> dict:
    """Run all 4 scenarios for a single coin."""
    print(f"\n{'='*60}")
    print(f"Coin: {coin['symbol']} ({coin['id']})")
    print(f"{'='*60}")

    # Scenario 1: Baseline (no fuzzy)
    print(f"\n>>> [{coin['symbol']}] Scenario 1: Baseline")
    baseline = fetch_and_backtest(coin, use_fuzzy=False)
    time.sleep(RATE_LIMIT_SECONDS)

    # Scenario 2: Fuzzy + Rules
    print(f"\n>>> [{coin['symbol']}] Scenario 2: Fuzzy + Rules")
    fuzzy_rules = fetch_and_backtest(coin, use_fuzzy=True)
    time.sleep(RATE_LIMIT_SECONDS)

    # Scenario 3: Fuzzy + AHPv2
    print(f"\n>>> [{coin['symbol']}] Scenario 3: Fuzzy + AHPv2")
    # AHPv2 is controlled by OPPORTUNITY_SCORING_METHOD
    original_method = getattr(settings, "OPPORTUNITY_SCORING_METHOD", "rules")
    settings.OPPORTUNITY_SCORING_METHOD = "ahp"
    fuzzy_ahp = fetch_and_backtest(coin, use_fuzzy=True)
    settings.OPPORTUNITY_SCORING_METHOD = original_method
    time.sleep(RATE_LIMIT_SECONDS)

    # Scenario 4: Meta-Controller
    print(f"\n>>> [{coin['symbol']}] Scenario 4: Meta-Controller")
    meta = MetaController()
    # Meta selects best of Rules vs AHP based on MaxDD
    rules_dd = abs(fuzzy_rules.get("max_drawdown_pct", 0)) if fuzzy_rules else 999
    ahp_dd = abs(fuzzy_ahp.get("max_drawdown_pct", 0)) if fuzzy_ahp else 999

    if ahp_dd < rules_dd and (rules_dd - ahp_dd) > 30:
        meta_result = fuzzy_ahp.copy() if fuzzy_ahp else baseline.copy()
        meta_result["meta_source"] = "AHPv2"
    else:
        meta_result = fuzzy_rules.copy() if fuzzy_rules else baseline.copy()
        meta_result["meta_source"] = "Rules"
    meta_result["meta_selected"] = True

    return {
        "coin": coin["id"],
        "symbol": coin["symbol"],
        "baseline": baseline,
        "fuzzy_rules": fuzzy_rules,
        "fuzzy_ahp": fuzzy_ahp,
        "meta_controller": meta_result,
    }


def generate_markdown_report(all_results: list) -> str:
    """Generate markdown report."""
    lines = [
        "# Multi-Coin Meta Test Report v2",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        f"**Period:** {DAYS} days | **Timeframe:** {BASE_TF}",
        "**Fixes Applied:** RR=2.5 | A+ Filter >=75 | Proportional Exit | TRX Blacklisted",
        "",
        "## Results Summary",
        "",
        "| Coin | Baseline Net | Rules Net | AHPv2 Net | Meta Net | Meta Source |",
        "|------|-------------|-----------|-----------|----------|-------------|",
    ]

    for r in all_results:
        coin = r["symbol"]
        b = r["baseline"]["net_return_pct"] if r["baseline"] else 0
        fr = r["fuzzy_rules"]["net_return_pct"] if r["fuzzy_rules"] else 0
        fa = r["fuzzy_ahp"]["net_return_pct"] if r["fuzzy_ahp"] else 0
        m = r["meta_controller"]["net_return_pct"] if r["meta_controller"] else 0
        src = r["meta_controller"].get("meta_source", "-") if r["meta_controller"] else "-"
        lines.append(f"| {coin} | {b:+.2f}% | {fr:+.2f}% | {fa:+.2f}% | {m:+.2f}% | {src} |")

    lines.extend(["", "## Detailed Results", ""])
    for r in all_results:
        lines.append(f"### {r['symbol']}")
        for scenario in ["baseline", "fuzzy_rules", "fuzzy_ahp", "meta_controller"]:
            s = r[scenario]
            if s:
                lines.append(f"- **{scenario}:** Trades={s.get('total_trades',0)}, WR={s.get('win_rate',0)}%, Net={s.get('net_return_pct',0):+.2f}%, PF={s.get('profit_factor',0):.3f}, MaxDD={s.get('max_drawdown_pct',0):.2f}%")
        lines.append("")

    return "\n".join(lines)


def main():
    print("="*70)
    print("Arsan — Multi-Coin Meta Test v2 (Profitability Fix)")
    print(f"Date: {datetime.now(timezone.utc).isoformat()}")
    print(f"Coins: {', '.join(c['symbol'] for c in COINS)}")
    print("Fixes: RR=2.5 | A+ Filter >=75 | Proportional Exit | TRX Blacklist")
    print("="*70)

    all_results = []
    for coin in COINS:
        result = run_all_scenarios(coin)
        all_results.append(result)

    # Save JSON
    report_dir = os.path.join("RSP", "baseline_reports", "multi_coin_meta_v2")
    os.makedirs(report_dir, exist_ok=True)

    json_path = os.path.join(report_dir, "multi_coin_meta_test_v2.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "meta": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "coins": [c["id"] for c in COINS],
                "fixes": ["RR=2.5", "A+_Filter_75", "Proportional_Exit", "TRX_Blacklist"],
            },
            "results": all_results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] JSON saved: {json_path}")

    # Save Markdown
    md_path = os.path.join(report_dir, "multi_coin_meta_test_v2.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(generate_markdown_report(all_results))
    print(f"[OK] Markdown saved: {md_path}")

    # Print summary
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    print(f"{'Coin':<8} {'Baseline':>10} {'Rules':>10} {'AHPv2':>10} {'Meta':>10} {'Source':>10}")
    print("-"*70)
    for r in all_results:
        coin = r["symbol"]
        b = r["baseline"]["net_return_pct"] if r["baseline"] else 0
        fr = r["fuzzy_rules"]["net_return_pct"] if r["fuzzy_rules"] else 0
        fa = r["fuzzy_ahp"]["net_return_pct"] if r["fuzzy_ahp"] else 0
        m = r["meta_controller"]["net_return_pct"] if r["meta_controller"] else 0
        src = r["meta_controller"].get("meta_source", "-") if r["meta_controller"] else "-"
        print(f"{coin:<8} {b:>+9.2f}% {fr:>+9.2f}% {fa:>+9.2f}% {m:>+9.2f}% {src:>10}")


if __name__ == "__main__":
    main()
