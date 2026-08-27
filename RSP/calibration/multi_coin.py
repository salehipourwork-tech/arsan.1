#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP.calibration.multi_coin

Answers the question the brief explicitly asks for and the single-coin
run does NOT answer: "پارامترهایی که روی یک کوین Lock شدن، روی کوین‌های
دیگه هم واقعاً جواب می‌دن یا فقط به رفتار خاص همون کوین over-fit شدن؟"

This does NOT re-optimize anything per extra coin (that would just be
"calibrate separately on N coins", a different and legitimate thing you
can already do with --coin per run). Instead it takes the parameter set
that was already locked on the PRIMARY coin's IS data and evaluates it,
completely un-tuned, on each secondary coin's own OOS-equivalent slice
(same protocol: same holdout_frac/purge, built independently per coin
since each has its own price history/length). This is a strict
generalization test, not a second calibration.

Two outcomes get reported honestly, because they mean different things:
  - Holds up (net profit positive, DD controlled) on most coins
        -> the edge is likely structural (works across regimes/assets),
           safer to ship as one shared parameter set.
  - Only works on the primary coin
        -> the "improvement" measured in the single-coin run was likely
           overfit to that coin's specific price history, not the model.
           Recommendation in that case is per-coin calibration (run
           run_calibration.py separately per coin), NOT one shared
           locked set — and the single-coin OOS/Holdout numbers already
           produced should NOT be read as "the system got better",
           only as "it got better for BTC specifically".
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .protocol import build_protocol, materialize_tf
from .optimizer import run_one
from .scoring import WindowScore, aggregate_oos


@dataclass
class CoinGeneralizationResult:
    coin_id: str
    oos_agg: WindowScore
    holds_up: bool
    reason: str


@dataclass
class MultiCoinReport:
    primary_coin: str
    primary_oos_agg: WindowScore
    per_coin: List[CoinGeneralizationResult] = field(default_factory=list)
    generalizes: bool = False
    verdict_note: str = ""


def check_generalization(load_bars_fn, primary_coin: str, primary_locked_params: Dict,
                          primary_oos_agg: WindowScore, mode: str, other_coins: List[str],
                          base_tf: str = "15M", min_history: int = 200,
                          holdout_frac: float = 0.15, purge_bars: int = 24,
                          n_folds: int = 2, min_hold_up_ratio: float = 0.5) -> MultiCoinReport:
    """
    load_bars_fn(coin_id) -> Dict[tf, DataFrame], same loader signature
    run_calibration.py already uses (live or --synthetic).
    """
    report = MultiCoinReport(primary_coin=primary_coin, primary_oos_agg=primary_oos_agg)
    for coin in other_coins:
        try:
            bars = load_bars_fn(coin)
        except Exception as e:
            report.per_coin.append(CoinGeneralizationResult(
                coin, WindowScore(coin, 0, 0, 0, 0, 0, 0, 0, False), False,
                f"داده‌ی {coin} در دسترس نبود ({e})"))
            continue
        base_df = bars.get(base_tf) if bars else None
        if base_df is None or base_df.empty:
            report.per_coin.append(CoinGeneralizationResult(
                coin, WindowScore(coin, 0, 0, 0, 0, 0, 0, 0, False), False,
                f"داده‌ی {coin} خالی/ناکافی بود"))
            continue

        plan = build_protocol(bars, base_tf=base_tf, holdout_frac=holdout_frac,
                               n_folds=n_folds, purge_bars=purge_bars, min_bars=300)
        if not plan.calibration_windows:
            report.per_coin.append(CoinGeneralizationResult(
                coin, WindowScore(coin, 0, 0, 0, 0, 0, 0, 0, False), False,
                f"داده‌ی {coin} برای ساخت حتی یک fold کافی نبود"))
            continue

        oos_windows: List[WindowScore] = []
        for _is_split, oos_split in plan.calibration_windows:
            oos_bars = materialize_tf(bars, base_tf, oos_split)
            n_bars = len(oos_bars.get(base_tf, []))
            if n_bars < 5:
                continue
            oos_min_hist = min(min_history, max(3, n_bars - 1))
            # NOTE: primary_locked_params used AS-IS, completely un-tuned for
            # this coin — that is the entire point of this check.
            summary = run_one(oos_bars, mode, coin, primary_locked_params, base_tf, oos_min_hist)
            oos_windows.append(WindowScore.from_summary(f"{coin}_oos", summary))

        agg = aggregate_oos(oos_windows)
        holds_up = agg.trades >= 5 and agg.net_return_pct > 0 and agg.profit_factor >= 1.0
        reason = (f"Net={agg.net_return_pct:+.2f}% PF={agg.profit_factor:.2f} DD={agg.max_drawdown_pct:.1f}% "
                  f"trades={agg.trades}" if agg.trades else "بدون معامله در OOS این کوین")
        report.per_coin.append(CoinGeneralizationResult(coin, agg, holds_up, reason))

    evaluated = [r for r in report.per_coin if r.oos_agg.trades > 0]
    hold_ratio = (sum(1 for r in evaluated if r.holds_up) / len(evaluated)) if evaluated else 0.0
    report.generalizes = len(evaluated) > 0 and hold_ratio >= min_hold_up_ratio
    if not evaluated:
        report.verdict_note = "هیچ کوین دیگری قابل ارزیابی نبود — نتیجه‌ی تک‌کوینی را نمی‌توان تعمیم داد."
    elif report.generalizes:
        report.verdict_note = (f"پارامترهای Lock‌شده روی {primary_coin} در {hold_ratio:.0%} از "
                                f"{len(evaluated)} کوین دیگر هم مثبت بودند — احتمالاً edge ساختاری است.")
    else:
        report.verdict_note = (f"فقط {hold_ratio:.0%} از {len(evaluated)} کوین دیگر با همین پارامترها مثبت شدند — "
                                f"این بهبود احتمالاً به {primary_coin} over-fit است. توصیه: کالیبراسیون جداگانه "
                                f"per-coin (اجرای run_calibration.py با --coin مجزا برای هرکدام)، نه یک پارامتر مشترک.")
    return report
