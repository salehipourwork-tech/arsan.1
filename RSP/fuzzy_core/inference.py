"""
RSP — fuzzy_core/inference.py  (Phase 42: Fuzzy Inference Engine, Phase 43: Aggregation,
Phase 44: Defuzzification)

انتخاب روش: Sugeno (نه Mamdani).
دلیل مهندسی: خروجی موردنیاز ما یک عدد تک (trade_permission_score، 0..100)
است که مستقیم به یک آستانه‌ی تصمیم می‌رود - نه یک شکل فازی که باید بعداً
defuzzify شود. Sugeno با خروجی singleton به همین‌جا می‌رسد بدون نیاز به
یک Membership Function خروجی جداگانه، سریع‌تر محاسبه می‌شود، و برای این
مقیاس (یک Feature ورودی، ۴ Rule) دقت عملی یکسانی با Mamdani دارد. اگر در
فازهای بعدی چند Feature ورودی همزمان با تعامل غیرخطی لازم شد، Mamdani
دوباره ارزیابی می‌شود.

Defuzzification: میانگین وزنی (weighted average) قدرت فعال‌شدن هر Rule در
خروجی singleton آن - فرمول استاندارد Sugeno-style Weighted Average:

    trade_permission = sum(firing_i * output_i) / sum(firing_i)
"""
from dataclasses import dataclass, field
from typing import Dict, List

from RSP.fuzzy_core.membership import build_signal_strength_variable
from RSP.fuzzy_core.rule_base import SIGNAL_PERMISSION_RULES, evaluate_rules
from RSP.config import settings


@dataclass
class FuzzySignalReport:
    """گزارش کامل (طبق فرمت DECISION REPORT درخواستی) برای یک ارزیابی فازی."""
    input_value: float = 0.0
    membership_degrees: Dict[str, float] = field(default_factory=dict)
    dominant_term: str = "UNDEFINED"
    active_rules: List[str] = field(default_factory=list)
    rule_firing_strengths: Dict[str, float] = field(default_factory=dict)
    trade_permission_score: float = 0.0   # خروجی بعد از Defuzzification (0..100)


def evaluate_signal_strength(net_score: float) -> FuzzySignalReport:
    """ورودی: net_score خام (-1..+1، از fusion_engine). قدر مطلق گرفته
    می‌شود چون جهت (BUY/SELL) جدا مدیریت می‌شود - این تابع فقط «قدرت»
    سیگنال را ارزیابی می‌کند، نه جهتش."""
    report = FuzzySignalReport(input_value=round(abs(net_score), 4))

    var = build_signal_strength_variable(
        weak_end=settings.FUZZY_SIGNAL_WEAK_END,
        moderate_center=settings.FUZZY_SIGNAL_MODERATE_CENTER,
        strong_center=settings.FUZZY_SIGNAL_STRONG_CENTER,
        extreme_start=settings.FUZZY_SIGNAL_EXTREME_START,
    )
    degrees = var.fuzzify(report.input_value)
    report.membership_degrees = degrees
    report.dominant_term = var.dominant_term(degrees)

    firing = evaluate_rules(degrees, SIGNAL_PERMISSION_RULES)
    report.rule_firing_strengths = firing
    report.active_rules = [rid for rid, strength in firing.items() if strength > 0.0]

    # Phase 44: Defuzzification (Sugeno weighted average)
    total_firing = sum(firing.values())
    if total_firing <= 0:
        report.trade_permission_score = 0.0
    else:
        weighted_sum = sum(
            firing[rule.rule_id] * rule.output_singleton
            for rule in SIGNAL_PERMISSION_RULES
        )
        report.trade_permission_score = round(weighted_sum / total_firing, 2)

    return report
