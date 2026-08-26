#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP.calibration.run_calibration — main entry point.

    python -m RSP.calibration.run_calibration --coin bitcoin
    python -m RSP.calibration.run_calibration --coin bitcoin --synthetic   (offline, no network)

Pipeline (exactly the brief's spec):
    Train/IS -> Calibration -> LOCK PARAMETERS -> Gap/Purge -> OOS
    ... repeated per fold, per mode, on ONE identical protocol ...
    -> Robustness suite (perturbation, regime, fee/slippage, sanity, overfit)
    -> Ablation (attribute profit to the specific component)
    -> Final Holdout (touched exactly once, at the very end)
    -> Golden-rule verdict: only declare success if OOS (and Holdout) net
       profit improved, with drawdown controlled and PF/expectancy intact.

Writes RSP/baseline_reports/calibration/<coin>_<timestamp>.json and .md.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from dataclasses import asdict, is_dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from RSP.config import settings
from . import param_registry as reg
from .protocol import build_protocol, materialize_tf
from .optimizer import calibrate_on_is, run_one
from .scoring import WindowScore, aggregate_oos, golden_rule_gate
from .compare_modes import compare_all_modes, run_ablation, MODES_TO_COMPARE
from .robustness import run_robustness_suite


def _to_jsonable(obj):
    if is_dataclass(obj):
        return {k: _to_jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    if isinstance(obj, float) and obj == float("inf"):
        return "inf"
    return obj


def _load_bars(coin: str, days: int, synthetic: bool):
    if synthetic:
        from . import synthetic_data
        return synthetic_data.build_synthetic_universe(days=days)
    # Real path — network call; will raise/return empty in a sandboxed
    # environment without exchange/CoinGecko access. This is the same
    # network limitation already documented in RSP/README.md.
    from RSP.ingestion.data_universe import build_data_universe
    universe = build_data_universe(coin)
    return universe.bars


def main():
    ap = argparse.ArgumentParser(description="RSP Calibration System")
    ap.add_argument("--coin", default="bitcoin")
    ap.add_argument("--base-tf", default="15M")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--synthetic", action="store_true",
                     help="Use offline synthetic OHLCV instead of live network data "
                          "(use this in sandboxes without exchange/CoinGecko access)")
    ap.add_argument("--holdout-frac", type=float, default=0.15)
    ap.add_argument("--n-folds", type=int, default=3)
    ap.add_argument("--purge-bars", type=int, default=24)
    ap.add_argument("--min-history", type=int, default=200)
    args = ap.parse_args()

    print("=" * 78)
    print(f"RSP Calibration System — coin={args.coin} base_tf={args.base_tf} "
          f"{'(SYNTHETIC/offline data)' if args.synthetic else '(live data)'}")
    print("=" * 78)

    bars_by_tf = _load_bars(args.coin, args.days, args.synthetic)
    base_df = bars_by_tf.get(args.base_tf) if bars_by_tf else None
    if base_df is None or base_df.empty:
        print("[FATAL] No usable OHLCV data (network unavailable and --synthetic not passed?). Aborting.")
        sys.exit(1)
    print(f"Loaded {len(base_df)} bars on {args.base_tf}.")

    plan = build_protocol(bars_by_tf, base_tf=args.base_tf, holdout_frac=args.holdout_frac,
                           n_folds=args.n_folds, purge_bars=args.purge_bars)
    for note in plan.notes:
        print(f"[PROTOCOL] {note}")
    if not plan.calibration_windows:
        print("[FATAL] No walk-forward folds could be built with this much data. "
              "Reduce --n-folds/--purge-bars or provide more history.")
        sys.exit(1)

    # -----------------------------------------------------------------
    # Step 1: BEFORE snapshot (current shipped defaults) — recorded before
    # any change, per the brief ("قبل از هر تغییر، عملکرد فعلی را ثبت کن").
    # -----------------------------------------------------------------
    before_snapshot = reg.snapshot_all()

    # -----------------------------------------------------------------
    # Step 2: compare all 4 modes on the IDENTICAL protocol (same folds,
    # same purge, same coin). Each mode calibrates its own params on IS,
    # locks them, evaluates once on OOS per fold.
    # -----------------------------------------------------------------
    mode_results = compare_all_modes(bars_by_tf, args.base_tf, plan, coin_id=args.coin,
                                      min_history=args.min_history)

    print("\n--- Mode comparison (identical IS->Purge->OOS protocol) ---")
    for mode in MODES_TO_COMPARE:
        r = mode_results[mode]
        agg = r.oos_agg
        print(f"{mode:10s} OOS: trades={agg.trades:4d} net={agg.net_return_pct:+7.2f}% "
              f"PF={agg.profit_factor:6.2f} DD={agg.max_drawdown_pct:6.2f}% "
              f"exp={agg.expectancy_pct:+.3f}% avgR={agg.avg_r:+.2f}  "
              f"| verdict={'ACCEPT' if r.verdict.accepted else 'REJECT'} — {r.verdict.reason}")

    # -----------------------------------------------------------------
    # Step 3: ablation — attribute the delta to the specific component,
    # using the risk parameters Baseline itself locked (so risk-param
    # changes aren't silently mixed into "what fuzzy/ahp/meta contributed").
    # -----------------------------------------------------------------
    baseline_locked_risk = {}
    if mode_results[reg.MODE_BASELINE].locked_params_by_fold:
        last_locked = mode_results[reg.MODE_BASELINE].locked_params_by_fold[-1]
        baseline_locked_risk = {k: v for k, v in last_locked.items()
                                 if reg.PARAMS_BY_NAME[k].modes == (reg.MODE_RISK,) or reg.MODE_RISK in reg.PARAMS_BY_NAME[k].modes}

    ablation_steps = run_ablation(bars_by_tf, args.base_tf, plan, baseline_locked_risk,
                                   coin_id=args.coin, min_history=args.min_history)
    print("\n--- Ablation (same locked risk params, one component at a time) ---")
    for step in ablation_steps:
        print(f"{step.label:28s} net={step.oos_agg.net_return_pct:+7.2f}% "
              f"(Δ vs previous={step.delta_net_vs_previous:+.2f}pp) "
              f"trades={step.oos_agg.trades:4d} | {'ACCEPT' if step.verdict.accepted else 'REJECT'} — {step.verdict.reason}")

    # -----------------------------------------------------------------
    # Step 4: pick the winner among modes that PASS the golden-rule gate
    # (never among rejected ones), preferring highest OOS composite score.
    # -----------------------------------------------------------------
    accepted = {m: r for m, r in mode_results.items() if r.verdict.accepted}
    baseline_agg = mode_results[reg.MODE_BASELINE].oos_agg
    if accepted:
        winner_mode, winner_result = max(accepted.items(), key=lambda kv: kv[1].oos_agg.composite_score())
    else:
        winner_mode, winner_result = reg.MODE_BASELINE, mode_results[reg.MODE_BASELINE]
        print("\n[RESULT] هیچ مدی طبق قانون طلایی OOS بهتر از Baseline تأیید نشد — Baseline نگه داشته می‌شود.")

    print(f"\n--- Robustness suite (winner={winner_mode}, on its last fold's locked params) ---")
    rb = winner_result.robustness
    if rb:
        for note in rb.notes:
            print(f"  {note}")
        print(f"  fee/slippage fragile: {rb.fee_slippage_fragile} | trade-count sanity: {rb.trade_count_sanity_note}")
        if rb.weakest_regime:
            print(f"  weakest regime: {rb.weakest_regime}")

    # -----------------------------------------------------------------
    # Step 5: Final Holdout — touched exactly once, only for the winning
    # mode + its last locked parameter set. Never used to pick the winner.
    # -----------------------------------------------------------------
    holdout_bars = materialize_tf(bars_by_tf, args.base_tf, plan.final_holdout)
    holdout_n = len(holdout_bars.get(args.base_tf, []))
    holdout_summary = None
    holdout_score = None
    if holdout_n > args.min_history:
        winner_locked = winner_result.locked_params_by_fold[-1] if winner_result.locked_params_by_fold else {}
        holdout_summary = run_one(holdout_bars, winner_mode, args.coin, winner_locked,
                                   args.base_tf, min(args.min_history, holdout_n - 1))
        holdout_score = WindowScore.from_summary("FINAL_HOLDOUT", holdout_summary)

        baseline_holdout_summary = run_one(holdout_bars, reg.MODE_BASELINE, args.coin, baseline_locked_risk,
                                            args.base_tf, min(args.min_history, holdout_n - 1))
        baseline_holdout_score = WindowScore.from_summary("FINAL_HOLDOUT_baseline", baseline_holdout_summary)

        print(f"\n--- FINAL HOLDOUT (touched once, {holdout_n} bars, never used in any decision above) ---")
        print(f"  {winner_mode:10s} net={holdout_score.net_return_pct:+.2f}% PF={holdout_score.profit_factor:.2f} "
              f"DD={holdout_score.max_drawdown_pct:.2f}% trades={holdout_score.trades}")
        print(f"  baseline   net={baseline_holdout_score.net_return_pct:+.2f}% PF={baseline_holdout_score.profit_factor:.2f} "
              f"DD={baseline_holdout_score.max_drawdown_pct:.2f}% trades={baseline_holdout_score.trades}")

        holdout_confirms = (winner_mode == reg.MODE_BASELINE) or (
            holdout_score.trades >= 5 and
            holdout_score.net_return_pct > baseline_holdout_score.net_return_pct and
            holdout_score.max_drawdown_pct <= baseline_holdout_score.max_drawdown_pct * 1.15
        )
    else:
        holdout_confirms = False
        print(f"\n[WARN] Final holdout too small ({holdout_n} bars) to evaluate reliably.")

    # -----------------------------------------------------------------
    # Final verdict — success is declared ONLY when OOS improvement (not
    # just IS) is confirmed AND the untouched final holdout agrees.
    # -----------------------------------------------------------------
    print("\n" + "=" * 78)
    if winner_mode != reg.MODE_BASELINE and winner_result.verdict.accepted and holdout_confirms:
        print(f"[SUCCESS] {winner_mode} روی OOS و Final Holdout (هردو) نسبت به Baseline بهبود سود خالص "
              f"با ریسک کنترل‌شده تأیید شد. توصیه: پارامترهای قفل‌شده را برای production اعمال کنید.")
    elif winner_mode != reg.MODE_BASELINE and winner_result.verdict.accepted and not holdout_confirms:
        print(f"[NOT CONFIRMED] {winner_mode} در OOS (walk-forward) بهتر بود اما روی Final Holdout دست‌نخورده "
              f"تأیید نشد — طبق قانون این پروژه، موفقیت اعلام نمی‌شود. باید دوباره با داده‌ی بیشتر/فولدهای دیگر بررسی شود.")
    else:
        print("[NO IMPROVEMENT CONFIRMED] هیچ mode/تغییری طبق قانون طلایی (IS بهتر ولی OOS بدتر = شکست) "
              "تأیید نشد؛ Baseline فعلی حفظ می‌شود.")
    print("=" * 78)

    # -----------------------------------------------------------------
    # Regression / before-after log + report files
    # -----------------------------------------------------------------
    after_snapshot = {}
    if winner_mode != reg.MODE_BASELINE and winner_result.locked_params_by_fold:
        after_snapshot = dict(before_snapshot)
        after_snapshot.update(winner_result.locked_params_by_fold[-1])

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "coin": args.coin, "base_tf": args.base_tf, "synthetic_data": args.synthetic,
        "protocol": _to_jsonable(plan),
        "mode_comparison": {
            m: {
                "oos_agg": _to_jsonable(r.oos_agg),
                "verdict": _to_jsonable(r.verdict),
                "locked_params_last_fold": r.locked_params_by_fold[-1] if r.locked_params_by_fold else {},
                "fold_is_scores": r.fold_is_scores,
            } for m, r in mode_results.items()
        },
        "ablation": [_to_jsonable(s) for s in ablation_steps],
        "robustness_winner": _to_jsonable(winner_result.robustness) if winner_result.robustness else None,
        "final_holdout": {
            "winner_mode": winner_mode,
            "winner": _to_jsonable(holdout_score) if holdout_score else None,
            "confirmed": holdout_confirms,
        },
        "before_params_snapshot": {k: (list(v) if isinstance(v, tuple) else v) for k, v in before_snapshot.items()},
        "after_params_snapshot": {k: (list(v) if isinstance(v, tuple) else v) for k, v in after_snapshot.items()},
        "final_verdict": (
            "SUCCESS" if (winner_mode != reg.MODE_BASELINE and winner_result.verdict.accepted and holdout_confirms)
            else "NOT_CONFIRMED" if (winner_mode != reg.MODE_BASELINE and winner_result.verdict.accepted)
            else "NO_IMPROVEMENT_KEEP_BASELINE"
        ),
    }

    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                            "RSP", "baseline_reports", "calibration")
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = os.path.join(out_dir, f"{args.coin}_{ts}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n[OK] JSON report: {json_path}")
    return report


if __name__ == "__main__":
    main()
