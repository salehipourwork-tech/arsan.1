"""
RSP — fuzzy_core/membership.py  (Phase 27: Fuzzy Membership Engine, Phase 28: Fuzzy Linguistic Variables)

پیاده‌سازی حداقلی و قابل‌تست Membership Functionهای فازی. طبق قانون پرامپت
اصلی، استفاده از یک نوع Membership Function برای همه‌ی Featureها ممنوع است؛
اینجا ۴ نوع پیاده‌سازی شده (Triangular, Trapezoidal, Gaussian, Sigmoid) و هر
LinguisticVariable آزاد است هرکدوم را برای هر Term انتخاب کند.

این نسخه عمداً حداقلی است: فقط یک LinguisticVariable واقعی (signal_strength)
ساخته شده که به دو نقطه‌ی تصمیم موجود (آستانه‌ی BUY/SELL و آستانه‌ی
Exhaustion) وصل می‌شود. بقیه‌ی Featureها (Trend/Momentum/Entry/Risk/...)
در فازهای بعدی اضافه می‌شوند - این فایل طوری طراحی شده که آن گسترش بدون
تغییر در این بخش انجام شود.
"""
from dataclasses import dataclass, field
from typing import Callable, Dict, List
import math


def triangular(x: float, a: float, b: float, c: float) -> float:
    """صعود خطی از a تا b (اوج=1)، نزول خطی از b تا c."""
    if x <= a or x >= c:
        return 0.0
    if x == b:
        return 1.0
    if x < b:
        return (x - a) / (b - a)
    return (c - x) / (c - b)


def trapezoidal(x: float, a: float, b: float, c: float, d: float) -> float:
    """صعود خطی a→b (اوج=1)، سطح صاف b→c، نزول خطی c→d.
    ترتیب چک‌ها عمداً این‌طور است: ابتدا سطح صاف چک می‌شود، چون در حالت
    مرزی c==d (بدون لبه‌ی نزولی، مثلاً انتهای بازه‌ی [0,1])، اگر چک
    'x >= d' زودتر اجرا شود، نقطه‌ی x==c==d به‌اشتباه 0 برمی‌گرداند."""
    if b <= x <= c:
        return 1.0
    if x <= a or x >= d:
        return 0.0
    if x < b:
        return (x - a) / (b - a)
    return (d - x) / (d - c)


def gaussian(x: float, center: float, sigma: float) -> float:
    """تابع گاوسی؛ برای Featureهایی که یک نقطه‌ی مرکزی مشخص دارند (نه بازه)."""
    if sigma <= 0:
        return 1.0 if x == center else 0.0
    return math.exp(-((x - center) ** 2) / (2 * sigma ** 2))


def sigmoid(x: float, midpoint: float, steepness: float) -> float:
    """تابع سیگموید؛ برای Featureهایی با یک لبه‌ی یک‌طرفه (نه دوطرفه مثل مثلث)."""
    try:
        return 1.0 / (1.0 + math.exp(-steepness * (x - midpoint)))
    except OverflowError:
        return 0.0 if steepness * (x - midpoint) < 0 else 1.0


@dataclass
class Term:
    """یک اصطلاح زبانی (مثل 'strong') و تابع عضویتش."""
    name: str
    membership_fn: Callable[[float], float]


@dataclass
class LinguisticVariable:
    """مجموعه‌ای از Termها روی یک Feature واحد. fuzzify یک مقدار خام را به
    درجه‌ی عضویت در هر Term تبدیل می‌کند (می‌تواند هم‌زمان در چند Term با
    درجه‌ی مختلف عضو باشد - این اصل اساسی فازی است)."""
    name: str
    terms: List[Term] = field(default_factory=list)

    def fuzzify(self, x: float) -> Dict[str, float]:
        return {t.name: round(t.membership_fn(x), 4) for t in self.terms}

    def dominant_term(self, degrees: Dict[str, float]) -> str:
        """فقط برای گزارش/نمایش - خود منطق تصمیم نباید فقط از dominant_term
        استفاده کند، باید از کل بردار درجه‌ها استفاده کند."""
        if not degrees:
            return "UNDEFINED"
        return max(degrees.items(), key=lambda kv: kv[1])[0]


def build_signal_strength_variable(weak_end: float, moderate_center: float,
                                    strong_center: float, extreme_start: float) -> LinguisticVariable:
    """می‌سازد: weak / moderate / strong / extreme روی |net_score| در [0,1].
    مرزها پارامتری هستند (نه هاردکد) تا بشود روی داده‌ی واقعی کالیبره کرد
    بدون دست‌زدن به این فایل - پارامترها در settings.py نگه داشته می‌شوند."""
    return LinguisticVariable(
        name="signal_strength",
        terms=[
            Term("weak", lambda x: trapezoidal(x, 0.0, 0.0, weak_end * 0.5, weak_end)),
            Term("moderate", lambda x: triangular(x, weak_end * 0.5, moderate_center,
                                                    strong_center)),
            Term("strong", lambda x: triangular(x, moderate_center, strong_center, extreme_start)),
            Term("extreme", lambda x: trapezoidal(x, strong_center, extreme_start, 1.0, 1.0)),
        ],
    )
