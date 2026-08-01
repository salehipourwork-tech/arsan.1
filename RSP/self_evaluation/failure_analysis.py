"""
RSP — self_evaluation/failure_analysis.py  (Phase 25: FAILURE ANALYSIS)

معاملات ناموفق را در دسته‌های خواسته‌شده در اسپک طبقه‌بندی می‌کند:
Bad Entry, Wrong Regime, False Breakout, Weak Momentum, Volume Failure,
Trend Reversal, Poor Risk/Reward, Signal Conflict, Data Problem.

یک معامله می‌تواند چند برچسب بگیرد (مثلاً هم Signal Conflict هم Bad
Entry). در پایان مشخص می‌کند موتور در کدام دسته بیشترین شکست را دارد.

وابسته به self_evaluation.py (باید قبل از این روی معاملات اجرا شده باشد)
و evidence_snapshot که در backtest_engine ثبت می‌شود.
"""

from dataclasses import dataclass, field
from typing import List, Dict
from collections import Counter

from RSP.backtest_engine.backtest_engine import BacktestTradeLog
from RSP.self_evaluation.self_evaluation import TradeSelfEvaluation
from RSP.config import settings

FAILURE_CATEGORIES = [
    "BAD_ENTRY", "WRONG_REGIME", "FALSE_BREAKOUT", "WEAK_MOMENTUM",
    "VOLUME_FAILURE", "TREND_REVERSAL", "POOR_RISK_REWARD",
    "SIGNAL_CONFLICT", "DATA_PROBLEM", "UNEXPLAINED",
]


@dataclass
class FailureRecord:
    timestamp: str
    pnl_pct: float
    categories: List[str] = field(default_factory=list)


@dataclass
class FailureAnalysisReport:
    total_losses: int = 0
    records: List[FailureRecord] = field(default_factory=list)
    category_counts: Dict[str, int] = field(default_factory=dict)
    category_avg_pnl: Dict[str, float] = field(default_factory=dict)
    dominant_failure_mode: str = ""
    worst_regime: str = ""
    notes: List[str] = field(default_factory=list)


def _classify_trade(trade: BacktestTradeLog, evaluation: TradeSelfEvaluation) -> List[str]:
    ev = trade.evidence_snapshot or {}
    categories = []

    if evaluation.entry_quality_flag in ("WEAK", "RISKY"):
        categories.append("BAD_ENTRY")

    if evaluation.regime_misdiagnosis_suspected:
        categories.append("WRONG_REGIME")

    structure_event = ev.get("structure_event", "NONE")
    if trade.regime in ("BREAKOUT", "FAKE_BREAKOUT") and trade.bars_held <= 5:
        categories.append("FALSE_BREAKOUT")

    if ev.get("momentum_state") == "WEAKENING":
        categories.append("WEAK_MOMENTUM")

    supporting_had_volume = any("VOLUME" in s for s in evaluation.confirming_signals)
    opposing_had_volume = any("VOLUME" in s for s in evaluation.misleading_signals)
    if opposing_had_volume and not supporting_had_volume:
        categories.append("VOLUME_FAILURE")

    if structure_event in ("CHOCH_BULLISH", "CHOCH_BEARISH"):
        categories.append("TREND_REVERSAL")

    if trade.risk_reward is not None and trade.risk_reward < settings.MIN_ACCEPTABLE_RISK_REWARD * 1.15:
        categories.append("POOR_RISK_REWARD")

    if ev.get("conflicting_evidence"):
        categories.append("SIGNAL_CONFLICT")

    if ev.get("data_quality_score", 100) < 70:
        categories.append("DATA_PROBLEM")

    if not categories:
        categories.append("UNEXPLAINED")

    return categories


def analyze_failures(trades: List[BacktestTradeLog], evaluations: List[TradeSelfEvaluation]) -> FailureAnalysisReport:
    report = FailureAnalysisReport()
    loss_pairs = [(t, e) for t, e in zip(trades, evaluations) if t.outcome == "LOSS"]
    report.total_losses = len(loss_pairs)

    if not loss_pairs:
        report.notes.append("هیچ معامله‌ی زیان‌ده‌ای برای تحلیل وجود ندارد")
        return report

    counter = Counter()
    pnl_by_category: Dict[str, list] = {}
    regime_loss_counter = Counter()

    for trade, evaluation in loss_pairs:
        categories = _classify_trade(trade, evaluation)
        report.records.append(FailureRecord(timestamp=trade.timestamp, pnl_pct=trade.pnl_pct, categories=categories))
        for c in categories:
            counter[c] += 1
            pnl_by_category.setdefault(c, []).append(trade.pnl_pct)
        regime_loss_counter[trade.regime] += 1

    report.category_counts = dict(counter)
    report.category_avg_pnl = {c: round(sum(v) / len(v), 4) for c, v in pnl_by_category.items()}
    report.dominant_failure_mode = counter.most_common(1)[0][0] if counter else "UNKNOWN"
    report.worst_regime = regime_loss_counter.most_common(1)[0][0] if regime_loss_counter else "UNKNOWN"

    report.notes.append(f"غالب‌ترین الگوی شکست: {report.dominant_failure_mode} "
                         f"({counter[report.dominant_failure_mode]} از {report.total_losses} زیان)")
    report.notes.append(f"رژیمی که بیشترین زیان در آن رخ داده: {report.worst_regime}")
    return report
