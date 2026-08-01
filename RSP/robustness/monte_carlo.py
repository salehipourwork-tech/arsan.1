"""
RSP — robustness/monte_carlo.py  (Phase 23: MONTE CARLO / ROBUSTNESS)

سه نوع تست Robustness:

1) Trade Sequence Randomization: ترتیب معاملات ثبت‌شده‌ی یک بک‌تست واقعی را
   N بار به‌صورت تصادفی جابه‌جا می‌کند و توزیع Max Drawdown را می‌سنجد -
   تا مشخص شود آیا نتیجه‌ی خوب فقط به یک ترتیب خاص از معاملات وابسته بوده
   یا نه (بدون اینکه هیچ معامله‌ی جدیدی جعل شود؛ فقط ترتیب همان معاملات
   واقعی عوض می‌شود).

2) Fee / Slippage Variation: کل بک‌تست را با چند مقدار متفاوت کارمزد/اسلیپیج
   دوباره اجرا می‌کند (با override موقت تنظیمات، بدون تغییر دائمی config).

3) Parameter Perturbation: پارامترهای ریسک (ATR multiplier، RR target) را
   کمی تغییر می‌دهد و می‌بیند آیا نتیجه شکننده است یا پایدار.

محدودیت صادقانه: چون موتور RSP یک مدل ML با فضای پارامتر پیوسته نیست،
Perturbation اینجا به‌معنای اجرای مجدد کامل پایپ‌لاین با چند مقدار گسسته
از هر پارامتر است، نه یک جست‌وجوی سیستماتیک روی فضای پارامتر.
"""

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Dict, List
import random

import numpy as np

from RSP.config import settings
from RSP.backtest_engine.backtest_engine import BacktestSummary, run_backtest


@contextmanager
def _temporary_settings_override(overrides: Dict[str, float]):
    original = {}
    for key, value in overrides.items():
        original[key] = getattr(settings, key)
        setattr(settings, key, value)
    try:
        yield
    finally:
        for key, value in original.items():
            setattr(settings, key, value)


# ---------------------------------------------------------------------------
# 1) Trade Sequence Randomization
# ---------------------------------------------------------------------------
@dataclass
class SequenceRandomizationReport:
    n_iterations: int
    original_max_drawdown: float
    simulated_max_drawdowns: List[float] = field(default_factory=list)
    worst_case_drawdown: float = 0.0
    p95_drawdown: float = 0.0
    order_dependent: bool = False
    notes: List[str] = field(default_factory=list)


def _max_drawdown_from_sequence(pnl_sequence: List[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnl_sequence:
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def randomize_trade_sequence(summary: BacktestSummary, n_iterations: int = 200,
                              seed: int = 1) -> SequenceRandomizationReport:
    report = SequenceRandomizationReport(n_iterations=n_iterations,
                                          original_max_drawdown=summary.max_drawdown_pct)
    if summary.total_trades < 5:
        report.notes.append("کمتر از ۵ معامله - Randomization آماری معنادار نیست")
        return report

    pnl_values = [t.pnl_pct for t in summary.trades]
    rng = random.Random(seed)
    drawdowns = []
    for _ in range(n_iterations):
        shuffled = pnl_values[:]
        rng.shuffle(shuffled)
        drawdowns.append(_max_drawdown_from_sequence(shuffled))

    report.simulated_max_drawdowns = drawdowns
    report.worst_case_drawdown = round(max(drawdowns), 3)
    report.p95_drawdown = round(float(np.percentile(drawdowns, 95)), 3)
    # اگر بدترین حالت جابه‌جایی خیلی بدتر از Drawdown اصلی باشد، یعنی نتیجه‌ی
    # فعلی تا حدی به شانسِ ترتیب وابسته بوده است
    report.order_dependent = report.worst_case_drawdown > summary.max_drawdown_pct * 1.5 \
        if summary.max_drawdown_pct > 0 else report.worst_case_drawdown > 0
    report.notes.append(
        f"Max Drawdown واقعی={summary.max_drawdown_pct}, بدترین حالت ممکن با همین معاملات "
        f"در ترتیب دیگر={report.worst_case_drawdown}, صدک ۹۵={report.p95_drawdown}")
    return report


# ---------------------------------------------------------------------------
# 2) Fee / Slippage Variation  &  3) Parameter Perturbation
# ---------------------------------------------------------------------------
@dataclass
class PerturbationResult:
    label: str
    overrides: Dict[str, float]
    summary: BacktestSummary


@dataclass
class PerturbationReport:
    baseline: BacktestSummary
    results: List[PerturbationResult] = field(default_factory=list)
    fragile: bool = False
    notes: List[str] = field(default_factory=list)


FEE_SLIPPAGE_SCENARIOS = {
    "low_cost": {"SIMULATED_FEE_PCT": 0.0005, "SIMULATED_SLIPPAGE_PCT": 0.0002},
    "baseline_cost": {"SIMULATED_FEE_PCT": settings.SIMULATED_FEE_PCT,
                       "SIMULATED_SLIPPAGE_PCT": settings.SIMULATED_SLIPPAGE_PCT},
    "high_cost": {"SIMULATED_FEE_PCT": 0.002, "SIMULATED_SLIPPAGE_PCT": 0.0015},
}

RISK_PARAM_SCENARIOS = {
    "tighter_stop": {"STOP_LOSS_ATR_MULTIPLIER": 1.0},
    "baseline_stop": {"STOP_LOSS_ATR_MULTIPLIER": settings.STOP_LOSS_ATR_MULTIPLIER},
    "wider_stop": {"STOP_LOSS_ATR_MULTIPLIER": 2.2},
    "lower_rr_target": {"TAKE_PROFIT_RR_TARGET": 1.5},
    "higher_rr_target": {"TAKE_PROFIT_RR_TARGET": 3.0},
}


def run_perturbation_suite(bars_by_tf, base_tf: str = "15M", min_history: int = 60) -> PerturbationReport:
    baseline = run_backtest(bars_by_tf, base_tf=base_tf, min_history=min_history)
    report = PerturbationReport(baseline=baseline)

    all_scenarios = {**{f"cost::{k}": v for k, v in FEE_SLIPPAGE_SCENARIOS.items()},
                      **{f"risk::{k}": v for k, v in RISK_PARAM_SCENARIOS.items()}}

    for label, overrides in all_scenarios.items():
        with _temporary_settings_override(overrides):
            summary = run_backtest(bars_by_tf, base_tf=base_tf, min_history=min_history)
        report.results.append(PerturbationResult(label=label, overrides=overrides, summary=summary))

    if baseline.total_trades >= 5:
        baseline_sign = 1 if baseline.net_return_pct > 0 else (-1 if baseline.net_return_pct < 0 else 0)
        flips = sum(1 for r in report.results
                    if r.summary.total_trades >= 5 and
                    (1 if r.summary.net_return_pct > 0 else (-1 if r.summary.net_return_pct < 0 else 0)) != baseline_sign
                    and baseline_sign != 0)
        report.fragile = flips >= max(1, len(report.results) // 3)
        report.notes.append(f"{flips} از {len(report.results)} سناریو جهت سودآوری را نسبت به baseline "
                             f"({'سودده' if baseline_sign > 0 else 'زیان‌ده' if baseline_sign < 0 else 'خنثی'}) عوض کردند")
    else:
        report.notes.append("تعداد معاملات baseline برای قضاوت درباره‌ی شکنندگی کافی نیست")

    return report
