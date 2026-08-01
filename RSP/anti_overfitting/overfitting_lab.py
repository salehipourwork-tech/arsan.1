"""
RSP — anti_overfitting/overfitting_lab.py  (Phase 21: ANTI OVERFITTING LAB)

مقایسه‌ی In-Sample (Validate) با Out-of-Sample (Test) در هر پنجره‌ی
Walk Forward. اگر افت عملکرد شدید باشد، OVERFITTING_WARNING صادر می‌شود.

معیار افت: هم Win Rate و هم Net Return per-trade با هم بررسی می‌شوند تا
یک معیار به‌تنهایی گمراه‌کننده نباشد (مثلاً Win Rate ثابت بماند ولی
سودآوری از بین برود).
"""

from dataclasses import dataclass, field
from typing import List

from RSP.walk_forward.walk_forward import WalkForwardReport, WalkForwardWindow

DEGRADATION_WARNING_THRESHOLD = 0.40   # افت بیش از ۴۰٪ در معیار => هشدار
DEGRADATION_SEVERE_THRESHOLD = 0.70    # افت بیش از ۷۰٪ => هشدار جدی


@dataclass
class WindowOverfittingCheck:
    window_index: int
    validate_win_rate: float
    test_win_rate: float
    validate_avg_trade_pct: float
    test_avg_trade_pct: float
    win_rate_degradation: float     # نسبت افت (۰..۱، منفی یعنی بهبود)
    return_degradation: float
    status: str                     # OK | OVERFITTING_WARNING | OVERFITTING_SEVERE | INSUFFICIENT_TRADES


@dataclass
class OverfittingReport:
    checks: List[WindowOverfittingCheck] = field(default_factory=list)
    overall_status: str = "UNKNOWN"
    windows_flagged: int = 0
    notes: List[str] = field(default_factory=list)


def _degradation(validate_val: float, test_val: float) -> float:
    if validate_val == 0:
        return 0.0 if test_val >= 0 else 1.0
    if validate_val < 0:
        # اگر حتی روی Validate هم منفی بود، معیار افت بی‌معنی است
        return 0.0
    return max(-1.0, min(1.0, (validate_val - test_val) / abs(validate_val)))


def _check_window(w: WalkForwardWindow) -> WindowOverfittingCheck:
    v, t = w.validate_summary, w.test_summary
    if v.total_trades < 3 or t.total_trades < 3:
        return WindowOverfittingCheck(
            window_index=w.window_index,
            validate_win_rate=v.win_rate, test_win_rate=t.win_rate,
            validate_avg_trade_pct=v.average_trade_pct, test_avg_trade_pct=t.average_trade_pct,
            win_rate_degradation=0.0, return_degradation=0.0,
            status="INSUFFICIENT_TRADES",
        )

    wr_deg = _degradation(v.win_rate, t.win_rate)
    ret_deg = _degradation(v.average_trade_pct, t.average_trade_pct)
    worst = max(wr_deg, ret_deg)

    if worst >= DEGRADATION_SEVERE_THRESHOLD:
        status = "OVERFITTING_SEVERE"
    elif worst >= DEGRADATION_WARNING_THRESHOLD:
        status = "OVERFITTING_WARNING"
    else:
        status = "OK"

    return WindowOverfittingCheck(
        window_index=w.window_index,
        validate_win_rate=v.win_rate, test_win_rate=t.win_rate,
        validate_avg_trade_pct=v.average_trade_pct, test_avg_trade_pct=t.average_trade_pct,
        win_rate_degradation=round(wr_deg, 3), return_degradation=round(ret_deg, 3),
        status=status,
    )


def run_overfitting_check(wf_report: WalkForwardReport) -> OverfittingReport:
    report = OverfittingReport()
    if not wf_report.windows:
        report.overall_status = "NO_DATA"
        report.notes.append("هیچ پنجره‌ی Walk Forward موجود نیست")
        return report

    for w in wf_report.windows:
        report.checks.append(_check_window(w))

    severe = sum(1 for c in report.checks if c.status == "OVERFITTING_SEVERE")
    warning = sum(1 for c in report.checks if c.status == "OVERFITTING_WARNING")
    ok = sum(1 for c in report.checks if c.status == "OK")
    insufficient = sum(1 for c in report.checks if c.status == "INSUFFICIENT_TRADES")

    report.windows_flagged = severe + warning

    if severe > 0:
        report.overall_status = "OVERFITTING_SEVERE"
    elif warning > len(report.checks) * 0.4:
        report.overall_status = "OVERFITTING_WARNING"
    elif ok == 0 and insufficient == len(report.checks):
        report.overall_status = "INSUFFICIENT_DATA"
    else:
        report.overall_status = "OK"

    report.notes.append(f"OK={ok}, WARNING={warning}, SEVERE={severe}, INSUFFICIENT_TRADES={insufficient} "
                         f"از {len(report.checks)} پنجره")
    report.notes.append("معیار: افت هم‌زمان Win Rate و میانگین سود هر معامله از Validate به Test بررسی می‌شود، "
                         "نه فقط یک متریک به‌تنهایی.")
    return report
