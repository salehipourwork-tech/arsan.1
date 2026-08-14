"""
RSP — fuzzy_core/inference.py (Phases 42-44: Fuzzy Inference + Aggregation + Defuzzification)

دو روش استاندارد پشتیبانی می‌شود:
  1. Sugeno (پیش‌فرض): سریع، خروجی singleton، نیاز به MF خروجی ندارد.
     مناسب برای Decision Engine که فقط یک عدد می‌خواهد.
  2. Mamdani: خروجی فازی واقعی با MF خروجی (trapezoidal/triangular).
     مناسب برای تفسیر و گزارش‌دهی انسانی.

انتخاب روش: config-driven (FUZZY_INFERENCE_METHOD).

Defuzzification:
  - Sugeno: Weighted Average (استاندارد)
  - Mamdani: Centroid (میانگین وزنی سطح زیر منحنی)
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import math

from RSP.fuzzy_core.membership import (
    build_opportunity_quality_variable,
    triangular, trapezoidal,
)
from RSP.fuzzy_core.rule_base import (
    FuzzyRule, OPPORTUNITY_RULES, evaluate_rules, get_active_rules,
)
from RSP.fuzzy_core.conflict_resolution import (
    resolve_conflicts, ConflictResolutionReport,
)


@dataclass
class FuzzyInferenceReport:
    input_fuzzified: Dict[str, Dict[str, float]] = field(default_factory=dict)
    active_rules: List[str] = field(default_factory=list)
    rule_firing_strengths: Dict[str, float] = field(default_factory=dict)
    aggregated_output_fuzzy: Optional[Dict[str, float]] = None  # for Mamdani
    defuzzified_score: float = 0.0  # 0..100
    method: str = "Sugeno"
    conflict_report: Optional[ConflictResolutionReport] = None
    dominant_term: str = "UNDEFINED"
    notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Sugeno Inference (default)
# ---------------------------------------------------------------------------
def _sugeno_defuzzify(firing_strengths: Dict[str, float]) -> float:
    """Weighted average of singleton outputs."""
    total = sum(firing_strengths.values())
    if total <= 0:
        return 0.0
    weighted = sum(
        strength * (next((r.output_singleton for r in OPPORTUNITY_RULES if r.rule_id == rid), 0))
        for rid, strength in firing_strengths.items()
    )
    return round(weighted / total, 2)


# ---------------------------------------------------------------------------
# Mamdani Inference
# ---------------------------------------------------------------------------
def _mamdani_aggregate(firing_strengths: Dict[str, float]) -> Dict[str, float]:
    """
    برای هر Rule، MF خروجی Opportunity Quality را با firing_strength clip می‌کنیم
    (min-implication). سپس union (max) می‌گیریم.

    به‌جای پیاده‌سازی کامل integral روی continuous domain،
    روی grid گسسته (0..100 با گام 1) approximate centroid می‌گیریم.
    """
    opp_var = build_opportunity_quality_variable()
    # Grid: 0 to 100
    grid = {i: 0.0 for i in range(101)}

    for rid, strength in firing_strengths.items():
        rule = next((r for r in OPPORTUNITY_RULES if r.rule_id == rid), None)
        if not rule:
            continue
        # Output singleton position maps to center of a triangular MF
        center = rule.output_singleton
        # Create a triangular MF around center with base width ~30
        a = max(0, center - 20)
        b = center
        c = min(100, center + 20)
        for x in range(101):
            mu = triangular(x, a, b, c)
            clipped = min(mu, strength)
            grid[x] = max(grid[x], clipped)  # max aggregation (union)

    return grid


def _centroid_defuzzify(grid: Dict[float, float]) -> float:
    """Centroid of discrete grid."""
    numerator = sum(x * mu for x, mu in grid.items())
    denominator = sum(mu for mu in grid.values())
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 2)


# ---------------------------------------------------------------------------
# Main Inference Entry Point
# ---------------------------------------------------------------------------
def run_fuzzy_inference(
    fuzzified_inputs: Dict[str, Dict[str, float]],
    method: str = "Sugeno",
    conflict_method: str = "conservative_weighted",
) -> FuzzyInferenceReport:
    """
    ورودی: fuzzified_inputs = {variable_name: {term: degree}}
    خروجی: FuzzyInferenceReport کامل

    method: "Sugeno" | "Mamdani"
    conflict_method: روش حل تضاد (Phase 41)
    """
    report = FuzzyInferenceReport(input_fuzzified=fuzzified_inputs, method=method)

    # Phase 42: Rule Evaluation
    firing = evaluate_rules(fuzzified_inputs, OPPORTUNITY_RULES)
    report.rule_firing_strengths = firing
    report.active_rules = get_active_rules(firing, threshold=0.01)

    # ROOT-CAUSE FIX (confirmed by production evidence, 2026-08-13):
    # نسخه‌ی قبلی اینجا چک می‌کرد `if not report.active_rules` — یعنی لیست
    # rule هایی که از آستانه‌ی گزارش‌دهی (threshold=0.01) رد شده‌اند. این
    # threshold صرفاً برای «کدام rule را در گزارش/UI به‌عنوان active نشان
    # بده» طراحی شده بود، ولی به‌اشتباه به مسیر امتیازدهی هم وصل شده بود:
    # هر لحظه که هیچ rule ای به‌اندازه‌ی ۰٫۰۱ فایر نمی‌کرد (even اگر rule های
    # دیگر با قدرت کوچک‌تر، مثلاً ۰٫۰۰۳، فایر کرده بودند) کل امتیاز به‌طور
    # کامل صفر می‌شد. روی داده‌ی واقعی تولید (RSP/main.py --fuzzy-compare,
    # 240 روز، چند کوین) این مسیر ۴۵-۵۸٪ کل مراحل را درگیر کرد — یعنی نزدیک
    # به نیمی از تصمیم‌ها اصلاً بر پایه‌ی داده نبودند، بلکه یک صفر کور بودند
    # که بعداً به‌اشتباه به‌عنوان "OPPORTUNITY_SCORE_BELOW_THRESHOLD (0.0 <
    # 50.0)" در آمار رد معاملات ثبت می‌شد — این آمار evidence واقعی نیست.
    # فیکس: فقط وقتی firing واقعاً کاملاً خالی است (هیچ rule ای حتی با
    # کوچک‌ترین قدرت فایر نکرده) صفر برگردان؛ در غیر این صورت از همان
    # weighted-average موجود (_sugeno_defuzzify) روی firing خام استفاده کن —
    # این تابع خودش از قبل safe است (total<=0 -> 0.0)، پس این فیکس هیچ
    # threshold/weight/membership function را عوض نمی‌کند، فقط یک گیت
    # گزارش‌دهی را از مسیر امتیازدهی جدا می‌کند.
    if not firing:
        report.notes.append("هیچ Rule ای حتی جزئی فایر نکرد - خروجی صفر (NO_TRADE ایمن)")
        report.defuzzified_score = 0.0
        return report

    # Phase 41: Conflict Resolution
    conflict_report = resolve_conflicts(firing, method=conflict_method)
    report.conflict_report = conflict_report
    if conflict_report.conflicting_rules:
        report.notes.append(f"Conflict resolved via {conflict_method}: score={conflict_report.resolved_score}")

    # Phase 43-44: Aggregation + Defuzzification
    if method == "Sugeno":
        # Use conflict-resolved score if available, else raw weighted average
        if conflict_report and conflict_report.resolved_score > 0:
            report.defuzzified_score = conflict_report.resolved_score
        else:
            report.defuzzified_score = _sugeno_defuzzify(firing)
        report.notes.append(f"Sugeno weighted average defuzzification: {report.defuzzified_score}")

    elif method == "Mamdani":
        grid = _mamdani_aggregate(firing)
        report.aggregated_output_fuzzy = {k: round(v, 4) for k, v in grid.items() if v > 0.001}
        report.defuzzified_score = _centroid_defuzzify(grid)
        report.notes.append(f"Mamdani centroid defuzzification: {report.defuzzified_score}")

    else:
        report.notes.append(f"Method {method} unknown, fallback to Sugeno")
        report.defuzzified_score = _sugeno_defuzzify(firing)

    # Dominant term on output
    opp_var = build_opportunity_quality_variable()
    out_degrees = opp_var.fuzzify(report.defuzzified_score / 100.0)
    report.dominant_term = opp_var.dominant_term(out_degrees)

    return report


# ---------------------------------------------------------------------------
# Legacy compatibility (for existing crisp-fuzzy hybrid path)
# ---------------------------------------------------------------------------
from RSP.fuzzy_core.membership import build_signal_strength_variable
from RSP.config import settings

@dataclass
class FuzzySignalReport:
    """Legacy report for signal_strength evaluation (kept for backward compat)."""
    input_value: float = 0.0
    membership_degrees: Dict[str, float] = field(default_factory=dict)
    dominant_term: str = "UNDEFINED"
    active_rules: List[str] = field(default_factory=list)
    rule_firing_strengths: Dict[str, float] = field(default_factory=dict)
    trade_permission_score: float = 0.0


def evaluate_signal_strength(net_score: float) -> FuzzySignalReport:
    """Legacy single-variable fuzzy evaluation (Phase 27-28 v1)."""
    report = FuzzySignalReport(input_value=round(abs(net_score), 4))
    var = build_signal_strength_variable()
    degrees = var.fuzzify(report.input_value)
    report.membership_degrees = degrees
    report.dominant_term = var.dominant_term(degrees)

    # Simple 4-rule base from v1
    from RSP.fuzzy_core.rule_base import SIGNAL_PERMISSION_RULES, evaluate_rules as _eval_legacy
    firing = _eval_legacy(degrees, SIGNAL_PERMISSION_RULES)
    report.rule_firing_strengths = firing
    report.active_rules = [rid for rid, s in firing.items() if s > 0.0]

    total = sum(firing.values())
    if total > 0:
        weighted = sum(
            firing[r.rule_id] * r.output_singleton
            for r in SIGNAL_PERMISSION_RULES
        )
        report.trade_permission_score = round(weighted / total, 2)
    return report
