#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP.calibration.smoke_test

NOT a real calibration run. This exists to mechanically prove the whole
pipeline (protocol -> per-mode calibration -> lock -> OOS -> robustness ->
ablation -> final holdout -> report) executes end-to-end without crashing,
on a deliberately tiny synthetic slice and a trimmed parameter grid, so it
finishes in well under a minute instead of the minutes-to-hours a real
41-parameter x 4-mode x multi-fold search takes (run_backtest recomputes
indicators from scratch per bar - documented, pre-existing cost in
RSP/README.md's "Performance" note - so cost grows faster than linearly
with both bar count and number of grid points evaluated).

Run: python -m RSP.calibration.smoke_test
"""
import sys
import time

from . import param_registry as reg
from . import synthetic_data
from .protocol import build_protocol
from .compare_modes import compare_all_modes, run_ablation, MODES_TO_COMPARE


def _trim_grids(max_points=2):
    for p in reg.ALL_PARAMS:
        if len(p.calibration_grid) > max_points:
            p.calibration_grid = p.calibration_grid[:1] + p.calibration_grid[-1:]


def main():
    t0 = time.time()
    _trim_grids()
    # only keep a handful of params per mode for the smoke test (real runs
    # use the full registry via run_calibration.py)
    tiny_names = {"rr_target", "sl_atr_multiplier", "min_confidence_to_trade",
                  "opp_threshold_rules", "rule_output_offset", "ahp_weights",
                  "meta_trade_threshold", "meta_vol_defensive_pct"}
    for p in reg.ALL_PARAMS:
        if p.name not in tiny_names:
            p.calibration_grid = []  # empty grid -> optimizer skips it (no improvement possible)

    bars = synthetic_data.build_synthetic_universe(days=10)
    small_bars = {tf: df.iloc[:min(len(df), 900 if tf == "15M" else len(df))] for tf, df in bars.items()}

    plan = build_protocol(small_bars, base_tf="15M", holdout_frac=0.20, n_folds=1,
                           purge_bars=10, is_frac_per_fold=0.55, oos_frac_per_fold=0.20,
                           min_bars=300)
    print("protocol notes:", plan.notes)
    if not plan.calibration_windows:
        print("[SMOKE TEST FAILED] no folds built"); sys.exit(1)

    results = compare_all_modes(small_bars, "15M", plan, coin_id="smoketest", min_history=100)
    for mode in MODES_TO_COMPARE:
        r = results[mode]
        print(f"{mode:10s} OOS trades={r.oos_agg.trades} net={r.oos_agg.net_return_pct:+.2f}% "
              f"verdict={'ACCEPT' if r.verdict.accepted else 'REJECT'} :: {r.verdict.reason[:80]}")

    baseline_locked = results[reg.MODE_BASELINE].locked_params_by_fold[-1] if results[reg.MODE_BASELINE].locked_params_by_fold else {}
    steps = run_ablation(small_bars, "15M", plan, baseline_locked, coin_id="smoketest", min_history=100)
    for s in steps:
        print(f"ablation {s.label:24s} net={s.oos_agg.net_return_pct:+.2f}% "
              f"verdict={'ACCEPT' if s.verdict.accepted else 'REJECT'}")

    print(f"\n[SMOKE TEST OK] full pipeline ran end-to-end in {time.time()-t0:.1f}s "
          f"(tiny synthetic data + trimmed grids — not a real calibration result)")


if __name__ == "__main__":
    main()
