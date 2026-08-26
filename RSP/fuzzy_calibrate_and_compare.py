#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP — Fuzzy Calibration + Comparison Runner (this session)

What this does, per coin:
  1. Walk-forward calibration search (RSP/fuzzy_core/fuzzy_calibration_wf.py)
     over a small, explicit grid of MF-breakpoint / rule-output / threshold
     candidates, scored on Net Return / Profit Factor / Max Drawdown /
     Expectancy (NOT win rate), with an out-of-sample rejection rule: a
     candidate that only looks better in-sample is rejected as overfit.
  2. A final, full-window comparison table: Baseline (fuzzy off, old
     RR/SL/Exit) vs Fuzzy-Previous (current shipped calibration) vs
     Fuzzy-Calibrated (whatever the walk-forward step accepted, or
     Fuzzy-Previous again if nothing beat it OOS).

Requires network (build_data_universe -> CoinGecko/exchanges) — run this
from an environment with real market access, not from an offline sandbox.
Prints a per-coin report and writes a combined JSON/Markdown report under
RSP/baseline_reports/fuzzy_calibration/.
"""
import os
import sys
import json
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from RSP.config import settings
from RSP.ingestion.data_universe import build_data_universe
from RSP.backtest_engine.backtest_engine import run_backtest
from RSP.fuzzy_core.fuzzy_calibration_wf import (
    run_walk_forward_calibration, print_report, CANDIDATE_PROFILES,
    RR, SL_MULT, EXIT_MODE, BASE_TF,
)

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
RATE_LIMIT_SECONDS = 2

OLD_RR, OLD_SL_MULT, OLD_EXIT = 2.0, 2.5, "SL_FIRST"


def _run_full_window(bars, coin_id: str, overrides: dict, fuzzy_on: bool, rr, sl, exit_mode):
    ov = dict(overrides)
    ov.update({
        "RR_TARGET": rr, "SL_ATR_MULTIPLIER": sl, "CONSERVATIVE_SL_TP_SAME_CANDLE": exit_mode,
        "FUZZY_BACKTEST_ENABLED": fuzzy_on, "META_CONTROLLER_ENABLED": False,
        "OPPORTUNITY_SCORING_METHOD": "rules",
    })
    with settings.temporary_override(ov):
        return run_backtest(bars, base_tf=BASE_TF, coin_id=coin_id)


def _summary_row(label, s):
    return (f"{label:<18} trades={s.total_trades:4d} WR={s.win_rate:5.1f}% "
            f"Net={s.net_return_pct:+7.2f}% PF={s.profit_factor:7.3f} "
            f"MaxDD={s.max_drawdown_pct:5.2f}% Expectancy={s.average_trade_pct:+6.3f}%")


def run_for_coin(coin_id: str) -> dict:
    print(f"\n{'#'*100}\n# {coin_id.upper()}\n{'#'*100}")
    universe = build_data_universe(coin_id, lookback_days=DAYS)
    bars = universe.bars
    if bars.get(BASE_TF) is None or bars[BASE_TF].empty:
        print(f"[{coin_id}] no data, skipping")
        return {"coin": coin_id, "error": "no_data"}

    # 1) Walk-forward calibration search
    wf = run_walk_forward_calibration(bars, coin_id)
    print_report(wf)

    accepted_name = wf.get("decision", {}).get("accepted", "current")
    accepted_overrides = {}
    for c in CANDIDATE_PROFILES:
        if c["name"] == accepted_name:
            accepted_overrides = c["overrides"]
            break

    # 2) Full-window final comparison: Baseline / Fuzzy-Previous / Fuzzy-Calibrated
    print(f"--- Full-window comparison ({coin_id}) ---")
    baseline = _run_full_window(bars, coin_id, {}, fuzzy_on=False, rr=OLD_RR, sl=OLD_SL_MULT, exit_mode=OLD_EXIT)
    print(_summary_row("Baseline", baseline))

    fuzzy_prev = _run_full_window(bars, coin_id, {}, fuzzy_on=True, rr=RR, sl=SL_MULT, exit_mode=EXIT_MODE)
    print(_summary_row("Fuzzy-Previous", fuzzy_prev))

    fuzzy_calibrated = _run_full_window(bars, coin_id, accepted_overrides, fuzzy_on=True, rr=RR, sl=SL_MULT, exit_mode=EXIT_MODE)
    label = "Fuzzy-Calibrated" if accepted_name != "current" else "Fuzzy-Calibrated(=Previous)"
    print(_summary_row(label, fuzzy_calibrated))

    # Fuzzy-only-effect control: same RR/SL/Exit as the fuzzy scenarios, but
    # fuzzy gate off — isolates how much of any Fuzzy-vs-Baseline gap is the
    # RR/SL/Exit change itself rather than the fuzzy filter.
    rr_sl_control = _run_full_window(bars, coin_id, {}, fuzzy_on=False, rr=RR, sl=SL_MULT, exit_mode=EXIT_MODE)
    print(_summary_row("(control) RR/SL only, fuzzy OFF", rr_sl_control))

    return {
        "coin": coin_id,
        "walk_forward": {k: v for k, v in wf.items() if k != "candidates"},  # candidates has non-JSON FoldResult objects
        "accepted_candidate": accepted_name,
        "full_window": {
            "baseline": vars(baseline) if not isinstance(baseline, dict) else baseline,
        },
    }


def main():
    print("=" * 100)
    print("Arsan — Fuzzy Walk-Forward Calibration + Comparison")
    print(f"Date: {datetime.now(timezone.utc).isoformat()}")
    print(f"Candidates: {[c['name'] for c in CANDIDATE_PROFILES]}")
    print("Scoring: Net Return / Profit Factor / Max Drawdown / Expectancy (NOT win rate)")
    print("Rejection rule: candidate must beat 'current' OUT-OF-SAMPLE, not just in-sample")
    print("=" * 100)

    all_results = []
    for c in COINS:
        try:
            all_results.append(run_for_coin(c["id"]))
        except Exception as e:
            print(f"[{c['id']}] ERROR: {e}")
            all_results.append({"coin": c["id"], "error": str(e)})
        time.sleep(RATE_LIMIT_SECONDS)

    report_dir = os.path.join("RSP", "baseline_reports", "fuzzy_calibration")
    os.makedirs(report_dir, exist_ok=True)
    out_path = os.path.join(report_dir, "fuzzy_calibration_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({"generated_at": datetime.now(timezone.utc).isoformat(),
                    "results": all_results}, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n[OK] JSON saved: {out_path}")


if __name__ == "__main__":
    main()
