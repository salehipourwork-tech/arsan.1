"""
RSP — contradiction_engine/contradiction_engine.py  (Phase 10: CONTRADICTION ENGINE)

تشخیص تضاد بین شواهد. اگر تضاد از یک آستانه بیشتر شود، سیستم نباید به‌زور
BUY/SELL بدهد؛ باید CONFLICT_DETECTED گزارش کند تا decision_engine بتواند
WAIT یا NO_TRADE بدهد.
"""

from dataclasses import dataclass, field
from typing import List

from RSP.config import settings
from RSP.signal_fusion.fusion_engine import FusionReport
from RSP.multi_timeframe.mtf_brain import MTFReport


@dataclass
class ContradictionReport:
    conflict_detected: bool = False
    conflict_ratio: float = 0.0
    reasons: List[str] = field(default_factory=list)
    mtf_disagreement: bool = False
    severity: str = "NONE"   # NONE | MODERATE | SEVERE


def detect_contradictions(fusion: FusionReport, mtf: MTFReport) -> ContradictionReport:
    report = ContradictionReport()

    total_evidence = len(fusion.bullish_evidence) + len(fusion.bearish_evidence) + len(fusion.neutral_evidence)
    conflicting = len(fusion.conflicting_evidence)
    report.conflict_ratio = round(conflicting / total_evidence, 3) if total_evidence else 0.0

    if fusion.bullish_evidence and fusion.bearish_evidence:
        # هر دو جهت شواهد معتبر دارند
        smaller = min(len(fusion.bullish_evidence), len(fusion.bearish_evidence))
        larger = max(len(fusion.bullish_evidence), len(fusion.bearish_evidence))
        if larger and smaller / larger >= 0.4:
            report.reasons.append(
                f"شواهد صعودی ({len(fusion.bullish_evidence)}) و نزولی ({len(fusion.bearish_evidence)}) هر دو قابل توجه‌اند")

    if not mtf.aligned:
        report.mtf_disagreement = True
        report.reasons.append(f"عدم اجماع بین تایم‌فریم‌ها: {mtf.summary}")

    if fusion.conflicting_evidence:
        report.reasons.extend(fusion.conflicting_evidence)

    report.conflict_detected = (
        report.conflict_ratio >= settings.CONTRADICTION_BLOCK_THRESHOLD
        or report.mtf_disagreement
        or bool(report.reasons and abs(fusion.net_score) < 0.15)
    )

    # --- Severity (قدم اول درخواستی: فقط این بخش، بدون دست‌زدن به رژیم RANGE) ---
    # "شدید" یعنی یا نسبت تناقض خیلی بالاست، یا چند نشانه‌ی مستقل تناقض هم‌زمان
    # رخ داده‌اند (مثلاً هم عدم‌اجماع تایم‌فریمی و هم شواهد متعارض) — نه صرفاً
    # یک نشانه‌ی مرزی. این تمایز باعث می‌شود NO_TRADE فقط برای تضاد واقعاً
    # جدی صادر شود، نه هر بار که آستانه‌ی WAIT رد شود.
    if not report.conflict_detected:
        report.severity = "NONE"
    else:
        severe_by_ratio = report.conflict_ratio >= settings.CONTRADICTION_SEVERE_THRESHOLD
        severe_by_multiple_signals = report.mtf_disagreement and len(report.reasons) >= 2
        report.severity = "SEVERE" if (severe_by_ratio or severe_by_multiple_signals) else "MODERATE"

    return report
