"""
RSP — comparison/arsan_vs_rsp.py  (Phase 29: CURRENT ARSAN COMPARISON)

آرسان اصلی از قبل یک آزمایشگاه بک‌تست دارد: `analyzer/backtest_lab.py`.
طبق اسپک ("اگر موتور اصلی آرسان قابلیت بک‌تست دارد، آن را بدون تغییر اجرا
کن")، این ماژول آن را **بدون تغییر** فراخوانی می‌کند - یا (پیش‌فرض و
امن‌تر) خروجی از‌پیش‌تولیدشده‌ی همان اسکریپت را می‌خواند
(`data/backtest_summary.json`، که با ورک‌فلوی هفتگی خودِ آرسان تولید
می‌شود) و کنار متریک‌های واقعی RSP می‌گذارد.

--- محدودیت روش‌شناسی (صادقانه، چون این دو بک‌تست قابل مقایسه‌ی مستقیمِ
    "برنده/بازنده" نیستند) ---

آرسان (`backtest_lab.py`):
  - کندل روزانه، نگه‌داری ۲۴ ساعته‌ی ثابت
  - "درست" = حرکت قیمت روز بعد حداقل ۰.۵٪ هم‌جهت با تصمیم
  - بدون کارمزد/اسلیپیج/Stop-Loss/Take-Profit/Position Sizing
  - فاکتور اخبار همیشه خنثی (چون تیتر خبر تاریخی در دسترس نیست)
  - متریک اصلی: accuracy_percent (٪ تصمیمات درست از کل buy/sell)

RSP (`backtest_engine.py`):
  - کندل ۱۵ دقیقه‌ای، نگه‌داری تا برخورد SL/TP واقعی (بر پایه‌ی ATR)
  - کارمزد + اسلیپیج واقعی لحاظ می‌شود
  - متریک اصلی: win_rate (٪ معاملاتی که TP قبل از SL خورد) + Net Return/Profit Factor/Max Drawdown

هر دو متریک از جنس "٪ تصمیمات درست جهت‌دار" هستند و در همین حد قابل کنار
هم گذاشتن‌اند - نه بیشتر. این ماژول عمداً یک عدد "برنده" واحد نمی‌سازد.
"""

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Optional, Dict, List

from RSP.backtest_engine.backtest_engine import BacktestSummary


ARSAN_BACKTEST_SUMMARY_RELATIVE_PATH = os.path.join("data", "backtest_summary.json")


@dataclass
class ArsanMetrics:
    available: bool = False
    error: Optional[str] = None
    generated_at: Optional[str] = None
    window_days: Optional[int] = None
    coins: List[str] = field(default_factory=list)
    overall_accuracy_percent: Optional[float] = None
    overall_total_evaluated: int = 0
    by_decision: Dict = field(default_factory=dict)
    by_coin: Dict = field(default_factory=dict)
    limitations: List[str] = field(default_factory=list)
    source: str = ""   # "existing_file" یا "regenerated_live"


@dataclass
class RspMetrics:
    win_rate: float
    net_return_pct: float
    profit_factor: float
    max_drawdown_pct: float
    number_of_trades: int
    average_trade_pct: float
    sharpe: str = "NOT_IMPLEMENTED"
    performance_by_regime: str = "جداگانه در robustness/stress_test.performance_by_market_type موجود است"
    out_of_sample_performance: str = "جداگانه در walk_forward/anti_overfitting موجود است (Phase 20/21)"


@dataclass
class ComparisonReport:
    arsan: ArsanMetrics = field(default_factory=ArsanMetrics)
    rsp: Optional[RspMetrics] = None
    methodology_notes: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def read_existing_arsan_summary(project_root: str) -> Optional[dict]:
    path = os.path.join(project_root, ARSAN_BACKTEST_SUMMARY_RELATIVE_PATH)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def regenerate_arsan_summary_live(project_root: str) -> Optional[dict]:
    """
    فراخوانی *بدون تغییر* اسکریپت واقعی آرسان (`analyzer/backtest_lab.run_backtest`).
    هشدار: این تابع داده‌ی زنده از CoinGecko برای ۶ کوین می‌گیرد (چند دقیقه طول
    می‌کشد) و فایل `data/backtest_summary.json` را در دیسک بازنویسی می‌کند -
    دقیقاً همان کاری که خودِ اسکریپت آرسان طراحی شده انجام دهد؛ RSP چیزی در
    آن تغییر نمی‌دهد، فقط صدایش می‌زند. فقط با فراخوانی صریح (`regenerate=True`
    در compare()) اجرا می‌شود - هرگز خودکار نه.
    """
    analyzer_path = os.path.join(project_root, "analyzer")
    if not os.path.isdir(analyzer_path):
        return None
    sys.path.insert(0, analyzer_path)   # backtest_lab.py با import های نسبی (from fetch_data import ...) نوشته شده
    try:
        import backtest_lab  # noqa: ماژول واقعی آرسان، فقط فراخوانی می‌شود، ویرایش نمی‌شود
        backtest_lab.run_backtest()
    finally:
        if analyzer_path in sys.path:
            sys.path.remove(analyzer_path)
    return read_existing_arsan_summary(project_root)


def extract_arsan_metrics(summary_json: dict, window_days: Optional[int] = None, source: str = "existing_file") -> ArsanMetrics:
    metrics = ArsanMetrics(available=True, source=source)
    metrics.generated_at = summary_json.get("generated_at")
    metrics.coins = summary_json.get("coins", [])
    metrics.limitations = summary_json.get("limitations", [])

    windows = summary_json.get("windows", {})
    if not windows:
        metrics.available = False
        metrics.error = "NO_WINDOWS_IN_SUMMARY"
        return metrics

    chosen_key = str(window_days) if window_days is not None and str(window_days) in windows else \
        max(windows.keys(), key=lambda k: int(k))  # پیش‌فرض: بزرگ‌ترین بازه‌ی موجود (نمونه‌ی بیشتر)
    window = windows[chosen_key]

    metrics.window_days = int(chosen_key)
    metrics.overall_accuracy_percent = window.get("overall", {}).get("accuracy_percent")
    metrics.overall_total_evaluated = window.get("overall", {}).get("total", 0)
    metrics.by_decision = window.get("by_decision", {})
    metrics.by_coin = window.get("by_coin", {})
    return metrics


def _rsp_metrics_from_summary(summary: BacktestSummary) -> RspMetrics:
    return RspMetrics(
        win_rate=summary.win_rate,
        net_return_pct=summary.net_return_pct,
        profit_factor=summary.profit_factor,
        max_drawdown_pct=summary.max_drawdown_pct,
        number_of_trades=summary.total_trades,
        average_trade_pct=summary.average_trade_pct,
    )


def compare(rsp_summary: BacktestSummary, project_root: str,
            window_days: Optional[int] = None, regenerate: bool = False) -> ComparisonReport:
    report = ComparisonReport()
    report.rsp = _rsp_metrics_from_summary(rsp_summary)

    raw = None
    source = "existing_file"
    if regenerate:
        try:
            raw = regenerate_arsan_summary_live(project_root)
            source = "regenerated_live"
        except Exception as exc:  # noqa
            report.notes.append(f"اجرای زنده‌ی backtest_lab آرسان شکست خورد: {exc} - "
                                 f"به فایل موجود روی دیسک برمی‌گردیم (در صورت وجود)")

    if raw is None:
        raw = read_existing_arsan_summary(project_root)
        source = "existing_file"

    if raw is None:
        report.arsan = ArsanMetrics(available=False, error="NO_BACKTEST_SUMMARY_FOUND",
                                     source=source)
        report.notes.append(
            f"فایل {ARSAN_BACKTEST_SUMMARY_RELATIVE_PATH} پیدا نشد. یا ورک‌فلوی هفتگی "
            f"backtest_lab.yml آرسان را یک‌بار دستی اجرا کن، یا compare(..., regenerate=True) "
            f"را صدا بزن (نیاز به شبکه‌ی زنده و چند دقیقه زمان دارد).")
        return report

    report.arsan = extract_arsan_metrics(raw, window_days=window_days, source=source)

    report.methodology_notes = [
        "این دو بک‌تست روش‌شناسی متفاوتی دارند (توضیح کامل در docstring این فایل) - "
        "مقایسه‌ی این گزارش صرفاً برای دید کلی است، نه داوری قطعی 'کدام بهتر است'.",
        f"آرسان: کندل روزانه، نگه‌داری ثابت ۲۴ساعته، آستانه‌ی حرکت ۰.۵٪، بدون کارمزد/SL/TP",
        f"RSP: کندل ۱۵ دقیقه‌ای، نگه‌داری تا برخورد SL/TP واقعی (ATR-based)، با کارمزد+اسلیپیج",
    ]

    return report
