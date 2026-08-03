"""
RSP — decision_engine/decision_brain.py  (Phase 11: DECISION BRAIN)

تصمیم نهایی: BUY / SELL / HOLD / WAIT / NO_TRADE

هر تصمیم باید Explainable باشد: WHY, WHY_NOT_OPPOSITE, INVALIDATION,
MISSING_CONFIRMATION (طبق اسپک - این‌ها همینجا تولید می‌شوند، سپس
reporting/explainability.py آن‌ها را به گزارش انسانی تبدیل می‌کند).
"""

from dataclasses import dataclass, field
from typing import List, Optional

from RSP.config import settings
from RSP.regime_engine.regime_engine import RegimeReport
from RSP.signal_fusion.fusion_engine import FusionReport
from RSP.multi_timeframe.mtf_brain import MTFReport
from RSP.contradiction_engine.contradiction_engine import ContradictionReport
from RSP.confidence_engine.confidence_engine import ConfidenceReport


@dataclass
class Decision:
    action: str = "NO_TRADE"     # BUY | SELL | HOLD | WAIT | NO_TRADE
    why: List[str] = field(default_factory=list)
    why_not_opposite: List[str] = field(default_factory=list)
    invalidation: List[str] = field(default_factory=list)
    missing_confirmation: List[str] = field(default_factory=list)


def decide(regime: RegimeReport, fusion: FusionReport, mtf: MTFReport,
           contradiction: ContradictionReport, confidence: ConfidenceReport,
           data_quality_ok: bool) -> Decision:
    d = Decision()

    # --- گارد ۱: کیفیت داده ---
    if not data_quality_ok:
        d.action = "NO_TRADE"
        d.why.append("کیفیت داده کافی برای تصمیم‌گیری نیست (Data Quality Engine)")
        d.missing_confirmation.append("داده‌ی تمیزتر / بازه‌ی زمانی کامل‌تر")
        return d

    # --- گارد ۲: عدم وجود استراتژی سازگار با رژیم فعلی ---
    if not regime.compatible_strategies:
        d.action = "NO_TRADE" if regime.regime in ("CRASH", "FAKE_BREAKOUT") else "WAIT"
        d.why.append(f"رژیم بازار «{regime.regime}» هیچ استراتژی سازگاری در کتابخانه ندارد")
        d.missing_confirmation.append("تغییر رژیم به یکی از حالات قابل‌معامله")
        return d

    # --- گارد ۲.۵: رژیم RANGE — طبق شواهد بک‌تست واقعی، این رژیم به‌طور پایدار
    # زیر نقطه‌ی سربه‌سر عمل می‌کند (نه فقط پرتعدادترین، واقعاً بدترین رژیم است).
    if regime.regime == "RANGE" and settings.RANGE_REGIME_NO_TRADE:
        d.action = "NO_TRADE"
        d.why.append("رژیم RANGE طبق شواهد بک‌تست به‌طور پایدار زیر نقطه‌ی سربه‌سر عمل می‌کند؛ "
                      "معامله در این رژیم فعلاً غیرفعال است (RANGE_REGIME_NO_TRADE)")
        d.missing_confirmation.append("تغییر رژیم به یکی از حالات ترند/شکست، یا بازطراحی استراتژی اختصاصی RANGE")
        return d

    # --- گارد ۳: تضاد شواهد ---
    if contradiction.conflict_detected:
        if contradiction.severity == "SEVERE":
            # تضاد شدید (چند نشانه‌ی مستقل هم‌زمان، یا نسبت تناقض خیلی بالا):
            # NO_TRADE به‌جای WAIT — این ستاپ اصلاً معتبر نیست، نه اینکه فقط
            # "فعلاً" منتظر بمانیم.
            d.action = "NO_TRADE"
            d.why.append("SEVERE CONFLICT: " + "؛ ".join(contradiction.reasons[:3]))
            d.why_not_opposite.append("تضاد شواهد به‌قدری جدی است که نه جهت و نه نقطه‌ی مقابلش قابل اتکا نیست")
            d.missing_confirmation.append("کاهش چشمگیر تضاد شواهد قبل از هر تصمیمی")
            d.invalidation.append("تا رفع کامل تضاد شواهد، هیچ معامله‌ای در این نماد گرفته نشود")
        else:
            d.action = "WAIT"
            d.why.append("CONFLICT DETECTED: " + "؛ ".join(contradiction.reasons[:3]))
            d.why_not_opposite.append("جهت غالب به‌اندازه‌ی کافی واضح نیست تا نقطه‌ی مقابل رد شود")
            d.missing_confirmation.append("هم‌جهت‌شدن تایم‌فریم‌ها یا کاهش شواهد متناقض")
            d.invalidation.append("در صورت تشدید تضاد یا شکست سطح کلیدی، از بازار دور بمان")
        return d

    # --- گارد ۴: اطمینان پایین ---
    if confidence.confidence < settings.MIN_CONFIDENCE_TO_TRADE:
        d.action = "WAIT"
        d.why.append(f"Confidence={confidence.confidence} کمتر از آستانه‌ی {settings.MIN_CONFIDENCE_TO_TRADE}")
        d.missing_confirmation.append("افزایش هماهنگی شواهد یا بهبود کیفیت داده")
        return d

    # --- تصمیم اصلی بر اساس net_score و اجماع MTF ---
    net = fusion.net_score
    if net > 0.2 and mtf.entry_bias != "BEARISH":
        d.action = "BUY"
        d.why.append(f"net_score={net:+.2f} صعودی، تایم‌فریم ورود ({mtf.entry_bias}) در تضاد نیست")
        d.why.extend(fusion.bullish_evidence[:3])
        d.why_not_opposite.append("شواهد نزولی به‌اندازه‌ی کافی قوی/هم‌جهت نبودند تا SELL توجیه شود")
        if fusion.bearish_evidence:
            d.why_not_opposite.append("شواهد نزولی باقیمانده: " + "؛ ".join(fusion.bearish_evidence[:2]))
    elif net < -0.2 and mtf.entry_bias != "BULLISH":
        d.action = "SELL"
        d.why.append(f"net_score={net:+.2f} نزولی، تایم‌فریم ورود ({mtf.entry_bias}) در تضاد نیست")
        d.why.extend(fusion.bearish_evidence[:3])
        d.why_not_opposite.append("شواهد صعودی به‌اندازه‌ی کافی قوی/هم‌جهت نبودند تا BUY توجیه شود")
        if fusion.bullish_evidence:
            d.why_not_opposite.append("شواهد صعودی باقیمانده: " + "؛ ".join(fusion.bullish_evidence[:2]))
    elif abs(net) <= 0.2:
        d.action = "HOLD"
        d.why.append(f"net_score={net:+.2f} نزدیک صفر - نه شواهد کافی برای BUY نه برای SELL")
        d.missing_confirmation.append("شکست واضح‌تر تعادل شواهد به یک سمت")
    else:
        d.action = "WAIT"
        d.why.append(f"net_score={net:+.2f} جهت‌دار است اما تایم‌فریم ورود ({mtf.entry_bias}) هم‌جهت نیست")
        d.missing_confirmation.append("هم‌جهت‌شدن تایم‌فریم پایین (15M) با جهت غالب")

    # --- Invalidation عمومی ---
    if d.action == "BUY":
        d.invalidation.append("شکست پایین‌ترین سطح حمایت اخیر یا CHOCH نزولی")
    elif d.action == "SELL":
        d.invalidation.append("شکست بالاترین سطح مقاومت اخیر یا CHOCH صعودی")

    if not fusion.bullish_evidence and d.action == "BUY":
        d.missing_confirmation.append("شواهد صعودی مستقل بیشتر")
    if not fusion.bearish_evidence and d.action == "SELL":
        d.missing_confirmation.append("شواهد نزولی مستقل بیشتر")

    return d
