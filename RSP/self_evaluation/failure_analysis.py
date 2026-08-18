"""
RSP — self_evaluation/failure_analysis.py  (Phase 25: FAILURE ANALYSIS)

معاملات ناموفق را در دسته‌های خواسته‌شده در اسپک طبقه‌بندی می‌کند:
Bad Entry, Wrong Regime, False Breakout, Weak Momentum, Volume Failure,
Trend Reversal, Poor Risk/Reward, Signal Conflict, Data Problem.

یک معامله می‌تواند چند برچسب بگیرد (مثلاً هم Signal Conflict هم Bad
Entry). در پایان مشخص می‌کند موتور در کدام دسته بیشترین شکست را دارد.

FIX v2.1:
  - این فایل قبلاً `from RSP.backtest_engine.backtest_engine import
    BacktestTradeLog` را import می‌کرد در حالی که backtest_engine.py هم
    این فایل را (غیرمستقیم، از طریق analyze_failures) import می‌کند —
    یعنی import چرخه‌ای (circular import) که همیشه کرش می‌کرد. کلاس
    BacktestTradeLog هم اصلاً جایی تعریف نشده بود (TradeRecord بود).
  - TradeSelfEvaluation هم وجود نداشت؛ self_evaluation.py کلاسی به اسم
    SelfEvaluationResult دارد با فیلدهای متفاوت
    (entry_quality_flag/regime_misdiagnosis_suspected/... اصلاً روی آن
    تعریف نشده بودند).
  - analyze_failures قبلاً حتماً به evaluations از بیرون نیاز داشت؛ حالا
    اگر داده نشود خودش evaluate_trade() را صدا می‌زند (duck-typing، بدون
    وابستگی چرخه‌ای).
  - trade.timestamp وجود نداشت (TradeRecord.entry_timestamp است).
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from collections import Counter

from RSP.config import settings
from RSP.self_evaluation.self_evaluation import evaluate_trade, SelfEvaluationResult

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


def _classify_trade(trade, evaluation: SelfEvaluationResult) -> List[str]:
    """
    FIX v2.1: rewritten against the fields that actually exist on TradeRecord
    (backtest_engine.py) and SelfEvaluationResult (self_evaluation.py),
    instead of an imagined evidence_snapshot/evaluation-flag contract that
    was never produced anywhere. Some of the original categories
    (FALSE_BREAKOUT / WEAK_MOMENTUM / DATA_PROBLEM) can't be reliably
    derived from what's tracked today, so they're conservatively skipped
    instead of guessed — better UNEXPLAINED than a fabricated label.
    """
    categories = []

    if trade.trade_quality and trade.trade_quality < 50.0:
        categories.append("BAD_ENTRY")

    if evaluation.should_not_have_traded:
        categories.append("WRONG_REGIME")

    structure_event = (trade.notes and any("CHOCH" in n for n in trade.notes))
    if structure_event:
        categories.append("TREND_REVERSAL")

    if trade.risk_reward is not None and trade.risk_reward < settings.MIN_ACCEPTABLE_RISK_REWARD * 1.15:
        categories.append("POOR_RISK_REWARD")

    if len(evaluation.opposing_evidence) >= len(evaluation.supporting_evidence) and evaluation.opposing_evidence:
        categories.append("SIGNAL_CONFLICT")

    if not categories:
        categories.append("UNEXPLAINED")

    return categories


def analyze_failures(trades: List, evaluations: Optional[List[SelfEvaluationResult]] = None) -> FailureAnalysisReport:
    report = FailureAnalysisReport()

    if evaluations is None:
        evaluations = (evaluate_trade(trades) or {}).get("results", [])

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
        timestamp = str(getattr(trade, "entry_timestamp", getattr(trade, "timestamp", "")))
        report.records.append(FailureRecord(timestamp=timestamp, pnl_pct=trade.pnl_pct, categories=categories))
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
