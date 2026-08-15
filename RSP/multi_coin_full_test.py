#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
آرسان — تست چندکوینه‌ی کامل (AHPv2 vs Rules vs Baseline)
برای کوین‌های باقی‌مانده: bitcoin, binancecoin, dogecoin, cardano, tron

نحوه‌ی اجرا:
    cd /path/to/arsan.1
    python RSP/multi_coin_full_test.py

این اسکریپت ۳ سناریو را روی هر کوین اجرا می‌کند:
    1. Baseline (فازی خاموش)
    2. Test B: Fuzzy + Rules
    3. Test A v2: Fuzzy + AHPv2

و نتایج را در یک جدول واحد JSON + Markdown ذخیره می‌کند.
"""

import os
import sys
import json
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Dict, List

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from RSP.config import settings
from RSP.ingestion.data_universe import build_data_universe
from RSP.backtest_engine.backtest_engine import run_backtest

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
REMAINING_COINS = ["bitcoin", "binancecoin", "dogecoin", "cardano", "tron"]
LOOKBACK_DAYS = 90
BASE_TF = "15M"
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "baseline_reports", "multi_coin_tests")

# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------
@dataclass
class TestResult:
    coin: str
    scenario: str  # "Baseline", "Fuzzy+Rules", "Fuzzy+AHPv2"
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

@dataclass
class CoinReport:
    coin: str
    baseline: TestResult = None
    fuzzy_rules: TestResult = None
    fuzzy_ahp: TestResult = None

# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
def run_scenario(coin: str, scenario_name: str, use_fuzzy: bool, use_ahp: bool) -> TestResult:
    """Run a single backtest scenario for one coin."""
    result = TestResult(coin=coin, scenario=scenario_name)

    # Save original settings
    orig_fuzzy_enabled = settings.FUZZY_BACKTEST_ENABLED
    orig_opportunity_method = getattr(settings, "OPPORTUNITY_SCORING_METHOD", "rules")

    try:
        # Apply scenario settings
        settings.FUZZY_BACKTEST_ENABLED = use_fuzzy
        if use_fuzzy:
            settings.OPPORTUNITY_SCORING_METHOD = "ahp" if use_ahp else "rules"
        else:
            settings.OPPORTUNITY_SCORING_METHOD = "rules"

        print(f"\n>>> [{coin}] {scenario_name} — fuzzy={use_fuzzy}, ahp={use_ahp}")

        # Build data universe
        universe = build_data_universe(coin, lookback_days=LOOKBACK_DAYS)
        base_bars = universe.bars.get(BASE_TF)
        if base_bars is None or base_bars.empty:
            result.error = "No data available"
            return result

        # Run backtest
        summary = run_backtest(universe.bars, base_tf=BASE_TF)

        # Fill result
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

        print(f"    trades={result.total_trades}  win_rate={result.win_rate}%  "
              f"net={result.net_return_pct}%  PF={result.profit_factor}  "
              f"maxDD={result.max_drawdown_pct}%")

    except Exception as e:
        result.error = str(e)
        print(f"    ERROR: {e}")

    finally:
        # Restore original settings
        settings.FUZZY_BACKTEST_ENABLED = orig_fuzzy_enabled
        settings.OPPORTUNITY_SCORING_METHOD = orig_opportunity_method

    return result


def run_all_tests():
    """Run all scenarios for all remaining coins."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    all_reports: List[CoinReport] = []
    all_results: List[TestResult] = []

    print("=" * 70)
    print("آرسان — تست چندکوینه‌ی کامل (AHPv2 vs Rules vs Baseline)")
    print(f"تاریخ: {datetime.now(timezone.utc).isoformat()}")
    print(f"کوین‌ها: {', '.join(REMAINING_COINS)}")
    print(f"بازه: {LOOKBACK_DAYS} روز | تایم‌فریم پایه: {BASE_TF}")
    print("=" * 70)

    for coin in REMAINING_COINS:
        print(f"\n{'='*70}")
        print(f"کوین: {coin.upper()}")
        print(f"{'='*70}")

        report = CoinReport(coin=coin)

        # 1. Baseline (no fuzzy)
        report.baseline = run_scenario(coin, "Baseline", use_fuzzy=False, use_ahp=False)
        all_results.append(report.baseline)
        time.sleep(2)

        # 2. Test B: Fuzzy + Rules
        report.fuzzy_rules = run_scenario(coin, "Fuzzy+Rules", use_fuzzy=True, use_ahp=False)
        all_results.append(report.fuzzy_rules)
        time.sleep(2)

        # 3. Test A v2: Fuzzy + AHPv2
        report.fuzzy_ahp = run_scenario(coin, "Fuzzy+AHPv2", use_fuzzy=True, use_ahp=True)
        all_results.append(report.fuzzy_ahp)
        time.sleep(2)

        all_reports.append(report)

    # Save JSON
    json_path = os.path.join(OUTPUT_DIR, "multi_coin_full_test.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "meta": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "coins": REMAINING_COINS,
                "lookback_days": LOOKBACK_DAYS,
                "base_timeframe": BASE_TF,
                "scenarios": ["Baseline", "Fuzzy+Rules", "Fuzzy+AHPv2"],
            },
            "results": [asdict(r) for r in all_results],
            "reports": [
                {
                    "coin": r.coin,
                    "baseline": asdict(r.baseline) if r.baseline else None,
                    "fuzzy_rules": asdict(r.fuzzy_rules) if r.fuzzy_rules else None,
                    "fuzzy_ahp": asdict(r.fuzzy_ahp) if r.fuzzy_ahp else None,
                }
                for r in all_reports
            ],
        }, f, ensure_ascii=False, indent=2)

    print(f"\n[OK] JSON saved: {json_path}")

    # Generate Markdown Report
    md_path = os.path.join(OUTPUT_DIR, "multi_coin_full_test.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# آرسان — گزارش تست چندکوینه‌ی کامل\n\n")
        f.write(f"**تاریخ:** {datetime.now(timezone.utc).isoformat()}\n\n")
        f.write(f"**بازه:** {LOOKBACK_DAYS} روز | **تایم‌فریم پایه:** {BASE_TF}\n\n")
        f.write(f"**کوین‌ها:** {', '.join(REMAINING_COINS)}\n\n")

        for report in all_reports:
            f.write(f"\n## {report.coin.upper()}\n\n")
            f.write("| معیار | Baseline | Fuzzy+Rules | Fuzzy+AHPv2 |\n")
            f.write("|-------|----------|-------------|-------------|\n")

            scenarios = [
                ("Baseline", report.baseline),
                ("Fuzzy+Rules", report.fuzzy_rules),
                ("Fuzzy+AHPv2", report.fuzzy_ahp),
            ]

            metrics = [
                ("PF", lambda r: r.profit_factor),
                ("Net Return %", lambda r: r.net_return_pct),
                ("MaxDD %", lambda r: r.max_drawdown_pct),
                ("Win Rate %", lambda r: r.win_rate),
                ("Trades", lambda r: r.total_trades),
                ("Avg Trade %", lambda r: r.avg_trade_pct),
                ("Fuzzy Steps", lambda r: r.fuzzy_steps),
                ("Fuzzy Overrides", lambda r: r.fuzzy_overrides),
                ("Opp Score Avg", lambda r: r.opportunity_score_avg),
            ]

            for metric_name, getter in metrics:
                vals = []
                for name, res in scenarios:
                    if res and not res.error:
                        v = getter(res)
                        vals.append(f"{v}" if v is not None else "-")
                    else:
                        vals.append("ERR" if res and res.error else "-")
                f.write(f"| **{metric_name}** | {' | '.join(vals)} |\n")

            for name, res in scenarios:
                if res and res.rejection_reasons:
                    f.write(f"\n**ردهای {name}:**\n")
                    for reason, count in sorted(res.rejection_reasons.items(), key=lambda x: -x[1]):
                        f.write(f"- {count}x {reason}\n")

        # Summary table
        f.write("\n---\n\n")
        f.write("## جدول خلاصه‌ی امتیازبندی\n\n")
        f.write("| کوین | بهترین PF | بهترین Net | بهترین MaxDD | ایمن‌تر | سودآورتر |\n")
        f.write("|------|-----------|------------|--------------|----------|----------|\n")

        for report in all_reports:
            scenarios_list = [
                ("Baseline", report.baseline),
                ("Fuzzy+Rules", report.fuzzy_rules),
                ("Fuzzy+AHPv2", report.fuzzy_ahp),
            ]
            valid = [(n, r) for n, r in scenarios_list if r and not r.error and r.total_trades > 0]

            if valid:
                best_pf = max(valid, key=lambda x: x[1].profit_factor if x[1].profit_factor is not None else -999)[0]
                best_net = max(valid, key=lambda x: x[1].net_return_pct if x[1].net_return_pct is not None else -999)[0]
                best_dd = min(valid, key=lambda x: abs(x[1].max_drawdown_pct) if x[1].max_drawdown_pct is not None else 999)[0]
                safest = best_dd
                most_profitable = best_net
            else:
                best_pf = best_net = best_dd = safest = most_profitable = "N/A"

            f.write(f"| {report.coin.upper()} | {best_pf} | {best_net} | {best_dd} | {safest} | {most_profitable} |\n")

    print(f"[OK] Markdown saved: {md_path}")
    print("\n" + "=" * 70)
    print("تست کامل شد! ✓")
    print(f"خروجی‌ها:\n  - {json_path}\n  - {md_path}")
    print("=" * 70)


if __name__ == "__main__":
    run_all_tests()
