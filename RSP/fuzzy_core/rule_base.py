"""
RSP — fuzzy_core/rule_base.py  (Phase 39: Fuzzy Rule Base, Phase 40: Rule Weighting)

نسخه‌ی حداقلی: فقط قوانینی که روی signal_strength (خروجی fuzzify شده‌ی
net_score) عمل می‌کنند و به یک خروجی تک‌متغیره‌ی «trade_permission» می‌رسند.
هر Rule یک وزن قابل‌تنظیم دارد (Phase 40) و یک مقدار خروجی singleton
(به‌سبک Sugeno - دلیل انتخاب در inference.py مستند شده).

قانون R4 دقیقاً همان یافته‌ی امروز را کدگذاری می‌کند: سیگنال «extreme»
(اجماع خیلی کامل) به‌جای بالاترین اعتماد، به یک اعتماد میانه/محتاطانه
می‌رسد - این جایگزین آستانه‌ی سخت Exhaustion (0.70) قدیمی است.
"""
from dataclasses import dataclass
from typing import Dict, List


@dataclass
class FuzzyRule:
    rule_id: str
    antecedent_term: str      # اصطلاح ورودی از signal_strength (weak/moderate/strong/extreme)
    weight: float              # وزن قابل‌تنظیم Rule (Phase 40)
    output_singleton: float    # خروجی singleton این Rule برای trade_permission (0..100)
    description: str


# Phase 39: Rule Base
SIGNAL_PERMISSION_RULES: List[FuzzyRule] = [
    FuzzyRule("R01", "weak", weight=1.0, output_singleton=5.0,
              description="سیگنال ضعیف -> اجازه‌ی معامله تقریباً صفر"),
    FuzzyRule("R02", "moderate", weight=1.0, output_singleton=55.0,
              description="سیگنال متوسط -> اجازه‌ی معامله در حد آستانه‌ی قبلی (MIN_CONFIDENCE_TO_TRADE)"),
    FuzzyRule("R03", "strong", weight=1.0, output_singleton=90.0,
              description="سیگنال قوی -> بالاترین اجازه‌ی معامله"),
    FuzzyRule("R04", "extreme", weight=1.0, output_singleton=35.0,
              description="سیگنال افراطی (اجماع خیلی کامل) -> اجازه‌ی معامله محتاطانه، "
                          "طبق یافته‌ی تجربی 'exhaustion' (نه صفر، نه بالا - فازی، نه بلوکه‌ی کامل)"),
]


def evaluate_rules(fuzzified_degrees: Dict[str, float],
                    rules: List[FuzzyRule] = None) -> Dict[str, float]:
    """هر Rule که antecedent_term اش در fuzzified_degrees درجه‌ی غیرصفر دارد،
    "فعال" است. قدرت فعال‌شدن = درجه‌ی عضویت × وزن Rule (Phase 41: در این
    نسخه‌ی حداقلی، تضاد بین Ruleها وجود ندارد چون هرکدوم فقط یک antecedent
    term متفاوت دارند - Conflict Resolution واقعی وقتی لازم می‌شود که
    Ruleهای چندمتغیره اضافه شوند، در فاز بعدی)."""
    rules = rules or SIGNAL_PERMISSION_RULES
    firing_strengths = {}
    for rule in rules:
        degree = fuzzified_degrees.get(rule.antecedent_term, 0.0)
        firing_strengths[rule.rule_id] = round(degree * rule.weight, 4)
    return firing_strengths
