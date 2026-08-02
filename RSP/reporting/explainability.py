"""
RSP — reporting/explainability.py  (Phase 30: DECISION EXPLAINABILITY)

خروجی نهایی پایپ‌لاین را به یک گزارش انسانی و ساختاریافته تبدیل می‌کند -
دقیقاً فرمتی که در اسپک خواسته شده بود (DECISION / REASON / MISSING
CONFIRMATION / INVALIDATION) به‌علاوه‌ی موارد Phase 32 (Final Evaluation).
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ExplainabilityReport:
    decision: str
    confidence: float
    market_regime: str
    selected_strategy: Optional[str]
    entry: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    risk_reward: Optional[float]
    key_evidence: List[str] = field(default_factory=list)
    conflicts: List[str] = field(default_factory=list)
    missing_confirmations: List[str] = field(default_factory=list)
    invalidation_conditions: List[str] = field(default_factory=list)
    data_quality: str = ""
    trade_quality: Optional[float] = None
    data_sources: dict = field(default_factory=dict)

    def to_text(self) -> str:
        lines = []
        lines.append(f"DECISION: {self.decision}")
        lines.append("")
        lines.append("REASON:")
        for reason in self.key_evidence[:6]:
            lines.append(f"  - {reason}")
        if self.conflicts:
            lines.append("")
            lines.append("CONFLICTS:")
            for c in self.conflicts[:5]:
                lines.append(f"  - {c}")
        if self.missing_confirmations:
            lines.append("")
            lines.append("MISSING CONFIRMATIONS:")
            for m in self.missing_confirmations:
                lines.append(f"  - {m}")
        if self.invalidation_conditions:
            lines.append("")
            lines.append("INVALIDATION CONDITIONS:")
            for inv in self.invalidation_conditions:
                lines.append(f"  - {inv}")
        lines.append("")
        lines.append(f"MARKET REGIME: {self.market_regime}")
        lines.append(f"SELECTED STRATEGY: {self.selected_strategy or 'NONE'}")
        lines.append(f"CONFIDENCE: {self.confidence}")
        if self.trade_quality is not None:
            lines.append(f"TRADE QUALITY: {self.trade_quality}")
        if self.entry is not None:
            lines.append(f"ENTRY: {self.entry}  STOP LOSS: {self.stop_loss}  "
                          f"TAKE PROFIT: {self.take_profit}  RISK/REWARD: {self.risk_reward}")
        lines.append(f"DATA QUALITY: {self.data_quality}")
        if self.data_sources:
            src_str = ", ".join(f"{tf}={src}" for tf, src in self.data_sources.items())
            lines.append(f"DATA SOURCES: {src_str}")
        return "\n".join(lines)


def build_report(decision, confidence, regime, selection, risk_plan, trade_quality,
                  quality_report, data_sources: dict) -> ExplainabilityReport:
    return ExplainabilityReport(
        decision=decision.action,
        confidence=confidence.confidence,
        market_regime=regime.regime,
        selected_strategy=selection.selected.name if selection.selected else None,
        entry=risk_plan.entry if risk_plan else None,
        stop_loss=risk_plan.stop_loss if risk_plan else None,
        take_profit=risk_plan.take_profit if risk_plan else None,
        risk_reward=risk_plan.risk_reward if risk_plan else None,
        key_evidence=decision.why,
        conflicts=decision.why_not_opposite,
        missing_confirmations=decision.missing_confirmation,
        invalidation_conditions=decision.invalidation,
        data_quality=f"score={quality_report.quality_score}, ok={quality_report.quality_ok}, "
                      f"issues={quality_report.issues}",
        trade_quality=trade_quality.score if trade_quality else None,
        data_sources=data_sources,
    )
