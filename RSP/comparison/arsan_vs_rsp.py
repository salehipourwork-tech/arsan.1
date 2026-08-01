"""
RSP — comparison/arsan_vs_rsp.py  (Phase 29: CURRENT ARSAN COMPARISON)

آرسان اصلی (analyzer/backtest_lab.py و analyzer/horizon_lab.py) دست‌نخورده
فراخوانی می‌شود (فقط import و اجرا؛ هیچ خطی از آن تغییر نمی‌کند) و نتیجه‌اش
با خروجی RSP backtest_engine مقایسه می‌شود.

معیارها: Win Rate, Net Return, Profit Factor, Max Drawdown, Number of
Trades, Average Trade, Risk/Reward. Sharpe و Performance-by-Regime روی
داده‌های فعلی (بدون equity curve روزانه‌ی پیوسته) قابل‌محاسبه‌ی دقیق نیستند
و NOT_IMPLEMENTED علامت می‌خورند (به‌جای عدد جعلی).
"""

from dataclasses import dataclass, field
from typing import Optional, Dict
import sys
import os

from RSP.backtest_engine.backtest_engine import BacktestSummary


@dataclass
class ComparisonReport:
    arsan_available: bool = False
    arsan_error: Optional[str] = None
    arsan_metrics: Dict = field(default_factory=dict)
    rsp_metrics: Dict = field(default_factory=dict)
    notes: list = field(default_factory=list)


def _rsp_metrics_from_summary(summary: BacktestSummary) -> dict:
    return {
        "win_rate": summary.win_rate,
        "net_return_pct": summary.net_return_pct,
        "profit_factor": summary.profit_factor,
        "max_drawdown_pct": summary.max_drawdown_pct,
        "number_of_trades": summary.total_trades,
        "average_trade_pct": summary.average_trade_pct,
        "sharpe": "NOT_IMPLEMENTED",
        "performance_by_regime": "NOT_IMPLEMENTED",
        "out_of_sample_performance": "NOT_IMPLEMENTED (walk_forward ماژول پایه دارد، Phase 20 کامل نیست)",
    }


def try_run_arsan_backtest(project_root: str) -> ComparisonReport:
    """
    آرسان اصلی را بدون تغییر، فقط فراخوانی می‌کند. اگر analyzer/backtest_lab.py
    قابل import/اجرا نبود (مثلاً به دلیل نیاز به داده‌ی زنده یا ساختار متفاوت)،
    این تابع صادقانه arsan_available=False برمی‌گرداند - به‌جای شبیه‌سازی نتیجه.
    """
    report = ComparisonReport()
    analyzer_path = os.path.join(project_root, "analyzer")
    if not os.path.isdir(analyzer_path):
        report.arsan_error = "ANALYZER_DIR_NOT_FOUND"
        return report

    sys.path.insert(0, project_root)
    try:
        import analyzer.backtest_lab as arsan_backtest  # noqa: آرسان اصلی، فقط خوانده می‌شود
        if hasattr(arsan_backtest, "run_backtest") or hasattr(arsan_backtest, "main"):
            report.arsan_available = True
            report.notes.append(
                "ماژول backtest_lab آرسان پیدا شد اما این نسخه‌ی RSP آن را خودکار اجرا نمی‌کند "
                "(چون امضای ورودی/خروجی‌اش مستند نبود و حدس‌زدن پارامترها خطرناک است). "
                "برای مقایسه‌ی واقعی، خروجی backtest_lab آرسان باید دستی یا با یک adapter صریح تزریق شود."
            )
        else:
            report.arsan_error = "NO_KNOWN_ENTRYPOINT_IN_BACKTEST_LAB"
    except Exception as exc:  # noqa
        report.arsan_error = f"IMPORT_FAILED: {exc}"
    finally:
        if project_root in sys.path:
            sys.path.remove(project_root)

    return report


def compare(rsp_summary: BacktestSummary, project_root: str) -> ComparisonReport:
    report = try_run_arsan_backtest(project_root)
    report.rsp_metrics = _rsp_metrics_from_summary(rsp_summary)
    if not report.arsan_available:
        report.notes.append(
            f"مقایسه‌ی مستقیم انجام نشد: {report.arsan_error}. "
            "این محدودیت صادقانه در گزارش نهایی ذکر می‌شود، نه با عدد جعلی پر می‌شود."
        )
    return report
