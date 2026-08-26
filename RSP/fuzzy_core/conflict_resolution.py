"""
RSP — fuzzy_core/conflict_resolution.py (Phase 41: Rule Conflict Resolution)

وقتی چند Rule هم‌زمان فعال باشند و خروجی‌های متفاوتی داشته باشند
(مثلاً یکی opportunity=high و دیگری opportunity=low)،
این ماژول تضاد را تشخیص داده و حل می‌کند.

روش‌ها:
  1. Winner-Takes-All: Rule با بیشترین firing strength برنده
  2. Weighted Average: میانگین وزنی (Sugeno-style)
  3. Conservative Override: اگر Rule با خروجی پایین فعال باشد، آن را ترجیح بده
  4. Confidence-Gated: فقط Ruleهایی با firing > threshold در نظر گرفته شوند
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from RSP.fuzzy_core.rule_base import FuzzyRule, OPPORTUNITY_RULES


@dataclass
class ConflictResolutionReport:
    resolved_score: float
    method_used: str
    conflicting_rules: List[str] = field(default_factory=list)
    winning_rule: Optional[str] = None
    notes: List[str] = field(default_factory=list)


def _get_rule(rule_id: str) -> Optional[FuzzyRule]:
    for r in OPPORTUNITY_RULES:
        if r.rule_id == rule_id:
            return r
    return None


def detect_conflicts(firing_strengths: Dict[str, float]) -> List[List[str]]:
    """
    گروه‌بندی Ruleهای فعال بر اساس نزدیکی خروجی singleton.
    اگر دو Rule فعال باشند و اختلاف singleton آن‌ها > 30 باشد،
    در گروه‌های متفاوت قرار می‌گیرند -> conflict.
    """
    active = {rid: strength for rid, strength in firing_strengths.items() if strength > 0.05}
    if len(active) <= 1:
        return []

    # Sort by singleton output
    items = []
    for rid, strength in active.items():
        rule = _get_rule(rid)
        if rule:
            items.append((rid, rule.effective_output_singleton(), strength))
    items.sort(key=lambda x: x[1])

    # Cluster by gap > 30
    clusters = []
    current = [items[0]]
    for i in range(1, len(items)):
        if items[i][1] - items[i-1][1] > 30:
            clusters.append(current)
            current = []
        current.append(items[i])
    clusters.append(current)

    if len(clusters) <= 1:
        return []

    # Return groups of rule_ids that conflict
    return [[x[0] for x in cluster] for cluster in clusters]


def resolve_conflicts(
    firing_strengths: Dict[str, float],
    method: str = "conservative_weighted",
    conservative_threshold: float = 25.0,
) -> ConflictResolutionReport:
    """
    حل تضاد بین Ruleهای فعال.

    Methods:
      - "winner_takes_all": Rule با max(firing * singleton) برنده
      - "weighted_average": Sugeno-style weighted average (default for Sugeno)
      - "conservative_weighted": Weighted average but cap by lowest active singleton
      - "conservative_override": اگر ANY rule با singleton < threshold فعال باشد،
                                 خروجی = min(weighted_avg, that_singleton)
    """
    report = ConflictResolutionReport(resolved_score=0.0, method_used=method)

    active = {rid: s for rid, s in firing_strengths.items() if s > 0.01}
    if not active:
        report.notes.append("هیچ Rule فعالی وجود ندارد")
        return report

    conflict_groups = detect_conflicts(firing_strengths)
    if conflict_groups:
        report.conflicting_rules = [rid for group in conflict_groups for rid in group]
        report.notes.append(f"تضاد بین {len(report.conflicting_rules)} Rule شناسایی شد: {report.conflicting_rules}")

    # Calculate weighted average (baseline)
    total_firing = sum(active.values())
    if total_firing <= 0:
        report.notes.append("مجموع firing strength صفر")
        return report

    weighted_sum = sum(
        strength * (_get_rule(rid).effective_output_singleton() if _get_rule(rid) else 0)
        for rid, strength in active.items()
    )
    weighted_avg = weighted_sum / total_firing

    if method == "weighted_average":
        report.resolved_score = round(weighted_avg, 2)
        # Winning rule = closest to output
        report.winning_rule = min(active.keys(),
            key=lambda rid: abs((_get_rule(rid).effective_output_singleton() if _get_rule(rid) else 0) - weighted_avg))

    elif method == "winner_takes_all":
        # Winner = max(firing_strength * singleton) — not just max firing
        winner = max(active.keys(),
            key=lambda rid: active[rid] * (_get_rule(rid).effective_output_singleton() if _get_rule(rid) else 0))
        report.resolved_score = round(_get_rule(winner).effective_output_singleton() if _get_rule(winner) else 0, 2)
        report.winning_rule = winner

    elif method == "conservative_weighted":
        # FIX (this session): the previous version capped weighted_avg by
        # the lowest singleton among ANY active rule, regardless of how
        # small that rule's firing strength was relative to the rest (the
        # 0.01 reporting threshold applied above meant a rule contributing
        # e.g. 1% of total firing weight could still drag a near-perfect
        # setup all the way down to its own low singleton). Confirmed via
        # isolated test: R01 firing at 1.0 (singleton=100) alongside R07
        # firing at just 0.0056 (singleton=40) produced resolved_score=40,
        # not because R07's evidence was strong, but purely because it was
        # present at all.
        #
        # Now the pull toward the lowest-singleton rule is scaled by that
        # rule's actual share of total firing weight — a rule contributing
        # negligible weight barely moves the score; a rule that dominates
        # firing still pulls the score down hard, preserving the
        # "conservative" intent without an all-or-nothing floor.
        min_rid = min(
            active.keys(),
            key=lambda rid: (_get_rule(rid).effective_output_singleton() if _get_rule(rid) else 100),
        )
        min_singleton = _get_rule(min_rid).effective_output_singleton() if _get_rule(min_rid) else 100
        min_rule_weight = active[min_rid] / total_firing  # 0..1 share of total firing
        pulled = weighted_avg - min_rule_weight * (weighted_avg - min_singleton)
        report.resolved_score = round(max(0.0, min(100.0, pulled)), 2)
        report.notes.append(
            f"Conservative weighted-cap applied: min_singleton={min_singleton}, "
            f"its_relative_firing_weight={round(min_rule_weight, 4)}"
        )

    elif method == "conservative_override":
        low_rules = [
            rid for rid in active.keys()
            if _get_rule(rid) and _get_rule(rid).effective_output_singleton() < conservative_threshold
        ]
        if low_rules:
            min_low = min(_get_rule(rid).effective_output_singleton() for rid in low_rules if _get_rule(rid))
            report.resolved_score = round(min(weighted_avg, min_low), 2)
            report.notes.append(f"Conservative override: low rule(s) {low_rules} capped output to {min_low}")
        else:
            report.resolved_score = round(weighted_avg, 2)

    else:
        report.resolved_score = round(weighted_avg, 2)
        report.notes.append(f"Method unknown ({method}), fallback to weighted_average")

    return report
