"""
RSP — fuzzy_core/membership.py (Phase 27-28: Fuzzy Membership Engine + Linguistic Variables)

پیاده‌سازی کامل Membership Functionهای فازی. طبق قانون پرامپت،
استفاده از یک نوع Membership Function برای همه‌ی Featureها ممنوع است.

این نسخه شامل ۸ نوع MF است:
  Triangular, Trapezoidal, Gaussian, Sigmoid,
  Generalized Bell, S-Shaped, Z-Shaped, Pi-Shaped

هر LinguisticVariable می‌تواند برای هر Term یک MF متفاوت انتخاب کند.
"""
import math
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

def triangular(x: float, a: float, b: float, c: float) -> float:
    if x <= a or x >= c:
        return 0.0
    if x == b:
        return 1.0
    if x < b:
        return (x - a) / (b - a)
    return (c - x) / (c - b)

def trapezoidal(x: float, a: float, b: float, c: float, d: float) -> float:
    if b <= x <= c:
        return 1.0
    if x <= a or x >= d:
        return 0.0
    if x < b:
        return (x - a) / (b - a)
    return (d - x) / (d - c)

def gaussian(x: float, center: float, sigma: float) -> float:
    if sigma <= 0:
        return 1.0 if x == center else 0.0
    return math.exp(-((x - center) ** 2) / (2 * sigma ** 2))

def sigmoid(x: float, midpoint: float, steepness: float) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-steepness * (x - midpoint)))
    except OverflowError:
        return 0.0 if steepness * (x - midpoint) < 0 else 1.0

def generalized_bell(x: float, a: float, b: float, c: float) -> float:
    """Bell MF: a=width, b=slope, c=center."""
    if a == 0:
        return 1.0 if x == c else 0.0
    return 1.0 / (1.0 + abs((x - c) / a) ** (2 * b))

def s_shaped(x: float, a: float, b: float) -> float:
    """S-shaped: 0 at a, 1 at b, quadratic in between."""
    if x <= a:
        return 0.0
    if x >= b:
        return 1.0
    if x <= (a + b) / 2:
        return 2.0 * ((x - a) / (b - a)) ** 2
    return 1.0 - 2.0 * ((x - b) / (b - a)) ** 2

def z_shaped(x: float, a: float, b: float) -> float:
    """Z-shaped: 1 at a, 0 at b, mirror of S-shaped."""
    if x <= a:
        return 1.0
    if x >= b:
        return 0.0
    if x <= (a + b) / 2:
        return 1.0 - 2.0 * ((x - a) / (b - a)) ** 2
    return 2.0 * ((x - b) / (b - a)) ** 2

def pi_shaped(x: float, a: float, b: float, c: float, d: float) -> float:
    """Pi-shaped: S up then Z down = trapezoid with curved shoulders."""
    if x <= a:
        return 0.0
    if x >= d:
        return 0.0
    if b <= x <= c:
        return 1.0
    if x < b:
        return s_shaped(x, a, b)
    return z_shaped(x, c, d)


@dataclass
class Term:
    name: str
    membership_fn: Callable[[float], float]
    mf_type: str = ""  # for logging/debugging

    def evaluate(self, x: float) -> float:
        return self.membership_fn(x)


@dataclass
class LinguisticVariable:
    name: str
    domain: tuple = (0.0, 1.0)  # (min, max)
    terms: List[Term] = field(default_factory=list)

    def fuzzify(self, x: float) -> Dict[str, float]:
        """تبدیل مقدار خام به درجه‌ی عضویت در هر Term."""
        # Clamp to domain
        x = max(self.domain[0], min(self.domain[1], x))
        return {t.name: round(t.evaluate(x), 4) for t in self.terms}

    def dominant_term(self, degrees: Dict[str, float]) -> str:
        if not degrees:
            return "UNDEFINED"
        return max(degrees.items(), key=lambda kv: kv[1])[0]

    def term_by_name(self, name: str) -> Optional[Term]:
        for t in self.terms:
            if t.name == name:
                return t
        return None


# =============================================================================
# Factory builders for each Quality Phase (29-38)
# =============================================================================

def build_quality_variable(
    name: str,
    weak_end: float = 0.25,
    moderate_center: float = 0.45,
    strong_center: float = 0.70,
    extreme_start: float = 0.85,
    domain: tuple = (0.0, 1.0),
) -> LinguisticVariable:
    """
    ساخت یک Quality Variable استاندارد ۵-term:
    very_weak, weak, moderate, strong, very_strong
    """
    return LinguisticVariable(
        name=name,
        domain=domain,
        terms=[
            Term("very_weak", lambda x: z_shaped(x, weak_end * 0.3, weak_end), "z_shaped"),
            Term("weak", lambda x: trapezoidal(x, 0.0, weak_end * 0.5, weak_end, moderate_center), "trapezoidal"),
            Term("moderate", lambda x: triangular(x, weak_end, moderate_center, strong_center), "triangular"),
            Term("strong", lambda x: triangular(x, moderate_center, strong_center, extreme_start), "triangular"),
            Term("very_strong", lambda x: s_shaped(x, strong_center, extreme_start), "s_shaped"),
        ],
    )


def build_trend_quality_variable() -> LinguisticVariable:
    """Phase 29: Fuzzy Trend Quality"""
    return build_quality_variable("trend_quality", 0.20, 0.40, 0.65, 0.85)


def build_momentum_quality_variable() -> LinguisticVariable:
    """Phase 30: Fuzzy Momentum Quality"""
    return build_quality_variable("momentum_quality", 0.25, 0.45, 0.70, 0.88)


def build_entry_quality_variable() -> LinguisticVariable:
    """Phase 31: Fuzzy Entry Quality"""
    return build_quality_variable("entry_quality", 0.20, 0.40, 0.65, 0.85)


def build_risk_quality_variable() -> LinguisticVariable:
    """Phase 32: Fuzzy Risk Quality"""
    return build_quality_variable("risk_quality", 0.25, 0.45, 0.70, 0.90)


def build_volatility_quality_variable() -> LinguisticVariable:
    """Phase 33: Fuzzy Volatility Quality
    نوسان خیلی بالا = کیفیت پایین (برای معامله نامناسب)
    نوسان متعادل = کیفیت بالا
    """
    return LinguisticVariable(
        name="volatility_quality",
        domain=(0.0, 1.0),
        terms=[
            Term("very_poor", lambda x: s_shaped(x, 0.70, 0.90), "s_shaped"),  # vol high -> poor
            Term("poor", lambda x: trapezoidal(x, 0.55, 0.65, 0.75, 0.85), "trapezoidal"),
            Term("moderate", lambda x: triangular(x, 0.40, 0.55, 0.70), "triangular"),
            Term("good", lambda x: triangular(x, 0.25, 0.40, 0.55), "triangular"),
            Term("excellent", lambda x: z_shaped(x, 0.15, 0.35), "z_shaped"),  # vol low -> excellent
        ],
    )


def build_market_stability_variable() -> LinguisticVariable:
    """Phase 34: Fuzzy Market Stability"""
    return build_quality_variable("market_stability", 0.20, 0.40, 0.65, 0.85)


def build_signal_strength_variable() -> LinguisticVariable:
    """Phase 35: Fuzzy Signal Strength (expanded from v1)"""
    return LinguisticVariable(
        name="signal_strength",
        domain=(0.0, 1.0),
        terms=[
            Term("very_weak", lambda x: z_shaped(x, 0.10, 0.20), "z_shaped"),
            Term("weak", lambda x: trapezoidal(x, 0.0, 0.10, 0.20, 0.35), "trapezoidal"),
            Term("moderate", lambda x: triangular(x, 0.20, 0.40, 0.60), "triangular"),
            Term("strong", lambda x: triangular(x, 0.45, 0.65, 0.80), "triangular"),
            Term("very_strong", lambda x: trapezoidal(x, 0.70, 0.80, 0.90, 1.0), "trapezoidal"),
            Term("extreme", lambda x: s_shaped(x, 0.85, 0.95), "s_shaped"),
        ],
    )


def build_signal_confidence_variable() -> LinguisticVariable:
    """Phase 36: Fuzzy Signal Confidence"""
    return build_quality_variable("signal_confidence", 0.25, 0.45, 0.70, 0.88)


def build_contradiction_severity_variable() -> LinguisticVariable:
    """Phase 37: Fuzzy Contradiction Severity
    تضاد شدید = very_high (این یک "bad" indicator است، پس بالا بودن = bad)
    """
    return LinguisticVariable(
        name="contradiction_severity",
        domain=(0.0, 1.0),
        terms=[
            Term("none", lambda x: z_shaped(x, 0.05, 0.15), "z_shaped"),
            Term("low", lambda x: trapezoidal(x, 0.0, 0.10, 0.20, 0.35), "trapezoidal"),
            Term("moderate", lambda x: triangular(x, 0.20, 0.40, 0.60), "triangular"),
            Term("high", lambda x: triangular(x, 0.45, 0.65, 0.80), "triangular"),
            Term("severe", lambda x: s_shaped(x, 0.70, 0.90), "s_shaped"),
        ],
    )


def build_opportunity_quality_variable() -> LinguisticVariable:
    """Phase 38: Fuzzy Opportunity Quality"""
    return LinguisticVariable(
        name="opportunity_quality",
        domain=(0.0, 1.0),
        terms=[
            Term("very_poor", lambda x: z_shaped(x, 0.15, 0.25), "z_shaped"),
            Term("poor", lambda x: trapezoidal(x, 0.10, 0.20, 0.30, 0.45), "trapezoidal"),
            Term("moderate", lambda x: triangular(x, 0.30, 0.50, 0.70), "triangular"),
            Term("good", lambda x: triangular(x, 0.55, 0.70, 0.85), "triangular"),
            Term("excellent", lambda x: s_shaped(x, 0.80, 0.95), "s_shaped"),
        ],
    )


# Registry of all quality variables for easy access
QUALITY_VARIABLE_REGISTRY = {
    "trend_quality": build_trend_quality_variable(),
    "momentum_quality": build_momentum_quality_variable(),
    "entry_quality": build_entry_quality_variable(),
    "risk_quality": build_risk_quality_variable(),
    "volatility_quality": build_volatility_quality_variable(),
    "market_stability": build_market_stability_variable(),
    "signal_strength": build_signal_strength_variable(),
    "signal_confidence": build_signal_confidence_variable(),
    "contradiction_severity": build_contradiction_severity_variable(),
    "opportunity_quality": build_opportunity_quality_variable(),
}


def get_quality_variable(name: str) -> Optional[LinguisticVariable]:
    return QUALITY_VARIABLE_REGISTRY.get(name)
