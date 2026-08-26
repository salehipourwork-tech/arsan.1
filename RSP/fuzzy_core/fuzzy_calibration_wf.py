#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP — Fuzzy Walk-Forward Calibrator (this session)

Answers one question honestly: is a candidate change to the fuzzy
membership functions / rule-output calibration / opportunity threshold
actually more profitable and more STABLE than the current Fuzzy+Rules
config — not just more accurate, not just a higher win rate, and not just
better on the exact window it was tuned on?

Method
------
1. Walk-forward split: each coin's base_tf bars are cut into N sequential
   folds. Fold i trains (calibration/candidate selection is *allowed* to
   look at) bars[0:train_end_i] and is scored out-of-sample on the
   strictly-later bars[train_end_i:test_end_i] it never saw. This is a
   walk-forward / anchored-expanding-window OOS test, not a single
   train/test split and not k-fold (which would leak future bars into
   training for a time series).
2. Candidate configs: small, explicit grid of membership-function
   breakpoint shifts + rule-output-singleton multiplier/offset + starting
   opportunity threshold (see CANDIDATE_PROFILES below). Each is applied
   via settings.temporary_override so nothing here mutates the shipped
   defaults directly - only main() decides, after seeing OOS results,
   whether to recommend copying a candidate's values into settings.py.
3. Scoring deliberately excludes win rate as a primary criterion (per this
   session's requirement) — composite score is Net Return / Profit Factor
   / Max Drawdown / Expectancy (avg pnl per trade) only. See
   composite_score() below for the exact weights.
4. Selection rule: a candidate is only accepted if its OOS composite score
   (averaged across folds) is >= the CURRENT config's OOS composite score.
   If a candidate wins in-sample but loses out-of-sample, it is REJECTED
   and reported as overfit — never silently adopted.
5. Also runs a "Fuzzy-OFF, same RR/SL/Exit" control per candidate/fold, to
   separate "the fuzzy filter itself helped" from "the RR/SL/Exit change
   that ships alongside every Fuzzy scenario in multi_coin_meta_test.py
   helped" — these are two different questions and conflating them makes
   any fuzzy-specific calibration conclusion unreliable.

This script does NOT call the network. Point it at bars you already have
(from build_data_universe, or your own cached/offline OHLCV) via
run_walk_forward_calibration(bars_by_tf, coin_id=...).
"""

import copy
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd

from ..config import settings
from ..backtest_engine.backtest_engine import run_backtest

BASE_TF = "15M"
N_FOLDS = 2               # anchored walk-forward folds (each fold = 3 backtest runs x N candidates - see run_walk_forward_calibration's runtime note)
MIN_TRAIN_FRAC = 0.45     # first fold's train window, as a fraction of total bars
FOLD_TEST_FRAC = 0.15     # each fold's OOS test window, as a fraction of total bars
MIN_TRADES_PER_FOLD = 5   # below this, a fold's score is treated as unreliable (not just 0)

# Composite score weights — Net/PF/DD/Expectancy only, no win-rate term.
SCORE_WEIGHTS = {"net": 0.35, "pf": 0.25, "dd": 0.20, "expectancy": 0.20}

RR = 2.5
SL_MULT = 1.5
EXIT_MODE = "PROPORTIONAL"

# ---------------------------------------------------------------------------
# Candidate calibration profiles
# ---------------------------------------------------------------------------
# "current" = whatever ships in settings.py right now (the post-AHP/Meta-fix
# baseline for this exercise) — always included, always the bar every other
# candidate has to clear OOS, never itself "rejected".
#
# The other candidates probe the two levers this session's request called
# out: (a) membership-function breakpoints (looser = easier to reach
# "strong"/"very_strong", tighter = harder) and (b) rule-output calibration
# (uniformly higher/lower singleton outputs) and (c) the starting
# opportunity threshold. Kept to a small, explicit, human-reviewable grid
# rather than a black-box optimizer — every candidate here is independently
# describable and its output auditable, which matters more than shaving a
# few more points of score off an unmonitored search.
CANDIDATE_PROFILES: List[Dict] = [
    {
        "name": "current",
        "desc": "Shipped defaults (post AHP/Meta scale fix, this session) - unchanged.",
        "overrides": {},
    },
    {
        "name": "mf_looser",
        "desc": "Membership breakpoints shifted down ~0.05-0.07 (easier to reach "
                "strong/very_strong) - tests whether the rule base is simply too "
                "strict to ever fire on realistic evidence strengths.",
        "overrides": {
            "FUZZY_MF_TREND": (0.15, 0.33, 0.58, 0.80),
            "FUZZY_MF_MOMENTUM": (0.18, 0.38, 0.63, 0.83),
            "FUZZY_MF_ENTRY": (0.15, 0.33, 0.58, 0.80),
            "FUZZY_MF_RISK": (0.18, 0.38, 0.63, 0.85),
        },
    },
    {
        "name": "mf_tighter",
        "desc": "Membership breakpoints shifted up ~0.05-0.07 (harder to reach "
                "strong/very_strong) - the opposite hypothesis: current rules fire "
                "too easily on mediocre setups and a stricter bar improves quality "
                "per trade even at lower trade count.",
        "overrides": {
            "FUZZY_MF_TREND": (0.25, 0.47, 0.72, 0.90),
            "FUZZY_MF_MOMENTUM": (0.30, 0.52, 0.77, 0.93),
            "FUZZY_MF_ENTRY": (0.25, 0.47, 0.72, 0.90),
            "FUZZY_MF_RISK": (0.30, 0.52, 0.77, 0.95),
        },
    },
    {
        "name": "rule_output_boost",
        "desc": "All 20 rule singleton outputs +8 (uniform), threshold unchanged - "
                "tests whether trades are being screened out only because the "
                "scoring is conservative, not because the underlying setups are bad.",
        "overrides": {"FUZZY_RULE_OUTPUT_MULTIPLIER": 1.0, "FUZZY_RULE_OUTPUT_OFFSET": 8.0},
    },
    {
        "name": "rule_output_trim",
        "desc": "All 20 rule singleton outputs -8 (uniform) - opposite hypothesis: "
                "current scoring is too generous and admits low-quality setups.",
        "overrides": {"FUZZY_RULE_OUTPUT_MULTIPLIER": 1.0, "FUZZY_RULE_OUTPUT_OFFSET": -8.0},
    },
    {
        "name": "threshold_down",
        "desc": "Starting rules threshold lowered 72->64 (more trades let through "
                "while the per-coin ATR/adaptive calibration from the previous fix "
                "still runs on top) - tests whether the *count* of trades, not the "
                "MFs/rules themselves, was the binding constraint.",
        "overrides": {"FUZZY_OPPORTUNITY_THRESHOLD_BY_METHOD": {"rules": 64.0, "ahp": 58.0}},
    },
]


@dataclass
class FoldResult:
    fold: int
    scope: str  # "IS" or "OOS"
    trades: int = 0
    net_return_pct: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    win_rate: float = 0.0
    expectancy_pct: float = 0.0  # avg pnl % per trade
    reliable: bool = True

    def composite_score(self) -> float:
        if self.trades == 0:
            return -999.0
        net_score = max(-50, min(50, self.net_return_pct)) + 50
        pf_score = 100.0 if self.profit_factor == float("inf") else min(100, self.profit_factor * 50)
        dd_score = max(0, 50 - self.max_drawdown_pct)
        # expectancy_pct is a per-trade % - typically small (-2..+2); scale
        # to a 0..100-ish band the same way net_score does, centered on 0.
        exp_score = max(-50, min(50, self.expectancy_pct * 20)) + 50
        score = (
            net_score * SCORE_WEIGHTS["net"] +
            pf_score * SCORE_WEIGHTS["pf"] +
            dd_score * SCORE_WEIGHTS["dd"] +
            exp_score * SCORE_WEIGHTS["expectancy"]
        )
        if not self.reliable:
            # Under MIN_TRADES_PER_FOLD - still computed (so it's visible),
            # but flagged so main() doesn't let a lucky/unlucky handful of
            # trades on a thin fold decide a candidate's fate on its own.
            score *= 0.5
        return score


def _summary_to_fold_result(summary, fold: int, scope: str) -> FoldResult:
    if summary.total_trades == 0:
        return FoldResult(fold=fold, scope=scope, trades=0, reliable=False)
    pf = summary.profit_factor
    return FoldResult(
        fold=fold, scope=scope, trades=summary.total_trades,
        net_return_pct=summary.net_return_pct,
        profit_factor=pf,
        max_drawdown_pct=summary.max_drawdown_pct,
        win_rate=summary.win_rate,
        expectancy_pct=summary.average_trade_pct,
        reliable=summary.total_trades >= MIN_TRADES_PER_FOLD,
    )


def walk_forward_splits(n_bars: int, n_folds: Optional[int] = None,
                        min_train_frac: Optional[float] = None,
                        test_frac: Optional[float] = None) -> List[Tuple[int, int, int]]:
    """
    Anchored expanding-window walk-forward splits.
    Returns [(train_start=0, train_end, test_end), ...] as bar INDICES into
    the base_tf dataframe. Fold i trains on [0, train_end_i) and is scored
    OOS on [train_end_i, test_end_i) - bars the candidate never saw.

    BUG FIX (this session): n_folds/min_train_frac/test_frac used to default
    to the *module-level* N_FOLDS/MIN_TRAIN_FRAC/FOLD_TEST_FRAC constants as
    Python default-argument values - which bind ONCE at function-definition
    time, not at call time. Setting `fuzzy_calibration_wf.N_FOLDS = 2` after
    import (as any caller wanting a faster/slower run would do) silently had
    no effect; the function kept using whatever N_FOLDS was at import time.
    Defaults are now looked up inside the function body instead, so runtime
    overrides of the module constants actually take effect.
    """
    n_folds = n_folds if n_folds is not None else N_FOLDS
    min_train_frac = min_train_frac if min_train_frac is not None else MIN_TRAIN_FRAC
    test_frac = test_frac if test_frac is not None else FOLD_TEST_FRAC
    splits = []
    train_end = int(n_bars * min_train_frac)
    step = int(n_bars * test_frac)
    for i in range(n_folds):
        test_end = min(n_bars, train_end + step)
        if test_end <= train_end:
            break
        splits.append((0, train_end, test_end))
        train_end = test_end
    return splits


def _sliced_bars(bars_by_tf: Dict[str, pd.DataFrame], base_tf: str,
                 start_ts, end_ts) -> Dict[str, pd.DataFrame]:
    """Slice every timeframe up to end_ts (exclusive), matching the same
    look-ahead-safe convention backtest_engine._known_slice already uses
    (index < ts, not <=)."""
    out = {}
    for tf, df in bars_by_tf.items():
        if df is None or df.empty:
            out[tf] = df
            continue
        sliced = df[(df.index >= start_ts) & (df.index < end_ts)] if start_ts is not None else df[df.index < end_ts]
        out[tf] = sliced
    return out


def _run_one(bars_slice: Dict[str, pd.DataFrame], coin_id: str, overrides: Dict,
            fuzzy_on: bool) -> "object":
    ov = dict(overrides)
    ov.update({
        "RR_TARGET": RR, "SL_ATR_MULTIPLIER": SL_MULT,
        "CONSERVATIVE_SL_TP_SAME_CANDLE": EXIT_MODE,
        "FUZZY_BACKTEST_ENABLED": fuzzy_on,
        "META_CONTROLLER_ENABLED": False,
        "OPPORTUNITY_SCORING_METHOD": "rules",
    })
    with settings.temporary_override(ov):
        return run_backtest(bars_slice, base_tf=BASE_TF, coin_id=coin_id)


def run_walk_forward_calibration(bars_by_tf: Dict[str, pd.DataFrame], coin_id: str,
                                 candidates: Optional[List[Dict]] = None,
                                 n_folds: Optional[int] = None) -> Dict:
    """
    Runs every candidate profile through every walk-forward fold (IS + OOS,
    plus a fuzzy-OFF control at the same RR/SL/Exit), and returns a
    dict with per-candidate fold results and the final accept/reject
    decision. Does not mutate settings.py - candidates only ever run under
    settings.temporary_override.

    Runtime note: each fold x candidate costs 3 full run_backtest() calls
    (IS, OOS, fuzzy-off control). With the default grid (6 candidates) and
    default N_FOLDS (2) on a real 90-day/15M coin, that's ~36 backtest runs
    per coin - budget real wall-clock time for this (minutes, not seconds)
    when running RSP/fuzzy_calibrate_and_compare.py across all 7 coins;
    consider passing a trimmed `candidates` list or n_folds=1 for a faster
    pass, then re-running the full grid on whichever coins look promising.
    """
    candidates = candidates if candidates is not None else CANDIDATE_PROFILES
    base_df = bars_by_tf.get(BASE_TF)
    if base_df is None or base_df.empty:
        return {"coin": coin_id, "error": "no_data"}

    splits = walk_forward_splits(len(base_df), n_folds=n_folds)
    if not splits:
        return {"coin": coin_id, "error": "insufficient_bars_for_walk_forward"}

    results = {"coin": coin_id, "folds": [], "candidates": {}}

    for fold_idx, (train_start, train_end, test_end) in enumerate(splits):
        train_end_ts = base_df.index[min(train_end, len(base_df) - 1)]
        test_end_ts = base_df.index[min(test_end, len(base_df) - 1)] if test_end < len(base_df) else base_df.index[-1] + pd.Timedelta(seconds=1)
        train_bars = _sliced_bars(bars_by_tf, BASE_TF, None, train_end_ts)
        test_bars = _sliced_bars(bars_by_tf, BASE_TF, train_end_ts, test_end_ts)
        results["folds"].append({
            "fold": fold_idx, "train_bars": len(train_bars.get(BASE_TF, [])),
            "test_bars": len(test_bars.get(BASE_TF, [])),
        })

        for cand in candidates:
            name = cand["name"]
            bucket = results["candidates"].setdefault(name, {
                "desc": cand["desc"], "IS": [], "OOS": [], "control_fuzzy_off_OOS": [],
            })

            is_summary = _run_one(train_bars, coin_id, cand["overrides"], fuzzy_on=True)
            oos_summary = _run_one(test_bars, coin_id, cand["overrides"], fuzzy_on=True)
            control_summary = _run_one(test_bars, coin_id, cand["overrides"], fuzzy_on=False)

            bucket["IS"].append(_summary_to_fold_result(is_summary, fold_idx, "IS"))
            bucket["OOS"].append(_summary_to_fold_result(oos_summary, fold_idx, "OOS"))
            bucket["control_fuzzy_off_OOS"].append(_summary_to_fold_result(control_summary, fold_idx, "OOS_no_fuzzy"))

    return _finalize(results)


def _avg_score(fold_results: List[FoldResult]) -> float:
    reliable = [f for f in fold_results if f.trades > 0]
    if not reliable:
        return -999.0
    return sum(f.composite_score() for f in reliable) / len(reliable)


def _avg_metric(fold_results: List[FoldResult], attr: str) -> float:
    vals = [getattr(f, attr) for f in fold_results if f.trades > 0]
    return sum(vals) / len(vals) if vals else 0.0


def _finalize(results: Dict) -> Dict:
    if "candidates" not in results or "current" not in results["candidates"]:
        results["decision"] = {"accepted": None, "reason": "no 'current' baseline candidate present"}
        return results

    current_oos_score = _avg_score(results["candidates"]["current"]["OOS"])
    ranking = []
    for name, bucket in results["candidates"].items():
        is_score = _avg_score(bucket["IS"])
        oos_score = _avg_score(bucket["OOS"])
        control_score = _avg_score(bucket["control_fuzzy_off_OOS"])
        gap = is_score - oos_score  # large positive gap = overfitting to the training window
        ranking.append({
            "name": name, "desc": bucket["desc"],
            "is_score": round(is_score, 2), "oos_score": round(oos_score, 2),
            "control_fuzzy_off_oos_score": round(control_score, 2),
            "overfit_gap_is_minus_oos": round(gap, 2),
            "oos_net_avg": round(_avg_metric(bucket["OOS"], "net_return_pct"), 2),
            "oos_pf_avg": round(_avg_metric(bucket["OOS"], "profit_factor"), 3),
            "oos_dd_avg": round(_avg_metric(bucket["OOS"], "max_drawdown_pct"), 2),
            "oos_expectancy_avg": round(_avg_metric(bucket["OOS"], "expectancy_pct"), 3),
            "oos_wr_avg": round(_avg_metric(bucket["OOS"], "win_rate"), 1),
            "oos_trades_total": sum(f.trades for f in bucket["OOS"]),
            "beats_current_oos": (name != "current") and (oos_score >= current_oos_score),
            "beats_fuzzy_off_control": oos_score >= control_score,
        })

    ranking.sort(key=lambda r: r["oos_score"], reverse=True)
    winner = ranking[0]
    if winner["name"] == "current" or not winner["beats_current_oos"]:
        decision = {
            "accepted": "current",
            "reason": (
                "No candidate beat 'current' out-of-sample - keeping the shipped "
                "calibration unchanged. (A candidate can look better in-sample and "
                "still be rejected here; that is the overfitting guard working as "
                "intended, not a bug.)"
            ),
        }
    else:
        decision = {
            "accepted": winner["name"],
            "reason": (
                f"'{winner['name']}' beat 'current' out-of-sample "
                f"(OOS score {winner['oos_score']} vs {round(current_oos_score, 2)}) "
                f"with an IS-OOS gap of {winner['overfit_gap_is_minus_oos']} "
                f"(smaller is better - a large gap here would mean it only looks "
                f"good on the training window)."
            ),
        }

    results["ranking"] = ranking
    results["decision"] = decision
    return results


def print_report(results: Dict) -> None:
    coin = results.get("coin", "?")
    if results.get("error"):
        print(f"[{coin}] walk-forward calibration skipped: {results['error']}")
        return
    print("=" * 100)
    print(f"Fuzzy Walk-Forward Calibration — {coin.upper()}  "
          f"({len(results.get('folds', []))} folds)")
    print("=" * 100)
    header = (f"{'candidate':<20}{'IS score':>10}{'OOS score':>11}{'ctrl(no-fz)':>13}"
              f"{'IS-OOS gap':>12}{'OOS Net%':>10}{'OOS PF':>9}{'OOS DD%':>9}"
              f"{'OOS Exp%':>10}{'OOS WR%':>9}{'OOS trades':>12}")
    print(header)
    print("-" * len(header))
    for r in results.get("ranking", []):
        flag = " <= WINNER" if results["decision"]["accepted"] == r["name"] else ""
        print(f"{r['name']:<20}{r['is_score']:>10.1f}{r['oos_score']:>11.1f}"
              f"{r['control_fuzzy_off_oos_score']:>13.1f}{r['overfit_gap_is_minus_oos']:>12.1f}"
              f"{r['oos_net_avg']:>10.2f}{r['oos_pf_avg']:>9.2f}{r['oos_dd_avg']:>9.2f}"
              f"{r['oos_expectancy_avg']:>10.3f}{r['oos_wr_avg']:>9.1f}{r['oos_trades_total']:>12d}{flag}")
    print("-" * len(header))
    print(f"DECISION: {results['decision']['accepted']} — {results['decision']['reason']}")
    print()
