"""
RSP — self_evaluation/self_evaluation.py  (Phase 24: SELF EVALUATION ENGINE)

بعد از هر معامله (از evidence_snapshot که backtest_engine ثبت کرده)،
تحلیل می‌کند: چرا درست شد؟ چرا اشتباه شد؟ کدام سیگنال گمراه‌کننده بود؟
کدام داده تأییدکننده بود؟ آیا Regime اشتباه تشخیص داده شد؟ آیا Entry بد
بود؟ آیا Risk Management ضعیف بود؟ آیا معامله نباید انجام می‌شد؟

این تحلیل صرفاً heuristic و بر پایه‌ی شواهدِ خودِ همان معامله است (نه یک
مدل یادگیری جداگانه) - یعنی «فهم» به‌معنای واقعی هوش مصنوعی نیست، بلکه
یک لایه‌ی توضیح‌دهنده‌ی قانون‌محور است. این محدودیت صادقانه اعلام می‌شود.
"""

from dataclasses import dataclass, field
from typing import List

from RSP.backtest_engine.backtest_engine import BacktestTradeLog


@dataclass
class TradeSelfEvaluation:
    timestamp: str
    outcome: str
    correct: bool
    likely_causes: List[str] = field(default_factory=list)
    misleading_signals: List[str] = field(default_factory=list)
    confirming_signals: List[str] = field(default_factory=list)
    regime_misdiagnosis_suspected: bool = False
    entry_quality_flag: str = "OK"        # OK | WEAK | RISKY
    risk_management_flag: str = "OK"      # OK | WEAK
    should_not_have_traded: bool = False


def evaluate_trade(trade: BacktestTradeLog) -> TradeSelfEvaluation:
    ev = trade.evidence_snapshot or {}
    correct = trade.outcome == "WIN"
    result = TradeSelfEvaluation(timestamp=trade.timestamp, outcome=trade.outcome, correct=correct)

    net_score = ev.get("net_score", 0.0)
    bullish = ev.get("bullish_evidence", [])
    bearish = ev.get("bearish_evidence", [])
    conflicting = ev.get("conflicting_evidence", [])
    divergences = ev.get("divergences", [])
    momentum_state = ev.get("momentum_state", "UNKNOWN")
    mtf_aligned = ev.get("mtf_aligned", True)
    atr_pct = ev.get("atr_pct", 0.0)

    supporting = bullish if trade.action == "BUY" else bearish
    opposing = bearish if trade.action == "BUY" else bullish
    result.confirming_signals = supporting[:3]
    result.misleading_signals = opposing[:3] if opposing else []

    if correct:
        result.likely_causes.append(f"شواهد {trade.action} ({len(supporting)} مورد) در جهت درست بودند")
        if momentum_state == "ACCELERATION":
            result.likely_causes.append("شتاب حجم/مومنتوم هم‌جهت با معامله بود - تاییدکننده")
        if mtf_aligned:
            result.likely_causes.append("تایم‌فریم‌ها هم‌جهت بودند - سیگنال ورود قابل‌اتکاتر بود")
    else:
        if opposing:
            result.likely_causes.append(f"شواهد مخالف ({len(opposing)} مورد) نادیده گرفته شدند و نهایتاً غالب شدند")
        if divergences:
            result.likely_causes.append(f"واگرایی از قبل هشدار داده بود: {divergences[0]}")
            result.misleading_signals.append("واگرایی نادیده گرفته شد")
        if momentum_state == "WEAKENING":
            result.likely_causes.append("مومنتوم در حال تضعیف بود اما معامله انجام شد")
        if conflicting:
            result.likely_causes.append("شواهد متناقض در زمان ورود وجود داشت ولی از آستانه‌ی CONFLICT رد نشد")
        if abs(net_score) < 0.3:
            result.likely_causes.append(f"net_score ({net_score:+.2f}) به‌اندازه‌ی کافی قوی نبود - ورود مرزی بود")
            result.entry_quality_flag = "WEAK"
        if not mtf_aligned:
            result.likely_causes.append("عدم هم‌جهتی کامل تایم‌فریم‌ها - Entry با ریسک بالاتر بود")
            result.entry_quality_flag = "RISKY"
        if atr_pct > 5.0:
            result.likely_causes.append(f"نوسان بازار بالا بود (ATR%={atr_pct:.1f}) - نوسان می‌تواند SL را زودتر از حد انتظار زده باشد")
            result.risk_management_flag = "WEAK"
        if not result.likely_causes:
            result.likely_causes.append("شکست بدون علامت هشدار قبلی در شواهد ثبت‌شده - ممکن است رویداد خارجی/غیرقابل‌پیش‌بینی بوده باشد")

    # آیا اصلاً نباید معامله می‌شد؟
    if not correct and (len(opposing) >= len(supporting) - 1 or conflicting or abs(net_score) < 0.25):
        result.should_not_have_traded = True

    result.regime_misdiagnosis_suspected = (not correct) and bool(divergences) and momentum_state == "WEAKENING"

    return result


def evaluate_all(trades: List[BacktestTradeLog]) -> List[TradeSelfEvaluation]:
    return [evaluate_trade(t) for t in trades]


def summarize(evaluations: List[TradeSelfEvaluation]) -> dict:
    if not evaluations:
        return {"notes": "هیچ معامله‌ای برای ارزیابی وجود ندارد"}
    losses = [e for e in evaluations if not e.correct]
    return {
        "total_evaluated": len(evaluations),
        "losses": len(losses),
        "should_not_have_traded_ratio": round(
            sum(1 for e in losses if e.should_not_have_traded) / len(losses), 3) if losses else 0.0,
        "weak_entry_ratio": round(sum(1 for e in losses if e.entry_quality_flag != "OK") / len(losses), 3) if losses else 0.0,
        "weak_risk_mgmt_ratio": round(sum(1 for e in losses if e.risk_management_flag != "OK") / len(losses), 3) if losses else 0.0,
        "regime_misdiagnosis_suspected_ratio": round(
            sum(1 for e in losses if e.regime_misdiagnosis_suspected) / len(losses), 3) if losses else 0.0,
    }
