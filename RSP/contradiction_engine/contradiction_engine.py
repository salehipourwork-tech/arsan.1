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
    # فقط برای مصرف feature/fuzzy-scoring (نه گیت‌گذاری Crisp): سیگنال پیوسته‌ی
    # قدرت اجماع، مستقل از threshold گسسته‌ی conflict_detected. این فیلد هیچ
    # اثری روی منطق گیت بالا ندارد (که همچنان فقط conflict_ratio/mtf_disagreement/
    # net_score را در سه شرط OR بالا مصرف می‌کند).
    net_score: float = 0.0


def detect_contradictions(fusion: FusionReport, mtf: MTFReport) -> ContradictionReport:
    report = ContradictionReport()

    total_evidence = len(fusion.bullish_evidence) + len(fusion.bearish_evidence) + len(fusion.neutral_evidence)
    conflicting = len(fusion.conflicting_evidence)
    report.conflict_ratio = round(conflicting / total_evidence, 3) if total_evidence else 0.0
    report.net_score = fusion.net_score

    if fusion.bullish_evidence and fusion.bearish_evidence:
        # هر دو جهت شواهد معتبر دارند
        smaller = min(len(fusion.bullish_evidence), len(fusion.bearish_evidence))
        larger = max(len(fusion.bullish_evidence), len(fusion.bearish_evidence))
        if larger and smaller / larger >= 0.4:
            report.reasons.append(
                f"شواهد صعودی ({len(fusion.bullish_evidence)}) و نزولی ({len(fusion.bearish_evidence)}) هر دو قابل توجه‌اند")

    # FIX v2.1: was `not mtf.aligned`, which requires an EXACT 3-way match
    # of trend labels across 1D/4H/15M — statistically close to impossible
    # given the timeframes move at very different speeds (a 15M pullback
    # inside a genuine 1D/4H uptrend is normal market behavior, not a
    # contradiction). This made mtf_disagreement true on ~every single bar
    # (confirmed via RSP/diagnose_pipeline.py: 100% of decisions were
    # rejected here, 0 ever reached the BUY/SELL logic, on 90 days of data
    # across three distinct trend/range/downtrend regimes). The module's
    # own docstring says this should be threshold-based ("اگر تضاد از یک
    # آستانه بیشتر شود"), and mtf_brain.py already computes a graduated
    # divergence_score for exactly this (0.8 for a direct 1D vs 15M
    # opposite-direction conflict, 0.5 for a 1D vs 4H conflict, 0 when
    # there's no genuine directional conflict) — using that instead of
    # exact-equality preserves the intended "real disagreement" signal
    # without firing on ordinary NEUTRAL/lag noise between timeframes.
    if mtf.divergence_score > 0:
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
