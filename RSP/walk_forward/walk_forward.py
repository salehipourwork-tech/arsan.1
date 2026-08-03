"""
RSP — walk_forward/walk_forward.py  (Phase 20: WALK FORWARD)

پنجره‌ی زمانی به‌جلو حرکت می‌کند: Train -> Validate -> Test، سپس کل پنجره
یک گام جلو می‌رود و تکرار می‌شود. نتایج *همه‌ی* پنجره‌ها ذخیره می‌شود، نه
فقط میانگین‌شان - چون خود اسپک (Phase 21: Anti-Overfitting) به نتایج
تک‌تک پنجره‌ها برای مقایسه‌ی In-Sample vs Out-of-Sample نیاز دارد.

نکته‌ی مهم درباره‌ی «Train» در این نسخه: موتور RSP یک مدل قابل‌آموزش
(ML) ندارد که روی Train بخواهد Fit شود - منطق تصمیم‌گیری قانون‌محور
(rule-based) است. پس «Train» در این پیاده‌سازی به‌معنای «گرم‌کردن
اندیکاتورها» (min_history لازم برای EMA/ADX/ATR) است، و آنچه واقعاً
Walk Forward را معنادار می‌کند تفکیک Validate (برای انتخاب استراتژی
فعلاً استاتیک - جایی برای Hyperparameter tuning در آینده) از Test
(ارزیابی نهایی، دست‌نخورده) است. این محدودیت صادقانه اینجا مستند می‌شود.
"""

from dataclasses import dataclass, field
from typing import Dict, List
import pandas as pd

from RSP.backtest_engine.backtest_engine import run_backtest, BacktestSummary


@dataclass
class WalkForwardWindow:
    window_index: int
    train_start: str
    train_end: str
    validate_start: str
    validate_end: str
    test_start: str
    test_end: str
    validate_summary: BacktestSummary
    test_summary: BacktestSummary


@dataclass
class WalkForwardReport:
    windows: List[WalkForwardWindow] = field(default_factory=list)
    aggregate_test_win_rate: float = 0.0
    aggregate_test_net_return: float = 0.0
    aggregate_validate_win_rate: float = 0.0
    aggregate_validate_net_return: float = 0.0
    notes: List[str] = field(default_factory=list)


def _slice_by_index(bars_by_tf: Dict[str, pd.DataFrame], base_tf: str,
                     start_idx: int, end_idx: int) -> Dict[str, pd.DataFrame]:
    base_df = bars_by_tf[base_tf]
    if start_idx >= len(base_df) or end_idx > len(base_df):
        return {tf: pd.DataFrame() for tf in bars_by_tf}
    start_ts = base_df.index[start_idx]
    end_ts = base_df.index[min(end_idx, len(base_df) - 1)]
    return {tf: df[(df.index >= start_ts) & (df.index <= end_ts)] for tf, df in bars_by_tf.items()}


def run_walk_forward(bars_by_tf: Dict[str, pd.DataFrame], base_tf: str = "15M",
                      train_bars: int = 300, validate_bars: int = 100, test_bars: int = 100,
                      step_bars: int = 100, min_history: int = 60) -> WalkForwardReport:
    report = WalkForwardReport()
    base_df = bars_by_tf.get(base_tf)
    if base_df is None or base_df.empty:
        report.notes.append("NO_BASE_DATA")
        return report

    total_needed = train_bars + validate_bars + test_bars
    if len(base_df) < total_needed + min_history:
        report.notes.append(
            f"داده‌ی کافی برای حتی یک پنجره‌ی کامل نیست "
            f"(نیاز: {total_needed + min_history}, موجود: {len(base_df)})")
        return report

    window_index = 0
    pos = 0
    total_windows_estimate = max(1, (len(base_df) - total_needed) // step_bars + 1)
    while pos + total_needed <= len(base_df):
        train_start_idx = pos
        train_end_idx = pos + train_bars
        validate_start_idx = train_end_idx
        validate_end_idx = validate_start_idx + validate_bars
        test_start_idx = validate_end_idx
        test_end_idx = test_start_idx + test_bars

        # Validate: از ابتدای Train تا انتهای Validate. باید تصمیمات دقیقاً از مرز
        # Train/Validate شروع شوند، نه زودتر - وگرنه معاملات Train هم اشتباهی
        # جزو Validate شمرده می‌شوند. (فیکس: قبلاً min(min_history, train_bars-1)
        # بود که چون min_history پیش‌فرض=60 < train_bars=300 است، همیشه 60 انتخاب
        # می‌شد - یعنی تصمیمات از وسط Train شروع می‌شدند، نه از مرز Validate.
        # با max() درست می‌شود: هم حداقل گرم‌شدن اندیکاتورها تضمین می‌شود، هم
        # تصمیمات دقیقاً از مرز واقعی شروع می‌شوند.)
        validate_bars_by_tf = _slice_by_index(bars_by_tf, base_tf, train_start_idx, validate_end_idx)
        validate_summary = run_backtest(validate_bars_by_tf, base_tf=base_tf, min_history=max(min_history, train_bars))

        # Test: از ابتدای Train تا انتهای Test (Out-of-Sample واقعی فقط بخش Test است،
        # ولی برای گرم‌شدن اندیکاتورها به تاریخچه‌ی قبلش نیاز داریم - همان تاریخچه
        # دیده‌شده در Train/Validate است، نه داده‌ی جدید از آینده -> نشتی رخ نمی‌دهد
        # چون تصمیمات Test هنوز فقط به bar های <= لحظه‌ی خودشان دسترسی دارند).
        # همون فیکس بالا این‌جا هم لازم است: تصمیمات باید دقیقاً از مرز Test شروع
        # شوند (train_bars+validate_bars)، وگرنه معاملات Validate هم دوباره داخل
        # آمار Test شمرده می‌شوند (باگ قبلی دقیقاً همین بود).
        test_bars_by_tf = _slice_by_index(bars_by_tf, base_tf, train_start_idx, test_end_idx)
        full_test_summary = run_backtest(test_bars_by_tf, base_tf=base_tf,
                                          min_history=max(min_history, train_bars + validate_bars))

        window = WalkForwardWindow(
            window_index=window_index,
            train_start=str(base_df.index[train_start_idx]),
            train_end=str(base_df.index[min(train_end_idx, len(base_df) - 1)]),
            validate_start=str(base_df.index[validate_start_idx]),
            validate_end=str(base_df.index[min(validate_end_idx - 1, len(base_df) - 1)]),
            test_start=str(base_df.index[test_start_idx]),
            test_end=str(base_df.index[min(test_end_idx - 1, len(base_df) - 1)]),
            validate_summary=validate_summary,
            test_summary=full_test_summary,
        )
        report.windows.append(window)
        window_index += 1
        pos += step_bars

    if report.windows:
        n = len(report.windows)
        report.aggregate_test_win_rate = round(sum(w.test_summary.win_rate for w in report.windows) / n, 2)
        report.aggregate_test_net_return = round(sum(w.test_summary.net_return_pct for w in report.windows), 3)
        report.aggregate_validate_win_rate = round(sum(w.validate_summary.win_rate for w in report.windows) / n, 2)
        report.aggregate_validate_net_return = round(sum(w.validate_summary.net_return_pct for w in report.windows), 3)
    else:
        report.notes.append("هیچ پنجره‌ای اجرا نشد")

    report.notes.append(
        "محدودیت مستند: Train در این نسخه صرفاً گرم‌کردن اندیکاتورهاست (بدون Fit "
        "پارامتر)، چون موتور rule-based است نه ML. برای معنادار شدن کامل Walk "
        "Forward، وقتی Adaptive Weighting (Phase 13) در آینده حالت یادگیری واقعی "
        "پیدا کند، این پنجره‌بندی باید به تنظیم پارامتر روی Validate هم وصل شود.")

    return report
