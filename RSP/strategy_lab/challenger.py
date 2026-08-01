"""
RSP — strategy_lab/challenger.py  (Phase 28: CHALLENGER SYSTEM)

یک نسخه‌ی «چالش‌گر» (Challenger) با نسخه‌ی فعلی (Champion) رقابت می‌کند،
اما طبق تاکید صریح اسپک: برد در بک‌تست In-Sample کافی نیست - داوری فقط
بر اساس عملکرد Out-of-Sample (بخش Test در هر پنجره‌ی Walk Forward،
Phase 20) انجام می‌شود.

این ماژول به walk_forward.py و versioning.py وابسته است: هر نسخه را با
Walk Forward کامل اجرا می‌کند (نه یک بک‌تست تک‌مرحله‌ای) تا معیار مقایسه
واقعاً Out-of-Sample باشد، سپس فقط میانگین معیارهای بخش Test را می‌سنجد.
"""

from dataclasses import dataclass, field
from typing import List

from RSP.config import settings
from RSP.strategy_lab.versioning import ENGINE_VERSIONS
from RSP.walk_forward.walk_forward import run_walk_forward, WalkForwardReport


@dataclass
class ChallengerResult:
    champion_id: str
    challenger_id: str
    champion_oos_win_rate: float
    challenger_oos_win_rate: float
    champion_oos_net_return: float
    challenger_oos_net_return: float
    champion_windows: int
    challenger_windows: int
    winner: str            # champion_id | challenger_id | "TIE" | "INCONCLUSIVE"
    reason: str


def _run_version_walk_forward(version_id: str, bars_by_tf, base_tf="15M",
                               train_bars=300, validate_bars=100, test_bars=100,
                               step_bars=100, min_history=60) -> WalkForwardReport:
    version = ENGINE_VERSIONS[version_id]
    with settings.temporary_override(version.overrides):
        return run_walk_forward(bars_by_tf, base_tf=base_tf, train_bars=train_bars,
                                 validate_bars=validate_bars, test_bars=test_bars,
                                 step_bars=step_bars, min_history=min_history)


def run_challenge(champion_id: str, challenger_id: str, bars_by_tf, **wf_kwargs) -> ChallengerResult:
    champion_wf = _run_version_walk_forward(champion_id, bars_by_tf, **wf_kwargs)
    challenger_wf = _run_version_walk_forward(challenger_id, bars_by_tf, **wf_kwargs)

    min_windows_required = 3
    if len(champion_wf.windows) < min_windows_required or len(challenger_wf.windows) < min_windows_required:
        return ChallengerResult(
            champion_id=champion_id, challenger_id=challenger_id,
            champion_oos_win_rate=champion_wf.aggregate_test_win_rate,
            challenger_oos_win_rate=challenger_wf.aggregate_test_win_rate,
            champion_oos_net_return=champion_wf.aggregate_test_net_return,
            challenger_oos_net_return=challenger_wf.aggregate_test_net_return,
            champion_windows=len(champion_wf.windows), challenger_windows=len(challenger_wf.windows),
            winner="INCONCLUSIVE",
            reason=f"تعداد پنجره‌های Walk Forward کافی نیست (کمینه {min_windows_required} پنجره لازم است) "
                   f"- داده‌ی تاریخی بیشتری لازم است تا داوری معتبر باشد",
        )

    champ_return = champion_wf.aggregate_test_net_return
    chall_return = challenger_wf.aggregate_test_net_return

    # معیار اصلی داوری: بازده خالص Out-of-Sample. اگر خیلی نزدیک بودند (اختلاف
    # کمتر از ۱۰٪ نسبت به قدرمطلق بزرگ‌تر)، Win Rate به‌عنوان معیار دوم دخیل می‌شود.
    diff = abs(champ_return - chall_return)
    reference = max(abs(champ_return), abs(chall_return), 1e-9)
    close_call = diff / reference < 0.10

    if close_call:
        if challenger_wf.aggregate_test_win_rate > champion_wf.aggregate_test_win_rate:
            winner = challenger_id
            reason = "بازده خالص Out-of-Sample نزدیک بود؛ چالش‌گر بر اساس Win Rate بالاتر برنده شد"
        elif challenger_wf.aggregate_test_win_rate < champion_wf.aggregate_test_win_rate:
            winner = champion_id
            reason = "بازده خالص Out-of-Sample نزدیک بود؛ قهرمان بر اساس Win Rate بالاتر نگه داشته شد"
        else:
            winner = "TIE"
            reason = "بازده خالص و Win Rate هر دو تقریباً یکسان بودند - نمی‌توان برنده‌ی قاطع اعلام کرد"
    elif chall_return > champ_return:
        winner = challenger_id
        reason = f"چالش‌گر در بازده خالص Out-of-Sample برتری روشن داشت ({chall_return:+.2f}% در برابر {champ_return:+.2f}%)"
    else:
        winner = champion_id
        reason = f"قهرمان همچنان در بازده خالص Out-of-Sample برتر است ({champ_return:+.2f}% در برابر {chall_return:+.2f}%)"

    return ChallengerResult(
        champion_id=champion_id, challenger_id=challenger_id,
        champion_oos_win_rate=champion_wf.aggregate_test_win_rate,
        challenger_oos_win_rate=challenger_wf.aggregate_test_win_rate,
        champion_oos_net_return=champ_return,
        challenger_oos_net_return=chall_return,
        champion_windows=len(champion_wf.windows), challenger_windows=len(challenger_wf.windows),
        winner=winner, reason=reason,
    )
