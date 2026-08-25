#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP — Multi-Coin Meta Test v3.1
- Meta-Controller multi-criteria (Net/PF/DD/WR)
- Auto-calibrate threshold per-coin based on ATR%
- Profitability bias
"""

import os
import sys
import json
import time
import pandas as pd
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
MIN_TRADES_FOR_VALID = 10

OLD_RR = 2.0
OLD_SL_MULT = 2.5
OLD_EXIT = "SL_FIRST"
OLD_OPP = 50.0

NEW_RR = 2.5
NEW_SL_MULT = 1.5
NEW_EXIT = "PROPORTIONAL"
NEW_OPP_BY_METHOD = dict(getattr(settings, "FUZZY_OPPORTUNITY_THRESHOLD_BY_METHOD",
    {"rules": 75.0, "ahp": 75.0}))

META_WEIGHTS = {"net": 0.35, "pf": 0.25, "dd": 0.25, "wr": 0.15}

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
    data_source: str = ""
    error: str = ""

    def is_valid(self) -> bool:
        return self.total_trades >= MIN_TRADES_FOR_VALID and not self.error

    def is_profitable(self) -> bool:
        return self.net_return_pct > 0 or self.profit_factor >= 1.0

    def composite_score(self) -> float:
        if not self.is_valid():
            return -999.0
        net_score = max(-50, min(50, self.net_return_pct)) + 50
        pf_score = min(100, self.profit_factor * 50)
        dd_score = max(0, 50 - self.max_drawdown_pct)
        wr_score = self.win_rate
        return (
            net_score * META_WEIGHTS["net"] +
            pf_score * META_WEIGHTS["pf"] +
            dd_score * META_WEIGHTS["dd"] +
            wr_score * META_WEIGHTS["wr"]
        )

def _apply_params(rr, sl_mult, exit_mode, opp_threshold, opp_by_method=None, method=None):
    settings.RR_TARGET = rr
    settings.SL_ATR_MULTIPLIER = sl_mult
    settings.CONSERVATIVE_SL_TP_SAME_CANDLE = exit_mode
    settings.MIN_OPPORTUNITY_SCORE_FOR_TRADE = opp_threshold
    settings.FUZZY_OPPORTUNITY_THRESHOLD = opp_threshold
    if opp_by_method is not None:
        # FIX v2.1: this used to overwrite the whole BY_METHOD dict with the
        # static, uncalibrated NEW_OPP_BY_METHOD values. backtest_engine.py's
        # threshold lookup checks BY_METHOD[method] *before* falling back to
        # MIN_OPPORTUNITY_SCORE_FOR_TRADE, and BY_METHOD always has the
        # active method's key present — so the per-coin calibrated threshold
        # (opp_threshold, e.g. 70 for low-volatility BTC) was silently never
        # applied; the gate always used the static 75 instead (confirmed by
        # the real BTC run: [CALIBRATE] printed threshold=70, but the trade
        # count matched a 75 gate). Now only the *active* method's entry is
        # overridden with the calibrated value; the other method's static
        # default is left alone.
        by_method = dict(opp_by_method)
        if method is not None:
            by_method[method] = opp_threshold
        settings.FUZZY_OPPORTUNITY_THRESHOLD_BY_METHOD = by_method

def _calibrate_threshold_for_coin(coin_id: str, bars: pd.DataFrame, method: str) -> float:
    if bars is None or len(bars) < 40:
        return NEW_OPP_BY_METHOD.get(method, 75.0)
    high_14 = bars['high'].rolling(14).max()
    low_14 = bars['low'].rolling(14).min()
    atr = high_14 - low_14
    atr_pct = (atr / bars['close']) * 100
    avg_atr_pct = atr_pct.iloc[20:40].mean()
    base = NEW_OPP_BY_METHOD.get(method, 75.0)
    if pd.notna(avg_atr_pct):
        if avg_atr_pct > 4.0:
            adjustment = 15
        elif avg_atr_pct > 3.0:
            adjustment = 10
        elif avg_atr_pct > 2.0:
            adjustment = 5
        elif avg_atr_pct < 0.8:
            adjustment = -5
        else:
            adjustment = 0
    else:
        adjustment = 0
    calibrated = base + adjustment
    calibrated = min(85, max(45, calibrated))
    print(f"    [CALIBRATE] {coin_id} | ATR%={avg_atr_pct:.2f} | "
          f"base={base:.0f} + adj={adjustment:+d} = threshold={calibrated:.0f}")
    return calibrated

def _detect_data_source(universe) -> str:
    sources = []
    for tf, df in universe.bars.items():
        if df is not None and not df.empty:
            source = getattr(df, 'attrs', {}).get('source', 'unknown')
            sources.append(f"{tf}:{source}")
    return " | ".join(sources) if sources else "unknown"

def run_scenario(coin: str, scenario_name: str, use_fuzzy: bool, use_ahp: bool, use_meta: bool = False) -> TestResult:
    result = TestResult(coin=coin, scenario=scenario_name)
    orig = {
        "fuzzy": settings.FUZZY_BACKTEST_ENABLED,
        "meta": getattr(settings, "META_CONTROLLER_ENABLED", False),
        "opp_method": getattr(settings, "OPPORTUNITY_SCORING_METHOD", "rules"),
        "rr": getattr(settings, "RR_TARGET", 2.5),
        "sl": getattr(settings, "SL_ATR_MULTIPLIER", 1.5),
        "exit": getattr(settings, "CONSERVATIVE_SL_TP_SAME_CANDLE", "PROPORTIONAL"),
        "opp": getattr(settings, "MIN_OPPORTUNITY_SCORE_FOR_TRADE", 75.0),
        "opp_by_method": dict(getattr(settings, "FUZZY_OPPORTUNITY_THRESHOLD_BY_METHOD", {})),
    }
    try:
        method = "ahp" if use_ahp else "rules"
        if scenario_name == "Baseline":
            _apply_params(OLD_RR, OLD_SL_MULT, OLD_EXIT, OLD_OPP)
        else:
            universe_preview = build_data_universe(coin, lookback_days=DAYS)
            base_preview = universe_preview.bars.get(BASE_TF)
            calibrated_opp = _calibrate_threshold_for_coin(coin, base_preview, method)
            # BUG FIX (this session): `method=method` was missing from this
            # call. _apply_params()'s own docstring/comment above (FIX v2.1)
            # explicitly describes overriding only the *active* method's
            # entry in FUZZY_OPPORTUNITY_THRESHOLD_BY_METHOD with the
            # per-coin calibrated_opp value — but without `method=method`
            # here, `_apply_params`'s `if method is not None:` guard never
            # fires, so that override never happened. The calibrated
            # threshold (correctly computed and printed by [CALIBRATE]
            # above) was silently discarded every single run, and
            # FUZZY_OPPORTUNITY_THRESHOLD_BY_METHOD was always reset to the
            # static default (75/75) instead — exactly the bug FIX v2.1
            # already fixed once, reintroduced by this one missing kwarg.
            _apply_params(NEW_RR, NEW_SL_MULT, NEW_EXIT, calibrated_opp,
                          opp_by_method=NEW_OPP_BY_METHOD, method=method)
        settings.FUZZY_BACKTEST_ENABLED = use_fuzzy
        # NEW: Meta-Adaptive scenario — turns on the per-bar adaptive
        # Rules/AHP blending (RSP/meta_controller) instead of a single
        # static method+threshold. This is a genuinely distinct decision
        # path (see decision_controller.py's _evaluate_via_meta_controller),
        # run here as its own scenario so it's compared on equal footing
        # against Baseline/Rules/AHPv2 rather than silently replacing any
        # of them.
        settings.META_CONTROLLER_ENABLED = use_meta
        settings.OPPORTUNITY_SCORING_METHOD = method if use_fuzzy else "rules"
        effective_opp = (NEW_OPP_BY_METHOD.get(method, 75.0) if use_fuzzy else OLD_OPP)
        print(f"\n>>> [{coin}] {scenario_name} — fuzzy={use_fuzzy}, ahp={use_ahp}, meta={use_meta}")
        print(f"    Params: RR={settings.RR_TARGET}, SL={settings.SL_ATR_MULTIPLIER}ATR, "
              f"Exit={settings.CONSERVATIVE_SL_TP_SAME_CANDLE}, Opp>={effective_opp} (method={method})")
        universe = build_data_universe(coin, lookback_days=DAYS)
        result.data_source = _detect_data_source(universe)
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
        print(f"    → trades={result.total_trades} WR={result.win_rate:.1f}% "
              f"Net={result.net_return_pct:+.2f}% PF={result.profit_factor:.3f} "
              f"MaxDD={result.max_drawdown_pct:.2f}% | score={result.composite_score():.1f}")
        # NEW (this session): opportunity_score_avg/min/max and
        # rejection_reasons were already being computed above into `result`
        # but never printed anywhere — only saved into the final JSON report
        # at the very end of the whole run. That's exactly the data needed
        # to tell "scores are just barely under threshold" (tunable) apart
        # from "scores are far below threshold" (something upstream is
        # broken) per scenario, and it was invisible on the console for the
        # entire multi-hour run. Print it live, per scenario, when fuzzy was
        # actually on for this run.
        if use_fuzzy and result.opportunity_score_avg is not None:
            print(f"    [FUZZY DIAG] opp_score avg={result.opportunity_score_avg:.1f} "
                  f"min={result.opportunity_score_min:.1f} max={result.opportunity_score_max:.1f} "
                  f"threshold={result.current_threshold} "
                  f"steps={result.fuzzy_steps} overrides={result.fuzzy_overrides}")
            if result.rejection_reasons:
                top = sorted(result.rejection_reasons.items(), key=lambda kv: -kv[1])[:5]
                print(f"    [FUZZY DIAG] top rejection reasons: {top}")
    except Exception as e:
        result.error = str(e)
        print(f"    ERROR: {e}")
    finally:
        settings.FUZZY_BACKTEST_ENABLED = orig["fuzzy"]
        settings.META_CONTROLLER_ENABLED = orig["meta"]
        settings.OPPORTUNITY_SCORING_METHOD = orig["opp_method"]
        settings.RR_TARGET = orig["rr"]
        settings.SL_ATR_MULTIPLIER = orig["sl"]
        settings.CONSERVATIVE_SL_TP_SAME_CANDLE = orig["exit"]
        settings.MIN_OPPORTUNITY_SCORE_FOR_TRADE = orig["opp"]
        settings.FUZZY_OPPORTUNITY_THRESHOLD = orig["opp"]
        if orig["opp_by_method"]:
            settings.FUZZY_OPPORTUNITY_THRESHOLD_BY_METHOD = orig["opp_by_method"]
    return result

def _select_meta(baseline: TestResult, rules: TestResult, ahp: TestResult, meta_adaptive: TestResult) -> tuple:
    """
    FIX v2.1: this used to only ever choose between the two FUZZY variants
    (Rules vs AHPv2) — Baseline (fuzzy OFF) was run and reported but never
    actually a candidate the meta-controller could pick. Now genuinely
    compares all candidates on the same Net/PF/DD/WR composite score, and
    can select Baseline (i.e. fuzzy OFF) as the winner.
    NEW: added Meta-Adaptive (the per-bar adaptive Rules/AHP blend via
    RSP/meta_controller) as a fourth candidate, on equal footing with the
    other three rather than silently replacing any of them.

    Selection order (unchanged philosophy, just extended to 4 candidates):
      1. Only candidates with >= MIN_TRADES_FOR_VALID trades are eligible.
      2. Among eligible candidates, prefer the ones that are profitable
         (net_return_pct > 0 or profit_factor >= 1.0) over ones that aren't.
      3. Within whichever pool that leaves, pick the highest composite_score.
      4. If nothing is eligible, fall back to Baseline (the simplest, best-
         understood scenario) rather than an untested fuzzy variant.
    """
    candidates = [(baseline, "Baseline"), (rules, "Rules"), (ahp, "AHPv2"), (meta_adaptive, "Meta-Adaptive")]
    eligible = [(r, name) for r, name in candidates if r.is_valid()]

    summary_line = (f"[Baseline: Net={baseline.net_return_pct:+.2f}%,PF={baseline.profit_factor:.2f},"
                     f"trades={baseline.total_trades}] [Rules: Net={rules.net_return_pct:+.2f}%,"
                     f"PF={rules.profit_factor:.2f},trades={rules.total_trades}] [AHPv2: Net="
                     f"{ahp.net_return_pct:+.2f}%,PF={ahp.profit_factor:.2f},trades={ahp.total_trades}] "
                     f"[Meta-Adaptive: Net={meta_adaptive.net_return_pct:+.2f}%,PF={meta_adaptive.profit_factor:.2f},"
                     f"trades={meta_adaptive.total_trades}]")

    if not eligible:
        return baseline, "Baseline", f"هیچ سناریویی به حداقل {MIN_TRADES_FOR_VALID} معامله نرسید؛ پیش‌فرض Baseline. {summary_line}"

    profitable = [(r, name) for r, name in eligible if r.is_profitable()]
    pool = profitable if profitable else eligible

    winner, winner_name = max(pool, key=lambda rn: rn[0].composite_score())
    pool_desc = "profitable" if profitable else "valid (none profitable)"
    reason = (f"{winner_name} انتخاب شد — بالاترین composite_score در بین سناریوهای {pool_desc} "
              f"(score={winner.composite_score():.1f}). {summary_line}")
    return winner, winner_name, reason

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
    meta_adaptive = run_scenario(coin, "Meta-Adaptive", use_fuzzy=True, use_ahp=False, use_meta=True)
    time.sleep(RATE_LIMIT_SECONDS)
    print(f"\n>>> [{coin}] Meta-Controller v3.2 (Baseline vs Rules vs AHPv2 vs Meta-Adaptive)")
    meta_result, meta_source, meta_reason = _select_meta(baseline, fuzzy_rules, fuzzy_ahp, meta_adaptive)
    print(f"    → Meta selected: {meta_source}")
    print(f"    → Reason: {meta_reason}")
    print(f"    → Meta Net={meta_result.net_return_pct:+.2f}% "
          f"PF={meta_result.profit_factor:.3f} "
          f"MaxDD={meta_result.max_drawdown_pct:.2f}%")
    return {
        "coin": coin,
        "baseline": asdict(baseline) if baseline else None,
        "fuzzy_rules": asdict(fuzzy_rules) if fuzzy_rules else None,
        "fuzzy_ahp": asdict(fuzzy_ahp) if fuzzy_ahp else None,
        "meta_adaptive": asdict(meta_adaptive) if meta_adaptive else None,
        "meta_controller": {
            **asdict(meta_result),
            "meta_source": meta_source,
            "meta_reason": meta_reason,
            "meta_selected": True,
        } if meta_result else None,
    }

def generate_markdown_report(all_results: list) -> str:
    lines = [
        "# Multi-Coin Meta Test Report v3.1",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        f"**Period:** {DAYS} days | **Timeframe:** {BASE_TF}",
        "**Baseline:** RR=2.0, SL=2.5ATR, SL_FIRST, Opp>=50",
        f"**Fuzzy+Rules:** RR=2.5, SL=1.5ATR, PROPORTIONAL, Opp>=75 (auto-calibrated ±15)",
        f"**Fuzzy+AHPv2:** RR=2.5, SL=1.5ATR, PROPORTIONAL, Opp>=75 (auto-calibrated ±15)",
        "**Meta-Adaptive:** same as Fuzzy+Rules params, but decision routed through "
        "RSP.meta_controller (per-bar adaptive Rules/AHP blend by market context)",
        f"**Meta Weights:** Net={META_WEIGHTS['net']*100:.0f}%, PF={META_WEIGHTS['pf']*100:.0f}%, "
        f"DD={META_WEIGHTS['dd']*100:.0f}%, WR={META_WEIGHTS['wr']*100:.0f}%",
        "",
        # BUG FIX (this session): pyflakes flagged `m` (meta_controller's own
        # net_return_pct) as computed-but-unused a few lines below. This
        # table header/row was missing the meta_controller column entirely -
        # a real gap in the report, not just dead code, since meta_controller
        # is the actual final routed decision the other columns (src/reason)
        # describe. Added it as its own column rather than dropping `m`.
        "| Coin | Baseline | Rules | AHPv2 | Meta-Adaptive | Meta-Controller | Winner | Winner Reason |",
        "|------|----------|-------|-------|----------------|------------------|--------|---------------|",
    ]
    for r in all_results:
        coin = r["coin"].upper()
        b = r["baseline"]["net_return_pct"] if r["baseline"] and not r["baseline"].get("error") else 0
        fr = r["fuzzy_rules"]["net_return_pct"] if r["fuzzy_rules"] and not r["fuzzy_rules"].get("error") else 0
        fa = r["fuzzy_ahp"]["net_return_pct"] if r["fuzzy_ahp"] and not r["fuzzy_ahp"].get("error") else 0
        ma = r["meta_adaptive"]["net_return_pct"] if r.get("meta_adaptive") and not r["meta_adaptive"].get("error") else 0
        m = r["meta_controller"]["net_return_pct"] if r["meta_controller"] else 0
        src = r["meta_controller"].get("meta_source", "-") if r["meta_controller"] else "-"
        reason = r["meta_controller"].get("meta_reason", "-") if r["meta_controller"] else "-"
        lines.append(f"| {coin} | {b:+.2f}% | {fr:+.2f}% | {fa:+.2f}% | {ma:+.2f}% | {m:+.2f}% | {src} | {reason} |")
    lines.extend(["", "## Detailed Results", ""])
    for r in all_results:
        lines.append(f"### {r['coin'].upper()}")
        for scenario in ["baseline", "fuzzy_rules", "fuzzy_ahp", "meta_adaptive", "meta_controller"]:
            s = r[scenario]
            if s and not s.get("error"):
                lines.append(
                    f"- **{scenario}:** Trades={s.get('total_trades',0)}, "
                    f"WR={s.get('win_rate',0):.1f}%, Net={s.get('net_return_pct',0):+.2f}%, "
                    f"PF={s.get('profit_factor',0):.3f}, MaxDD={s.get('max_drawdown_pct',0):.2f}%, "
                    f"Score={s.get('composite_score',0):.1f}"
                )
                if s.get('data_source'):
                    lines.append(f"  - Source: {s['data_source']}")
            elif s and s.get("error"):
                lines.append(f"- **{scenario}:** ERROR: {s.get('error')}")
        lines.append("")
    return "\n".join(lines)

def main():
    print("="*70)
    print("Arsan — Multi-Coin Meta Test v3.2 (Auto-Calibrate + Meta-Adaptive)")
    print(f"Date: {datetime.now(timezone.utc).isoformat()}")
    print(f"Coins: {', '.join(c['symbol'] for c in COINS)}")
    print("Baseline: RR=2.0 | SL=2.5ATR | SL_FIRST | Opp>=50")
    print(f"Fuzzy+Rules: RR=2.5 | SL=1.5ATR | PROPORTIONAL | Opp>=75 (auto ±15)")
    print(f"Fuzzy+AHPv2: RR=2.5 | SL=1.5ATR | PROPORTIONAL | Opp>=75 (auto ±15)")
    print(f"Meta-Adaptive: same params as Fuzzy+Rules, decision routed through "
          f"RSP.meta_controller (per-bar adaptive Rules/AHP blend)")
    print(f"Meta Weights: Net={META_WEIGHTS['net']*100:.0f}% | PF={META_WEIGHTS['pf']*100:.0f}% | "
          f"DD={META_WEIGHTS['dd']*100:.0f}% | WR={META_WEIGHTS['wr']*100:.0f}%")
    print("="*70)
    all_results = []
    for coin_dict in COINS:
        result = run_all_scenarios(coin_dict["id"])
        all_results.append(result)
    report_dir = os.path.join("RSP", "baseline_reports", "multi_coin_meta_v3")
    os.makedirs(report_dir, exist_ok=True)
    json_path = os.path.join(report_dir, "multi_coin_meta_test_v3.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({
            "meta": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "coins": [c["id"] for c in COINS],
                "baseline_params": {"RR": OLD_RR, "SL": OLD_SL_MULT, "EXIT": OLD_EXIT, "OPP": OLD_OPP},
                "fuzzy_params": {"RR": NEW_RR, "SL": NEW_SL_MULT, "EXIT": NEW_EXIT, "OPP_BY_METHOD": NEW_OPP_BY_METHOD},
                "meta_weights": META_WEIGHTS,
            },
            "results": all_results,
        }, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] JSON saved: {json_path}")
    md_path = os.path.join(report_dir, "multi_coin_meta_test_v3.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(generate_markdown_report(all_results))
    print(f"[OK] Markdown saved: {md_path}")
    print("\n" + "="*70)
    print("SUMMARY")
    print("="*70)
    print(f"{'Coin':<8} {'Baseline':>10} {'Rules':>10} {'AHPv2':>10} {'MetaAdapt':>10} {'Winner':>10} {'Source':>10}")
    print("-"*70)
    for r in all_results:
        coin = r["coin"].upper()
        b = r["baseline"]["net_return_pct"] if r["baseline"] and not r["baseline"].get("error") else 0
        fr = r["fuzzy_rules"]["net_return_pct"] if r["fuzzy_rules"] and not r["fuzzy_rules"].get("error") else 0
        fa = r["fuzzy_ahp"]["net_return_pct"] if r["fuzzy_ahp"] and not r["fuzzy_ahp"].get("error") else 0
        ma = r["meta_adaptive"]["net_return_pct"] if r.get("meta_adaptive") and not r["meta_adaptive"].get("error") else 0
        m = r["meta_controller"]["net_return_pct"] if r["meta_controller"] else 0
        src = r["meta_controller"].get("meta_source", "-") if r["meta_controller"] else "-"
        print(f"{coin:<8} {b:>+9.2f}% {fr:>+9.2f}% {fa:>+9.2f}% {ma:>+9.2f}% {m:>+9.2f}% {src:>10}")
    valid_metas = [r["meta_controller"] for r in all_results if r["meta_controller"]]
    if valid_metas:
        avg_meta = sum(m["net_return_pct"] for m in valid_metas) / len(valid_metas)
        profitable = sum(1 for m in valid_metas if m["net_return_pct"] > 0)
        print(f"\nAverage Meta Net: {avg_meta:+.2f}%")
        print(f"Profitable Coins: {profitable}/{len(valid_metas)}")

if __name__ == "__main__":
    main()
