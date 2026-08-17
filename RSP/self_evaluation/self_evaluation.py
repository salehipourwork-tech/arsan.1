"""
RSP — Self-Evaluation Engine v2.0
PATCH: Stricter should_not_have_traded logic
"""

from typing import List, Dict
from dataclasses import dataclass, field


@dataclass
class SelfEvaluationResult:
    correct: bool; should_not_have_traded: bool
    opposing_evidence: List[str]; supporting_evidence: List[str]
    net_score: float; notes: List[str] = field(default_factory=list)


def evaluate_trade(trades: List) -> Dict:
    results = []
    for trade in trades:
        if not hasattr(trade, 'notes'):
            continue

        supporting = [n for n in trade.notes if n.startswith("+")]
        opposing = [n for n in trade.notes if n.startswith("-")]
        conflicting = any(n.startswith("!") for n in trade.notes)
        net_score = getattr(trade, 'confidence', 50.0) / 100.0
        correct = trade.outcome == "WIN"

        # FIX v2.0: Stricter logic
        should_not = False
        if not correct:
            if len(opposing) >= len(supporting):
                should_not = True
            elif conflicting:
                should_not = True
            elif net_score < 0.30:
                should_not = True
            elif len(opposing) >= len(supporting) - 2:
                should_not = True

        results.append(SelfEvaluationResult(
            correct=correct, should_not_have_traded=should_not,
            opposing_evidence=opposing, supporting_evidence=supporting,
            net_score=net_score, notes=[f"evaluated:{trade.regime}"],
        ))

    total = len(results)
    if total == 0:
        return {"total": 0, "accuracy": 0.0, "should_not_rate": 0.0}

    return {
        "total": total,
        "accuracy": round(sum(1 for r in results if r.correct) / total, 4),
        "should_not_rate": round(sum(1 for r in results if r.should_not_have_traded) / total, 4),
        "results": results,
    }
