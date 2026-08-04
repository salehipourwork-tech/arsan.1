"""
RSP — phase_registry.py

ثبت رسمی فازها طبق معماری ۱۰لایه‌ی پیشنهادی. این نسخه فقط فازهای Layer 5
(Fuzzy Intelligence Core) و Layer 6 (Fuzzy Rule System) را که واقعاً امروز
پیاده‌سازی شدند ثبت می‌کند - هر فاز موجود دیگر که فقط باید اینجا نام‌گذاری
مجدد شود (بدون تغییر کد)، در گسترش بعدی این فایل اضافه می‌شود.

هر ورودی طبق الزام پرامپت: هدف، ورودی، خروجی، وضعیت، معیار موفقیت،
Failure Mode.
"""
from dataclasses import dataclass, field
from typing import List


@dataclass
class PhaseEntry:
    number: int
    name: str
    layer: str
    purpose: str
    inputs: List[str]
    outputs: List[str]
    status: str            # ACTIVE | CONDITIONAL | STUB | PLANNED
    testable: bool
    toggleable: bool
    failure_mode: str
    success_criterion: str


PHASE_REGISTRY: List[PhaseEntry] = [
    PhaseEntry(
        number=27, name="Fuzzy Membership Engine", layer="L5",
        purpose="تبدیل مقدار خام (net_score) به درجه‌ی عضویت در چند اصطلاح زبانی هم‌زمان",
        inputs=["net_score (float, -1..+1)"],
        outputs=["Dict[str, float] درجه‌ی عضویت هر Term"],
        status="ACTIVE", testable=True, toggleable=True,
        failure_mode="اگر مرزهای Term اشتباه کالیبره شوند، درجه‌ها بی‌معنی می‌شوند (نه کرش)",
        success_criterion="مجموع درجه‌ها در نواحی هم‌پوشان >0 برای حداقل ۲ Term",
    ),
    PhaseEntry(
        number=28, name="Fuzzy Linguistic Variables", layer="L5",
        purpose="نگهداری مجموعه‌ی Termهای یک Feature (weak/moderate/strong/extreme)",
        inputs=["پارامترهای مرزی از settings.py"],
        outputs=["LinguisticVariable با ۴ Term"],
        status="ACTIVE", testable=True, toggleable=True,
        failure_mode="Term تعریف‌نشده -> fuzzify مقدار 0.0 برمی‌گرداند (نه خطا)",
        success_criterion="dominant_term برای مقادیر مرزی شناخته‌شده (0.0, 0.5, 1.0) صحیح باشد",
    ),
    PhaseEntry(
        number=39, name="Fuzzy Rule Base", layer="L6",
        purpose="نگاشت هر Term به یک خروجی singleton (trade_permission)",
        inputs=["FuzzyRule list"],
        outputs=["قابل گسترش با افزودن Rule جدید بدون تغییر inference.py"],
        status="ACTIVE", testable=True, toggleable=False,
        failure_mode="Rule بدون antecedent_term معتبر -> هیچ‌وقت فعال نمی‌شود (خاموش، نه کرش)",
        success_criterion="R04 (extreme) خروجی singleton پایین‌تر از R03 (strong) داشته باشد",
    ),
    PhaseEntry(
        number=40, name="Rule Weighting", layer="L6",
        purpose="وزن قابل‌تنظیم هر Rule",
        inputs=["FuzzyRule.weight"],
        outputs=["firing_strength = membership_degree × weight"],
        status="ACTIVE", testable=True, toggleable=True,
        failure_mode="وزن صفر -> Rule عملاً خاموش می‌شود",
        success_criterion="تغییر وزن یک Rule، trade_permission_score نهایی را متناسب تغییر دهد",
    ),
    PhaseEntry(
        number=41, name="Rule Conflict Resolution", layer="L6",
        purpose="مدیریت تضاد بین Ruleهای هم‌زمان فعال",
        inputs=["firing_strengths"],
        outputs=["-"],
        status="PLANNED",   # در این نسخه‌ی حداقلی، هر Rule فقط یک antecedent
                            # متفاوت دارد، پس تضاد واقعی رخ نمی‌دهد؛ وقتی
                            # Ruleهای چندمتغیره اضافه شوند لازم می‌شود.
        testable=False, toggleable=False,
        failure_mode="-", success_criterion="-",
    ),
    PhaseEntry(
        number=42, name="Fuzzy Inference Engine (Sugeno)", layer="L6",
        purpose="اجرای کامل fuzzify -> rule evaluation -> aggregation -> defuzzify",
        inputs=["net_score"],
        outputs=["FuzzySignalReport"],
        status="ACTIVE", testable=True, toggleable=True,
        failure_mode="مجموع firing=0 -> trade_permission_score=0 (رفتار ایمن پیش‌فرض: عدم‌معامله)",
        success_criterion="خروجی روی net_score=0.70 (مرز قدیمی Exhaustion) پیوسته باشد، نه جهش ناگهانی",
    ),
    PhaseEntry(
        number=43, name="Fuzzy Aggregation", layer="L6",
        purpose="ترکیب قدرت فعال‌شدن همه‌ی Ruleها قبل از Defuzzification",
        inputs=["rule_firing_strengths"], outputs=["مجموع وزن‌دار"],
        status="ACTIVE", testable=True, toggleable=False,
        failure_mode="-", success_criterion="-",
    ),
    PhaseEntry(
        number=44, name="Defuzzification (Sugeno Weighted Average)", layer="L6",
        purpose="تبدیل خروجی فازی به یک عدد قطعی (trade_permission_score، 0..100)",
        inputs=["firing_strengths", "output_singletons"],
        outputs=["trade_permission_score (float)"],
        status="ACTIVE", testable=True, toggleable=False,
        failure_mode="-", success_criterion="مقدار همیشه در بازه‌ی [0,100] بماند",
    ),
]


def get_phase(number: int) -> PhaseEntry:
    for p in PHASE_REGISTRY:
        if p.number == number:
            return p
    raise KeyError(f"Phase {number} در Registry ثبت نشده")
