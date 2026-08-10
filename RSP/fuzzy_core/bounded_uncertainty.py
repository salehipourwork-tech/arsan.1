"""
RSP — fuzzy_core/bounded_uncertainty.py

Bounded Uncertainty / Interval-Based Scoring.

وقتی یک ورودی خام را نمی‌توان با اطمینان کامل به یک عدد واحد نگاشت کرد
(مثلاً ATR% در برابر توزیع نسبی خودش، در لحظه‌ای که تاریخچه‌ی کافی هنوز
جمع نشده)، این ماژول به‌جای تحمیل یک مقدار ثابت، یک BoundedScore برمی‌گرداند:

    value       بهترین برآورد نقطه‌ای (0..1)
    lower/upper بازه‌ی اطمینان تجربی (Wald interval روی percentile rank)
    confidence  0..1 — بر اساس اندازه‌ی نمونه‌ی تاریخی موجود در لحظه‌ی تصمیم
    n_samples   تعداد نمونه‌ای که این برآورد رویش ساخته شده

منبع bounds: empirical quantile rank درون یک پنجره‌ی تاریخی که caller
می‌فرستد — نه یک بازه‌ی دلخواه.

قانون ضد Leakage: این ماژول هیچ داده‌ای را خودش نمی‌گیرد یا کش نمی‌کند.
مسئولیت caller است که فقط history تا لحظه‌ی تصمیم (walk-forward-safe،
یعنی هیچ داده‌ای از آینده‌ی همان نماد) پاس بدهد. به همین دلیل هم در
backtest/training export و هم در تحلیل زنده، رفتار یکسان و بدون نشت
اطلاعات آینده خواهد بود، به شرط آنکه caller این قانون را رعایت کند.
"""
from dataclasses import dataclass
from typing import Optional, Sequence
import math


@dataclass
class BoundedScore:
    value: float       # بهترین برآورد نقطه‌ای (0..1) — percentile rank
    lower: float        # کران پایین بازه‌ی اطمینان (~90%)
    upper: float        # کران بالای بازه‌ی اطمینان (~90%)
    confidence: float   # 0..1 — هرچه نمونه بیشتر، بالاتر
    n_samples: int

    def as_dict(self) -> dict:
        return {
            "value": self.value, "lower": self.lower, "upper": self.upper,
            "confidence": self.confidence, "n_samples": self.n_samples,
        }


def rolling_percentile_score(
    current_value: float,
    history: Optional[Sequence[float]],
    min_samples: int = 30,
    target_samples: int = 300,
    z: float = 1.645,  # ~90% Wald CI روی یک نسبت
) -> Optional[BoundedScore]:
    """
    رتبه‌ی درصدی مقدار فعلی درون یک تاریخچه‌ی از پیش داده‌شده (فقط گذشته).

    اگر تعداد نمونه کمتر از min_samples باشد None برمی‌گرداند — caller باید
    در این حالت به یک فرمول fallback (مثلاً آستانه‌ی ثابت قدیمی) برگردد،
    به‌جای اینکه یک برآورد غیرقابل‌اتکا روی نمونه‌ی خیلی کوچک تحمیل شود.
    """
    if history is None:
        return None
    n = len(history)
    if n < min_samples:
        return None

    rank = sum(1 for v in history if v <= current_value) / n
    rank = max(0.0, min(1.0, rank))

    se = math.sqrt(max(rank * (1.0 - rank), 1e-6) / n)
    lower = max(0.0, rank - z * se)
    upper = min(1.0, rank + z * se)
    confidence = round(min(1.0, n / target_samples), 3)

    return BoundedScore(
        value=round(rank, 4), lower=round(lower, 4), upper=round(upper, 4),
        confidence=confidence, n_samples=n,
    )
