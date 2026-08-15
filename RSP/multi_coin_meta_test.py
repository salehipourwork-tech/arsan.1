#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP — Multi-Coin Meta Test v2 (Profitability Fix)

Baseline uses OLD params (RR=2.0, SL=2.5ATR, SL_FIRST)
Fuzzy uses NEW params (RR=2.5, SL=1.5ATR, PROPORTIONAL)

Run: python RSP/multi_coin_meta_test.py
"""

import os
import sys
import json
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from RSP.config import settings
from RSP.ingestion.data_universe import build_data_universe
from RSP.backtest_engine.backtest_engine import run_backtest

COINS = [
    {"id": "bitcoin", "symbol": "BTC"},
    {"id": "ethereum", "symbol": "ETH"},
    {"id": "binancecoin", "symbol": "BNB"},
    {"id": "ripple", "symbol": "XRP"},
    {"id": "solana", "symbol": "SOL"},
    {"id": "dogecoin", "symbol": "DOGE"},
    {"id": "cardano", "symbol": "ADA"},
]

DAYS = 90
BASE_TF = "15M"
RATE_LIMIT_SECONDS = 2

# OLD params (Baseline)
OLD_RR = 2.0
OLD_SL_MULT = 2.5
OLD_EXIT = "SL_FIRST"
OLD_OPP = 50.0

# NEW params (Fuzzy)
NEW_RR = 2.5
NEW_SL_MULT = 1.5
NEW_EXIT = "PROPORTIONAL"
NEW_OPP = 75.0


@dataclass
class TestResult:
    coin: str
    scenario: str
    total_trades: int = 0
    win_rate: float = 0.0
    net_return_pct: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    avg_trade_pct: float = 0.0
    fuzzy_steps: int = 0
    fuzzy_overrides: int = 0
    opportunity_score_avg: float = None
    opportunity_score_min: float = None
    opportunity_score_max: float = None
    current_threshold: float = None
    rejection_reasons: Dict = field(default_factory=dict)
    rejected_trade_outcomes: Dict = field(default_factory=dict)
    error: str = ""


def _apply_params(rr, sl_mult, exit_mode, opp_threshold):
    """Temporarily apply scenario-specific params."""
    settings.RR_TARGET = rr
    settings.SL_ATR_MULTIPLIER = sl_mult
    settings.CONSERVATIVE_SL_TP_SAME_CANDLE = exit_mode
    settings.MIN_OPPORTUNITY_SCORE_FOR_TRADE = opp_threshold
    settings.FUZZY_OPPORTUNITY_THRESHOLD = opp_threshold


def run_scenario(coin: str, scenario_name: str, use_fuzzy: bool, use_ahp: bool) -> TestResult:
    result = TestResult(coin=coin, scenario=scenario_name)

    # Save originals
    orig = {
        "fuzzy": settings.FUZZY_BACKTEST_ENABLED,
        "opp_method": getattr(settings, "OPPORTUNITY_SCORING_METHOD", "rules"),
        "rr": getattr(settings, "RR_TARGET", 2.5),
        "sl": getattr(settings, "SL_ATR_MULTIPLIER", 1.5),
        "exit": getattr(settings, "CONSERVATIVE_SL_TP_SAME_CANDLE", "PROPORTIONAL"),
        "opp": getattr(settings, "MIN_OPPORTUNITY_SCORE_FOR_TRADE", 75.0),
    }

    try:
        # Apply scenario params
        if scenario_name == "Baseline":
            _apply_params(OLD_RR, OLD_SL_MULT, OLD_EXIT, OLD_OPP)
        else:
            _apply_params(NEW_RR, NEW_SL_MULT, NEW_EXIT, NEW_OPP)

        settings.FUZZY_BACKTEST_ENABLED = use_fuzzy
        if use_fuzzy:
            settings.OPPORTUNITY_SCORING_METHOD = "ahp" if use_ahp else "rules"
        else:
            settings.OPPORTUNITY_SCORING_METHOD = "rules"

        print(f"\n>>> [{coin}] {scenario_name} — fuzzy={use_fuzzy}, ahp={use_ahp}")
        print(f"    Params: RR={settings.RR_TARGET}, SL={settings.SL_ATR_MULTIPLIER}ATR, "
              f"Exit={settings.CONSERVATIVE_SL_TP_SAME_CANDLE}, Opp>={settings.MIN_OPPORTUNITY_SCORE_FOR_TRADE}")

        universe = build_data_universe(coin, lookback_days=DAYS)
        base_bars = universe.bars.get(BASE_TF)
        if base_bars is None or base_bars.empty:
            result.error = "No data available"
            return result

        summary = run_backtest(universe.bars, base_tf=BASE_TF, coin_id=coin)

        result.total_trades = summary.total_trades
        result.win_rate = summary.win_rate
        result.net_return_pct = summary.net_return_pct
        result.profit_factor = summary.profit_factor
        result.max_drawdown_pct = summary.max_drawdown_pct
        result.avg_trade_pct = summary.average_trade_pct

        if summary.fuzzy_diagnostics:
            d = summary.fuzzy_diagnostics
            result.fuzzy_steps = d.get("fuzzy_steps", 0)
            result.fuzzy_overrides = d.get("fuzzy_overrides", 0)
            result.opportunity_score_avg = d.get("opportunity_score_avg")
            result.opportunity_score_min = d.get("opportunity_score_min")
            result.opportunity_score_max = d.get("opportunity_score_max")
            result.current_threshold = d.get("current_threshold")
            result.rejection_reasons = d.get("rejection_reasons", {})
            result.rejected_trade_outcomes = d.get("rejected_trade_outcomes", {})

        print(f"    → trades={result.total_trades} WR={result.win_rate}% "
              f"Net={result.net_return_pct}% PF={result.profit_factor} "
              f"MaxDD={result.max_drawdown_pct}%")

    except Exception as e:
        result.error = str(e)
        print(f"    ERROR: {e}")

    finally:
        # Restore originals
        settings.FUZZY_BACKTEST_ENABLED = orig["fuzzy"]
        settings.OPPORTUNITY_SCORING_METHOD = orig["opp_method"]
        settings.RR_TARGET = orig["rr"]
        settings.SL_ATR_MULTIPLIER = orig["sl"]
        settings.CONSERVATIVE_SL_TP_SAME_CANDLE = orig["exit"]
        settings.MIN_OPPORTUNITY_SCORE_FOR_TRADE = orig["opp"]
        settings.FUZZY_OPPORTUNITY_THRESHOLD = orig["opp"]

    return result


def run_all_scenarios(coin: str) -> dict:
    print(f"\n{'='*70}")
    print(f"Coin: {coin.upper()}")
    print(f"{'='*70}")

    baseline = run_scenario(coin, "Baseline", use_fuzzy=False, use_ahp=False)
    time.sleep(RATE_LIMIT_SECONDS)

    fuzzy_rules = run_scenario(coin, "Fuzzy+Rules", use_fuzzy=True, use_ahp=False)
    time.sleep(RATE_LIMIT_SECONDS)

    fuzzy_ahp = run_scenario(coin, "Fuzzy+AHPv2", use_fuzzy=True, use_ahp=True)
    time.sleep(RATE_LIMIT_SECONDS)

    # Meta-Controller
    print(f"\n>>> [{coin}] Meta-Controller")
    rules_dd = abs(fuzzy_rules.max_drawdown_pct) if fuzzy_rules and not fuzzy_rules.error else 999
    ahp_dd = abs(fuzzy_ahp.max_drawdown_pct) if fuzzy_ahp and not fuzzy_ahp.error else 999

    if ahp_dd < rules_dd and (rules_dd - ahp_dd) > 30:
        meta_result = fuzzy_ahp
        meta_source = "AHPv2"
    else:
        meta_result = fuzzy_rules
        meta_source = "Rules"

    print(f"    → Meta selected: {meta_source} (Rules DD={rules_dd:.1f}%, AHP DD={ahp_dd:.1f}%)")

    return {
        "coin": coin,
        "baseline": asdict(baseline) if baseline else None,
        "fuzzy_rules": asdict(fuzzy_rules) if fuzzy_rules else None,
        "fuzzy_ahp": asdict(fuzzy_ahp) if fuzzy_ahp else None,
        "meta_controller": {
            **asdict(meta_result),
            "meta_source": meta_source,
            "meta_selected": True,
        } if meta_result else None,
    }


def generate_markdown_report(all_results: list) -> str:
    lines = [
        "# Multi-Coin Meta Test Report v2",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        f"**Period:** {DAYS} days | **Timeframe:** {BASE_TF}",
        "**Baseline:** RR=2.0, SL=2.5ATR, SL_FIRST, Opp>=50",
        "**Fuzzy:** RR=2.5, SL=1.5ATR, PROPORTIONAL, Opp>=75",
        "",
        "| Coin | Baseline Net | Rules Net | AHPv2 Net | Meta Net | Meta Source |",
        "|------|-------------|-----------|-----------|----------|-------------|",
    ]

    for r in all_results:
        coin = r["coin"].upper()
        b = r["baseline"]["net_return_pct"] if r["baseline"] and not r["baseline"].get("error") else 0
        fr = r["fuzzy_rules"]["net_return_pct"] if r["fuzzy_rules"] and not r["fuzzy_rules"].get("error") else 0
        fa = r["fuzzy_ahp"]["net_return_pct"] if r["fuzzy_ahp"] and not r["fuzzy_ahp"].get("error") else 0
        m = r["meta_controller"]["net_return_pct"] if r["meta_controller"] else 0
        src = r["meta_controller"].get("meta_source", "-") if r["meta_controller"] else "-"
        lines.append(f"| {coin} | {b:+.2f}% | {fr:+.2f}% | {fa:+.2f}% | {m:+.2f}% | {src} |")

    lines.extend(["", "## Detailed Results", ""])
    for r in all_results:
        lines.append(f"### {r['coin'].upper()}")
        for scenario in ["baseline", "fuzzy_rules", "fuzzy_ahp", "meta_controller"]:
            s = r[scenario]
            if s and not s.get("error"):
                lines.append(
                    f"- **{scenario}:** Trades={s.get('total_trades',0)}, "
                    f"WR={s.get('win_rate',0)}%, Net={s.get('net_return_pct',0):+.2f}%, "
                    f"PF={s.get('profit_factor',0):.3f}, MaxDD={s.get('max_drawdown_pct',0):.2f}%"
                )
            elif s and s.get("error"):
                lines.append(f"- **{scenario}:** ERROR: {s.get('error')}")
        lines.append("")

    return "\n".join(lines)


def main():
    print("="*70)
    print("Arsan — Multi-Coin Meta Test v2 (Profitability Fix)")
    print(f"Date: {datetime.now(timezone.utc).isoformat()}")
    print(f"Coins: {', '.join(c['symbol'] for c in COINS)}")
    print("Baseline: RR=2.0 | SL=2.5ATR | SL_FIRST | Opp>=50")
    print("Fuzzy:    RR=2.5 | SL=1.5ATR | PROPORTIONAL | Opp>=75")
    print("="*70)

    all_results = []
    for coin_dict in COINS:
        result = run_all_scenarios(coin_dict["id"])
        all_results.append(result)

    report_dir = os.path.join("RSP", "baseline_reports", "multi_coin_meta_v2")
    os.makedirs(report_dir, exist_ok=True)

    json_path = os.path.join(report_dir, "multi_coin_meta_test_v2.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "meta": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "coins": [c["id"] for c in COINS],
                "baseline_params": {"RR": OLD_RR, "SL": OLD_SL_MULT, "EXIT": OLD_EXIT, "OPP": OLD_OPP},
                "fuzzy_params": {"RR": NEW_RR, "SL": NEW_SL_MULT, "EXIT": NEW_EXIT, "OPP": NEW_OPP},
            },
            "results": all_results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] JSON saved: {json_path}")

    md_path = os.path.join(report_dir, "multi_coin_meta_test_v2.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(generate_markdown_report(all_results))
    print(f"[OK] Markdown saved: {md_path}")

    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    print(f"{'Coin':<8} {'Baseline':>10} {'Rules':>10} {'AHPv2':>10} {'Meta':>10} {'Source':>10}")
    print("-"*70)
    for r in all_results:
        coin = r["coin"].upper()
        b = r["baseline"]["net_return_pct"] if r["baseline"] and not r["baseline"].get("error") else 0
        fr = r["fuzzy_rules"]["net_return_pct"] if r["fuzzy_rules"] and not r["fuzzy_rules"].get("error") else 0
        fa = r["fuzzy_ahp"]["net_return_pct"] if r["fuzzy_ahp"] and not r["fuzzy_ahp"].get("error") else 0
        m = r["meta_controller"]["net_return_pct"] if r["meta_controller"] else 0
        src = r["meta_controller"].get("meta_source", "-") if r["meta_controller"] else "-"
        print(f"{coin:<8} {b:>+9.2f}% {fr:>+9.2f}% {fa:>+9.2f}% {m:>+9.2f}% {src:>10}")


if __name__ == "__main__":
    main()
