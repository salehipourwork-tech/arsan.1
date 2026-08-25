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


# ---------------------------------------------------------------------------
# BUG FIX (this session): README.md's own top-level usage example, and
# rsp_diagnose.py (a real script shipped in this repo, not documentation-only)
# both do:
#
#     from RSP.self_evaluation.self_evaluation import evaluate_all, summarize
#     evals = evaluate_all(summary.trades)
#     print(summarize(evals))
#
# Neither `evaluate_all` nor `summarize` was ever defined anywhere in this
# module (only `evaluate_trade`, which returns an aggregate dict with a
# `results` list nested inside, not a bare list of per-trade results). That
# made rsp_diagnose.py fail with an ImportError before it could even run,
# and made the README's own example code non-functional if anyone followed
# it literally. `evaluate_all` returns exactly the `List[SelfEvaluationResult]`
# the README/rsp_diagnose.py code expects to zip against `summary.trades`;
# `summarize` returns the aggregate dict `evaluate_trade` used to return
# directly. Both are thin wrappers around the untouched `evaluate_trade`
# implementation above, so nothing about its logic or existing callers
# (backtest_engine.py) changes.
# ---------------------------------------------------------------------------

def evaluate_all(trades: List) -> List[SelfEvaluationResult]:
    """Per-trade self-evaluation list — see module docstring FIX note above."""
    return evaluate_trade(trades).get("results", [])


def summarize(evals: List[SelfEvaluationResult]) -> Dict:
    """Aggregate accuracy / should_not_rate over an evaluate_all() result."""
    total = len(evals)
    if total == 0:
        return {"total": 0, "accuracy": 0.0, "should_not_rate": 0.0}
    return {
        "total": total,
        "accuracy": round(sum(1 for r in evals if r.correct) / total, 4),
        "should_not_rate": round(sum(1 for r in evals if r.should_not_have_traded) / total, 4),
    }
