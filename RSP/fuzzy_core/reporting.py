"""
RSP — fuzzy_core/reporting.py (Explainable Fuzzy Decision Report)

طبق الزامات پرامپت، برای هر تصمیم باید گزارش کامل تولید شود:
  - Decision
  - Confidence
  - تمام Quality Variables
  - Active Rules
  - Rejected Trade
  - Primary Reason
  - Firing Strengths
  - Conflict Resolution Details
"""
from typing import Dict, List, Optional

from RSP.fuzzy_core.decision_controller import FuzzyDecisionReport
from RSP.fuzzy_core.rule_base import get_rule_by_id


def generate_fuzzy_report(report: FuzzyDecisionReport, coin: str = "") -> str:
    """
    تولید گزارش انسانی و قابل تفسیر از تصمیم فازی.
    """
    lines = []
    lines.append("=" * 60)
    lines.append("FUZZY DECISION REPORT")
    if coin:
        lines.append(f"Coin: {coin.upper()}")
    lines.append("=" * 60)

    lines.append(f"
Decision:          {report.decision}")
    lines.append(f"Confidence:        {report.confidence:.4f}")
    lines.append(f"Opportunity Score: {report.opportunity_score:.2f}/100")
    lines.append(f"Rejected Trade:    {'YES' if report.rejected_trade else 'NO'}")
    lines.append(f"Primary Reason:    {report.primary_reason}")

    if report.hysteresis_applied:
        lines.append("Hysteresis:        APPLIED (decision locked)")
    if not report.stability_check_passed:
        lines.append("Stability Check:   FAILED")

    lines.append("
" + "-" * 40)
    lines.append("FUZZY QUALITY VARIABLES")
    lines.append("-" * 40)

    def _fmt_fuzzy(d: Dict[str, float]) -> str:
        if not d:
            return "N/A"
        # Show top 2 terms
        sorted_items = sorted(d.items(), key=lambda x: x[1], reverse=True)[:2]
        return ", ".join(f"{k}={v:.3f}" for k, v in sorted_items)

    lines.append(f"Trend Quality:       {_fmt_fuzzy(report.trend_quality)}")
    lines.append(f"Momentum Quality:    {_fmt_fuzzy(report.momentum_quality)}")
    lines.append(f"Entry Quality:       {_fmt_fuzzy(report.entry_quality)}")
    lines.append(f"Risk Quality:        {_fmt_fuzzy(report.risk_quality)}")
    lines.append(f"Volatility Quality:  {_fmt_fuzzy(report.volatility_quality)}")
    lines.append(f"Market Stability:    {_fmt_fuzzy(report.market_stability)}")
    lines.append(f"Signal Strength:     {_fmt_fuzzy(report.signal_strength)}")
    lines.append(f"Signal Confidence:   {_fmt_fuzzy(report.signal_confidence)}")
    lines.append(f"Contradiction Sev.:  {_fmt_fuzzy(report.contradiction_severity)}")
    lines.append(f"Opportunity Quality: {_fmt_fuzzy(report.opportunity_quality)}")

    lines.append("
" + "-" * 40)
    lines.append("ACTIVE RULES & FIRING STRENGTHS")
    lines.append("-" * 40)

    if report.fuzzy_inference and report.fuzzy_inference.rule_firing_strengths:
        # Sort by strength desc
        sorted_rules = sorted(
            report.fuzzy_inference.rule_firing_strengths.items(),
            key=lambda x: x[1], reverse=True,
        )
        for rid, strength in sorted_rules:
            rule = get_rule_by_id(rid)
            desc = rule.description if rule else "N/A"
            lines.append(f"  {rid}: firing={strength:.4f} -> singleton={rule.output_singleton if rule else 'N/A'} | {desc}")
    else:
        lines.append("  No active rules.")

    if report.fuzzy_inference and report.fuzzy_inference.conflict_report:
        cr = report.fuzzy_inference.conflict_report
        if cr.conflicting_rules:
            lines.append("
" + "-" * 40)
            lines.append("CONFLICT RESOLUTION (Phase 41)")
            lines.append("-" * 40)
            lines.append(f"Method:     {cr.method_used}")
            lines.append(f"Resolved:   {cr.resolved_score:.2f}")
            lines.append(f"Conflicts:  {', '.join(cr.conflicting_rules)}")
            if cr.winning_rule:
                lines.append(f"Winning:    {cr.winning_rule}")
            for note in cr.notes:
                lines.append(f"  -> {note}")

    if report.notes:
        lines.append("
" + "-" * 40)
        lines.append("SYSTEM NOTES")
        lines.append("-" * 40)
        for note in report.notes:
            lines.append(f"  • {note}")

    lines.append("
" + "=" * 60)
    return "\n".join(lines)


def generate_fuzzy_json(report: FuzzyDecisionReport) -> Dict:
    """
    خروجی JSON قابل consume توسط dashboard یا experiment_manager.
    """
    return {
        "decision": report.decision,
        "confidence": report.confidence,
        "opportunity_score": report.opportunity_score,
        "rejected_trade": report.rejected_trade,
        "primary_reason": report.primary_reason,
        "hysteresis_applied": report.hysteresis_applied,
        "stability_check_passed": report.stability_check_passed,
        "qualities": {
            "trend_quality": report.trend_quality,
            "momentum_quality": report.momentum_quality,
            "entry_quality": report.entry_quality,
            "risk_quality": report.risk_quality,
            "volatility_quality": report.volatility_quality,
            "market_stability": report.market_stability,
            "signal_strength": report.signal_strength,
            "signal_confidence": report.signal_confidence,
            "contradiction_severity": report.contradiction_severity,
            "opportunity_quality": report.opportunity_quality,
        },
        "active_rules": report.active_rules,
        "firing_strengths": report.fuzzy_inference.rule_firing_strengths if report.fuzzy_inference else {},
        "conflict_resolution": {
            "method": report.fuzzy_inference.conflict_report.method_used if report.fuzzy_inference and report.fuzzy_inference.conflict_report else None,
            "resolved_score": report.fuzzy_inference.conflict_report.resolved_score if report.fuzzy_inference and report.fuzzy_inference.conflict_report else None,
            "conflicting_rules": report.fuzzy_inference.conflict_report.conflicting_rules if report.fuzzy_inference and report.fuzzy_inference.conflict_report else [],
        },
        "notes": report.notes,
    }
