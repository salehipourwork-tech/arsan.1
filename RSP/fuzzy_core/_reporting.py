"""
RSP — fuzzy_core/reporting.py (Explainable Fuzzy Decision Report)
No f-strings — only string concatenation to avoid syntax errors.
"""
from typing import Dict, List, Optional

from RSP.fuzzy_core.decision_controller import FuzzyDecisionReport
from RSP.fuzzy_core.rule_base import get_rule_by_id


def generate_fuzzy_report(report: FuzzyDecisionReport, coin: str = "") -> str:
    lines = []
    sep = "=" * 60
    lines.append(sep)
    lines.append("FUZZY DECISION REPORT")
    if coin:
        lines.append("Coin: " + coin.upper())
    lines.append(sep)
    lines.append("")
    lines.append("Decision:          " + str(report.decision))
    lines.append("Confidence:        " + str(round(report.confidence, 4)))
    lines.append("Opportunity Score: " + str(round(report.opportunity_score, 2)) + "/100")
    lines.append("Rejected Trade:    " + ("YES" if report.rejected_trade else "NO"))
    lines.append("Primary Reason:    " + str(report.primary_reason))

    if report.hysteresis_applied:
        lines.append("Hysteresis:        APPLIED (decision locked)")
    if not report.stability_check_passed:
        lines.append("Stability Check:   FAILED")

    lines.append("")
    lines.append("-" * 40)
    lines.append("FUZZY QUALITY VARIABLES")
    lines.append("-" * 40)

    def _fmt_fuzzy(d):
        if not d:
            return "N/A"
        items = sorted(d.items(), key=lambda x: x[1], reverse=True)[:2]
        return ", ".join(k + "=" + str(round(v, 3)) for k, v in items)

    lines.append("Trend Quality:       " + _fmt_fuzzy(report.trend_quality))
    lines.append("Momentum Quality:    " + _fmt_fuzzy(report.momentum_quality))
    lines.append("Entry Quality:       " + _fmt_fuzzy(report.entry_quality))
    lines.append("Risk Quality:        " + _fmt_fuzzy(report.risk_quality))
    lines.append("Volatility Quality:  " + _fmt_fuzzy(report.volatility_quality))
    lines.append("Market Stability:    " + _fmt_fuzzy(report.market_stability))
    lines.append("Signal Strength:     " + _fmt_fuzzy(report.signal_strength))
    lines.append("Signal Confidence:   " + _fmt_fuzzy(report.signal_confidence))
    lines.append("Contradiction Sev.:  " + _fmt_fuzzy(report.contradiction_severity))
    lines.append("Opportunity Quality: " + _fmt_fuzzy(report.opportunity_quality))

    lines.append("")
    lines.append("-" * 40)
    lines.append("ACTIVE RULES & FIRING STRENGTHS")
    lines.append("-" * 40)

    if report.fuzzy_inference and report.fuzzy_inference.rule_firing_strengths:
        sorted_rules = sorted(
            report.fuzzy_inference.rule_firing_strengths.items(),
            key=lambda x: x[1], reverse=True,
        )
        for rid, strength in sorted_rules:
            rule = get_rule_by_id(rid)
            desc = rule.description if rule else "N/A"
            out = "  " + rid + ": firing=" + str(round(strength, 4))
            if rule:
                out += " -> singleton=" + str(rule.output_singleton)
            out += " | " + desc
            lines.append(out)
    else:
        lines.append("  No active rules.")

    if report.fuzzy_inference and report.fuzzy_inference.conflict_report:
        cr = report.fuzzy_inference.conflict_report
        if cr.conflicting_rules:
            lines.append("")
            lines.append("-" * 40)
            lines.append("CONFLICT RESOLUTION (Phase 41)")
            lines.append("-" * 40)
            lines.append("Method:     " + str(cr.method_used))
            lines.append("Resolved:   " + str(round(cr.resolved_score, 2)))
            lines.append("Conflicts:  " + ", ".join(cr.conflicting_rules))
            if cr.winning_rule:
                lines.append("Winning:    " + str(cr.winning_rule))
            for note in cr.notes:
                lines.append("  -> " + note)

    if report.notes:
        lines.append("")
        lines.append("-" * 40)
        lines.append("SYSTEM NOTES")
        lines.append("-" * 40)
        for note in report.notes:
            lines.append("  * " + note)

    lines.append("")
    lines.append(sep)
    return "\n".join(lines)


def generate_fuzzy_json(report: FuzzyDecisionReport) -> Dict:
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
