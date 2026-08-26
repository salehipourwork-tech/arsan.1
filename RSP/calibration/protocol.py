#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP.calibration.protocol

Implements exactly the pipeline required by the brief:

    Train/IS -> Calibration -> LOCK PARAMETERS -> Gap/Purge -> OOS
    ... with a Final Holdout slice carved off BEFORE any of the above,
    and never touched until the very last reporting step.

This is new — RSP/walk_forward/walk_forward.py windows Train/Validate/Test
and reports both, but never locks a parameter set coming out of Train and
never reserves a completely untouched final holdout. This module wraps
that gap without modifying walk_forward.py.

Bar-index based (not calendar-based) so it works uniformly across coins
regardless of gaps in the source data.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import pandas as pd


@dataclass
class DataSplit:
    """One labelled bar-index slice of bars_by_tf."""
    label: str
    start_idx: int
    end_idx: int  # exclusive


@dataclass
class CalibrationProtocolPlan:
    base_tf: str
    total_bars: int
    final_holdout: DataSplit
    calibration_windows: List[Tuple[DataSplit, DataSplit]] = field(default_factory=list)
    # each tuple = (IS/calibration split, OOS split) for one walk-forward fold,
    # already gapped/purged, all strictly inside the pre-holdout region.
    purge_bars: int = 0
    notes: List[str] = field(default_factory=list)


def _slice_bars(bars_by_tf: Dict[str, pd.DataFrame], base_tf: str,
                 start_idx: int, end_idx: int) -> Dict[str, pd.DataFrame]:
    base_df = bars_by_tf[base_tf]
    n = len(base_df)
    start_idx = max(0, min(start_idx, n))
    end_idx = max(start_idx, min(end_idx, n))
    if start_idx >= n or start_idx == end_idx:
        return {tf: df.iloc[0:0] for tf, df in bars_by_tf.items()}
    start_ts = base_df.index[start_idx]
    end_ts = base_df.index[end_idx - 1]
    return {tf: df[(df.index >= start_ts) & (df.index <= end_ts)] for tf, df in bars_by_tf.items()}


def build_protocol(bars_by_tf: Dict[str, pd.DataFrame], base_tf: str = "15M",
                    holdout_frac: float = 0.15,
                    n_folds: int = 3,
                    is_frac_per_fold: float = 0.55,
                    oos_frac_per_fold: float = 0.20,
                    purge_bars: int = 24,
                    step_frac: Optional[float] = None,
                    min_bars: int = 400) -> CalibrationProtocolPlan:
    """
    1) Carve off the LAST `holdout_frac` of bars as the Final Holdout —
       reserved, never used in calibration_windows below, only touched by
       the very last "final holdout" evaluation step.
    2) Inside the remaining (pre-holdout) region, lay down `n_folds`
       anchored walk-forward folds. Each fold =
         [IS/Calibration window] -- purge_bars gap --> [OOS window]
       IS window grows (anchored/expanding) with each fold so later folds
       calibrate on more history, matching how the system would actually be
       recalibrated over time. Folds march forward by step_frac (defaults
       to oos_frac_per_fold, i.e. non-overlapping OOS windows).
    3) purge_bars sits strictly between IS and OOS in every fold so no
       indicator warm-up state or label leakage crosses the boundary —
       this is the "Gap/Purge" step the brief asks for explicitly.
    """
    base_df = bars_by_tf.get(base_tf)
    plan = CalibrationProtocolPlan(base_tf=base_tf, total_bars=0,
                                    final_holdout=DataSplit("FINAL_HOLDOUT", 0, 0),
                                    purge_bars=purge_bars)
    if base_df is None or base_df.empty:
        plan.notes.append("NO_BASE_DATA")
        return plan

    n = len(base_df)
    plan.total_bars = n
    if n < min_bars:
        plan.notes.append(f"داده ناکافی برای پروتکل کالیبراسیون کامل (نیاز: {min_bars}, موجود: {n})")
        return plan

    holdout_bars = max(1, int(n * holdout_frac))
    pre_holdout_end = n - holdout_bars
    plan.final_holdout = DataSplit("FINAL_HOLDOUT", pre_holdout_end, n)

    step = int(pre_holdout_end * (step_frac if step_frac is not None else oos_frac_per_fold))
    step = max(step, 1)

    is_bars_min = int(pre_holdout_end * is_frac_per_fold * 0.5)  # first fold uses at least half the target IS size
    oos_bars = max(1, int(pre_holdout_end * oos_frac_per_fold))

    fold = 0
    is_end = max(is_bars_min, int(pre_holdout_end * is_frac_per_fold))
    while fold < n_folds:
        oos_start = is_end + purge_bars
        oos_end = oos_start + oos_bars
        if oos_end > pre_holdout_end:
            break
        is_split = DataSplit(f"IS_fold{fold}", 0, is_end)          # anchored: always starts at 0
        oos_split = DataSplit(f"OOS_fold{fold}", oos_start, oos_end)
        plan.calibration_windows.append((is_split, oos_split))
        fold += 1
        is_end = oos_end + step  # next fold's IS absorbs this fold's OOS + a further step forward

    if not plan.calibration_windows:
        plan.notes.append("داده کافی برای حتی یک fold کامل IS->Purge->OOS نبود؛ holdout/purge/fold "
                           "پارامترها را کوچک‌تر کنید یا داده‌ی بیشتری بدهید")
    else:
        plan.notes.append(
            f"{len(plan.calibration_windows)} fold ساخته شد | purge={purge_bars} bar | "
            f"final holdout = آخرین {holdout_bars} bar ({holdout_frac:.0%}) — کاملاً دست‌نخورده تا گزارش نهایی")
    return plan


def materialize_tf(bars_by_tf: Dict[str, pd.DataFrame], base_tf: str, split: DataSplit) -> Dict[str, pd.DataFrame]:
    return _slice_bars(bars_by_tf, base_tf, split.start_idx, split.end_idx)
