"""
RSP — confidence_engine/confidence_engine.py  (Phase 12: CONFIDENCE ENGINE)

طبق اسپک: Confidence یعنی «میزان هماهنگی شواهد موجود»، نه احتمال سود.
از عوامل: Signal Agreement, MTF Agreement, Regime Stability (proxy با
عدم CONFLICT ساختاری), Data Quality, Risk/Reward (از بیرون تزریق می‌شود
چون بعد از Risk Engine مشخص می‌شود)، Volatility.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from RSP.signal_fusion.fusion_engine import FusionReport
from RSP.multi_timeframe.mtf_brain import MTFReport
from RSP.contradiction_engine.contradiction_engine import ContradictionReport


@dataclass
class ConfidenceReport:
    confidence: float = 0.0     # 0..100
    components: dict = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)


def compute_confidence(fusion: FusionReport, mtf: MTFReport, contradiction: ContradictionReport,
                        data_quality_score: float, atr_pct: float,
                        risk_reward: Optional[float] = None) -> ConfidenceReport:
    report = ConfidenceReport()

    # 1) Signal Agreement: هرچه net_score قوی‌تر (نزدیک ±1) و شواهد متناقض کمتر
    agreement_component = abs(fusion.net_score) * 100
    agreement_component -= contradiction.conflict_ratio * 40
    agreement_component = max(0.0, min(100.0, agreement_component))

    # 2) MTF Agreement
    mtf_component = (abs(mtf.consensus_score) * 100) if mtf.aligned else max(0.0, abs(mtf.consensus_score) * 50)

    # 3) Regime/Structural Stability proxy: نبود تضاد ساختاری
    stability_component = 100.0 if not contradiction.conflict_detected else 40.0

    # 4) Data Quality (از preprocessing می‌آید، 0..100)
    quality_component = max(0.0, min(100.0, data_quality_score))

    # 5) Volatility penalty: نوسان خیلی بالا اطمینان را کم می‌کند
    if atr_pct > 6.0:
        volatility_component = 30.0
    elif atr_pct > 4.0:
        volatility_component = 60.0
    else:
        volatility_component = 90.0

    # 6) Risk/Reward (اختیاری - اگر هنوز محاسبه نشده، خنثی می‌گیریم)
    if risk_reward is None:
        rr_component = 70.0
    else:
        rr_component = min(100.0, max(0.0, (risk_reward / 3.0) * 100))

    # وزن‌ها: قبلاً stability/data_quality/volatility/risk_reward جمعاً 50% وزن داشتند
    # در حالی‌که برای معاملاتی که واقعاً اجرا می‌شوند (رد شده از گاردهای قبلی) این
    # چهار مقدار عملاً همیشه ثابت‌اند (stability=100 چون conflict_detected از قبل
    # فیلتر شده، data_quality~100 چون داده‌ی KuCoin تمیز است، volatility=90 چون
    # آستانه‌های 4%/6% برای ATR واقعی 15M که ~0.1-0.4% است هرگز رد نمی‌شوند،
    # risk_reward~66.7 چون RR ساختاری همیشه نزدیک TAKE_PROFIT_RR_TARGET است).
    # این باعث می‌شد confidence عملاً بدون توجه به کیفیت واقعی معامله همیشه حدود
    # همون کف ثابت باشد. وزن اکنون روی دو مؤلفه‌ای متمرکز شده که واقعاً بین
    # معاملات فرق می‌کنند: signal_agreement و mtf_agreement.
    weights = {
        "signal_agreement": 0.55,
        "mtf_agreement": 0.30,
        "stability": 0.03,
        "data_quality": 0.05,
        "volatility": 0.02,
        "risk_reward": 0.05,
    }
    components = {
        "signal_agreement": agreement_component,
        "mtf_agreement": mtf_component,
        "stability": stability_component,
        "data_quality": quality_component,
        "volatility": volatility_component,
        "risk_reward": rr_component,
    }
    report.components = {k: round(v, 1) for k, v in components.items()}

    confidence = sum(components[k] * weights[k] for k in weights)
    report.confidence = round(max(0.0, min(100.0, confidence)), 1)

    if contradiction.conflict_detected:
        report.notes.append("Confidence به‌خاطر CONFLICT DETECTED کاهش یافته است")
    if data_quality_score < 60:
        report.notes.append("کیفیت داده پایین است - Confidence قابل‌اعتماد نیست")

    return report
