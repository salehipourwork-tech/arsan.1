"""
RSP — fuzzy_core/rule_base.py (Phases 39-40: Fuzzy Rule Base + Rule Weighting)

نسخه‌ی گسترش‌یافته: Ruleهای چندمتغیره (multi-antecedent) که
ورودی‌های فازی از Quality Engines (Phase 29-38) را به Opportunity Quality
نگاشت می‌کنند.

هر Rule یک وزن دارد (Phase 40) و یک خروجی singleton (Sugeno-style).
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Callable

@dataclass
class FuzzyRule:
    rule_id: str
    # antecedents: dict of {variable_name: term_name}
    # e.g. {"trend_quality": "strong", "momentum_quality": "strong", ...}
    antecedents: Dict[str, str]
    weight: float
    output_singleton: float  # 0..100 for Sugeno
    description: str
    # Optional custom activation function override
    t_norm: Optional[Callable[[List[float]], float]] = None

    def evaluate(self, fuzzified_inputs: Dict[str, Dict[str, float]]) -> float:
        """
        محاسبه‌ی firing strength این Rule.
        fuzzified_inputs: {variable_name: {term_name: degree}}

        T-norm: min (standard fuzzy AND)
        """
        degrees = []
        for var_name, term_name in self.antecedents.items():
            var_dict = fuzzified_inputs.get(var_name, {})
            degree = var_dict.get(term_name, 0.0)
            degrees.append(degree)
        if not degrees:
            return 0.0
        if self.t_norm:
            return self.t_norm(degrees) * self.weight
        # Standard min T-norm
        return min(degrees) * self.weight

    def effective_output_singleton(self) -> float:
        """
        NEW (this session): single calibration knob for the whole rule base.
        Every consumer of `.output_singleton` (inference.py's Sugeno
        defuzzifier AND conflict_resolution.py's several resolution
        methods - both read it directly) now goes through this instead,
        so a walk-forward calibration search (see
        RSP/fuzzy_core/fuzzy_calibration_wf.py) can uniformly scale/shift
        overall rule generosity via
        settings.FUZZY_RULE_OUTPUT_MULTIPLIER/_OFFSET without hand-editing
        any of the 20 individually-designed singleton values above (each
        has its own documented rationale) and without missing one of the
        several read sites. Defaults to a no-op (1.0 / 0.0).
        """
        from ..config import settings
        mult = getattr(settings, "FUZZY_RULE_OUTPUT_MULTIPLIER", 1.0)
        off = getattr(settings, "FUZZY_RULE_OUTPUT_OFFSET", 0.0)
        return max(0.0, min(100.0, self.output_singleton * mult + off))


# =============================================================================
# Rule Base: Opportunity Quality Rules
# =============================================================================

OPPORTUNITY_RULES: List[FuzzyRule] = [
    # R01: Excellent opportunity — all stars aligned
    FuzzyRule(
        "R01",
        antecedents={
            "trend_quality": "very_strong",
            "momentum_quality": "very_strong",
            "entry_quality": "very_strong",
            "risk_quality": "very_strong",
            "volatility_quality": "excellent",
            "contradiction_severity": "none",
        },
        weight=1.0,
        output_singleton=100.0,
        description="همه‌ی شاخص‌ها عالی و بدون تضاد -> فرصت عالی",
    ),

    # R02: Strong opportunity — minor volatility issue
    FuzzyRule(
        "R02",
        antecedents={
            "trend_quality": "strong",
            "momentum_quality": "strong",
            "entry_quality": "strong",
            "risk_quality": "strong",
            "contradiction_severity": "low",
        },
        weight=1.0,
        output_singleton=90.0,
        description="روند و مومنتوم و ورود و ریسک قوی با تضاد کم -> فرصت قوی",
    ),

    # R03: Good opportunity — moderate everything
    FuzzyRule(
        "R03",
        antecedents={
            "trend_quality": "moderate",
            "momentum_quality": "moderate",
            "entry_quality": "moderate",
            "risk_quality": "moderate",
            "contradiction_severity": "low",
        },
        weight=1.0,
        output_singleton=65.0,
        description="همه چیز متوسط -> فرصت متوسط",
    ),

    # R04: Good momentum catch — strong momentum, moderate trend
    FuzzyRule(
        "R04",
        antecedents={
            "trend_quality": "moderate",
            "momentum_quality": "very_strong",
            "entry_quality": "strong",
            "risk_quality": "moderate",
            "contradiction_severity": "low",
        },
        weight=0.9,
        output_singleton=72.0,
        description="مومنتوم خیلی قوی ولی روند متوسط -> فرصت خوب (مومنتوم play)",
    ),

    # R05: Pullback entry — weak trend but good entry + strong risk
    FuzzyRule(
        "R05",
        antecedents={
            "trend_quality": "weak",
            "momentum_quality": "moderate",
            "entry_quality": "strong",
            "risk_quality": "very_strong",
            "contradiction_severity": "low",
        },
        weight=0.85,
        output_singleton=60.0,
        description="پولبک با ریسک کنترل‌شده -> فرصت محتاطانه",
    ),

    # R06: Breakout play — moderate trend, strong entry, volatility good
    FuzzyRule(
        "R06",
        antecedents={
            "trend_quality": "moderate",
            "momentum_quality": "strong",
            "entry_quality": "very_strong",
            "volatility_quality": "good",
            "contradiction_severity": "low",
        },
        weight=0.9,
        output_singleton=78.0,
        description="نقطه ورود عالی در شکست -> فرصت خوب",
    ),

    # R07: Exhaustion warning — extreme signal strength
    FuzzyRule(
        "R07",
        antecedents={
            "signal_strength": "extreme",
            "momentum_quality": "very_strong",
            "contradiction_severity": "low",
        },
        weight=1.0,
        output_singleton=40.0,
        description="سیگنال extreme (اشباع) -> اجازه‌ی معامله محتاطانه (نه صفر)",
    ),

    # R08: Contradiction block — moderate contradiction
    FuzzyRule(
        "R08",
        antecedents={
            "contradiction_severity": "moderate",
            "trend_quality": "strong",
            "momentum_quality": "strong",
        },
        weight=1.0,
        output_singleton=35.0,
        description="تضاد متوسط با شواهد قوی -> فرصت مرزی/محتاطانه",
    ),

    # R09: Severe contradiction — NO TRADE territory
    FuzzyRule(
        "R09",
        antecedents={
            "contradiction_severity": "severe",
        },
        weight=1.0,
        output_singleton=5.0,
        description="تضاد شدید -> تقریباً هیچ اجازه‌ی معامله",
    ),

    # R10: High volatility rejection
    FuzzyRule(
        "R10",
        antecedents={
            "volatility_quality": "very_poor",
            "risk_quality": "weak",
        },
        weight=1.0,
        output_singleton=10.0,
        description="نوسان خیلی بالا + ریسک ضعیف -> فرصت بسیار بد",
    ),

    # R11: Weak trend + weak momentum — no edge
    FuzzyRule(
        "R11",
        antecedents={
            "trend_quality": "weak",
            "momentum_quality": "weak",
            "entry_quality": "weak",
        },
        weight=1.0,
        output_singleton=8.0,
        description="همه چیز ضعیف -> بدون edge",
    ),

    # R12: Unstable market — stability penalty
    FuzzyRule(
        "R12",
        antecedents={
            "market_stability": "weak",
            "contradiction_severity": "high",
        },
        weight=1.0,
        output_singleton=15.0,
        description="بازار ناپایدار + تضاد -> فرصت بسیار محدود",
    ),

    # R13: Confidence-driven boost — high confidence overrides moderate weakness
    FuzzyRule(
        "R13",
        antecedents={
            "signal_confidence": "very_strong",
            "trend_quality": "moderate",
            "momentum_quality": "moderate",
            "contradiction_severity": "none",
        },
        weight=0.8,
        output_singleton=70.0,
        description="اعتماد بالا + بدون تضاد -> تقویت فرصت",
    ),

    # R14: Risk-reward excellence — even with moderate signal
    FuzzyRule(
        "R14",
        antecedents={
            "risk_quality": "very_strong",
            "entry_quality": "strong",
            "trend_quality": "moderate",
        },
        weight=0.85,
        output_singleton=68.0,
        description="ریسک/ریوارد عالی -> فرصت خوب حتی با سیگنال متوسط",
    ),

    # R15: Low confidence filter
    FuzzyRule(
        "R15",
        antecedents={
            "signal_confidence": "very_weak",
            "contradiction_severity": "moderate",
        },
        weight=1.0,
        output_singleton=12.0,
        description="اعتماد پایین + تضاد -> رد قاطع",
    ),

    # R16: Mean reversion setup — range + good entry + volatility excellent
    FuzzyRule(
        "R16",
        antecedents={
            "trend_quality": "weak",
            "volatility_quality": "excellent",
            "entry_quality": "strong",
            "contradiction_severity": "low",
        },
        weight=0.8,
        output_singleton=55.0,
        description="بازار رنج + نوسان کم + ورود خوب -> mean reversion محتاطانه",
    ),

    # R17: Trend following — strong trend, acceleration
    FuzzyRule(
        "R17",
        antecedents={
            "trend_quality": "very_strong",
            "momentum_quality": "strong",
            "market_stability": "strong",
            "contradiction_severity": "none",
        },
        weight=1.0,
        output_singleton=92.0,
        description="روند خیلی قوی + پایداری -> فرصت عالی trend-following",
    ),

    # R18: Fake breakout protection
    FuzzyRule(
        "R18",
        antecedents={
            "trend_quality": "moderate",
            "entry_quality": "weak",
            "volatility_quality": "poor",
            "contradiction_severity": "high",
        },
        weight=1.0,
        output_singleton=8.0,
        description="ورود ضعیف + نوسان بد + تضاد -> احتمال fake breakout",
    ),

    # R19: Recovery play — weak trend but momentum turning
    FuzzyRule(
        "R19",
        antecedents={
            "trend_quality": "weak",
            "momentum_quality": "strong",
            "market_stability": "moderate",
            "contradiction_severity": "low",
        },
        weight=0.85,
        output_singleton=58.0,
        description="مومنتوم در حال برگشت -> فرصت recovery محتاطانه",
    ),

    # R20: Default / fallback — when nothing strongly matches
    FuzzyRule(
        "R20",
        antecedents={
            "signal_strength": "moderate",
            "contradiction_severity": "low",
        },
        weight=0.5,
        output_singleton=45.0,
        description="حالت پیش‌فرض -> فرصت مرزی",
    ),
]


# =============================================================================
# Legacy Rule Base: Signal Permission Rules (for evaluate_signal_strength v1)
# =============================================================================

SIGNAL_PERMISSION_RULES: List[FuzzyRule] = [
    FuzzyRule(
        "SP01",
        antecedents={"signal_strength": "very_weak"},
        weight=1.0,
        output_singleton=5.0,
        description="سیگنال خیلی ضعیف -> اجازه معامله ناچیز",
    ),
    FuzzyRule(
        "SP02",
        antecedents={"signal_strength": "weak"},
        weight=1.0,
        output_singleton=20.0,
        description="سیگنال ضعیف -> اجازه معامله کم",
    ),
    FuzzyRule(
        "SP03",
        antecedents={"signal_strength": "moderate"},
        weight=1.0,
        output_singleton=50.0,
        description="سیگنال متوسط -> اجازه معامله متوسط",
    ),
    FuzzyRule(
        "SP04",
        antecedents={"signal_strength": "strong"},
        weight=1.0,
        output_singleton=80.0,
        description="سیگنال قوی -> اجازه معامله خوب",
    ),
    FuzzyRule(
        "SP05",
        antecedents={"signal_strength": "very_strong"},
        weight=1.0,
        output_singleton=90.0,
        description="سیگنال خیلی قوی -> اجازه معامله عالی",
    ),
    FuzzyRule(
        "SP06",
        antecedents={"signal_strength": "extreme"},
        weight=1.0,
        output_singleton=40.0,
        description="سیگنال extreme (اشباع) -> اجازه محتاطانه",
    ),
]


def evaluate_rules(fuzzified_inputs: Dict[str, Dict[str, float]],
                   rules: Optional[List[FuzzyRule]] = None) -> Dict[str, float]:
    """
    ارزیابی تمام Ruleها.
    خروجی: {rule_id: firing_strength}
    """
    rules = rules or OPPORTUNITY_RULES
    firing_strengths = {}
    for rule in rules:
        strength = rule.evaluate(fuzzified_inputs)
        if strength > 0.0:
            firing_strengths[rule.rule_id] = round(strength, 4)
    return firing_strengths


def get_active_rules(firing_strengths: Dict[str, float], threshold: float = 0.01) -> List[str]:
    return [rid for rid, strength in firing_strengths.items() if strength >= threshold]


def get_rule_by_id(rule_id: str) -> Optional[FuzzyRule]:
    for r in OPPORTUNITY_RULES:
        if r.rule_id == rule_id:
            return r
    return None
