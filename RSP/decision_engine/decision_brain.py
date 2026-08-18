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
from RSP.regime_engine.regime_engine import RegimeReport, detect_regime
from RSP.signal_fusion.fusion_engine import FusionReport, fuse_signals
from RSP.multi_timeframe.mtf_brain import MTFReport, analyze_mtf
from RSP.signal_engine.confluence import ConfluenceReport, analyze_confluence
from RSP.contradiction_engine.contradiction_engine import ContradictionReport, detect_contradictions
from RSP.confidence_engine.confidence_engine import ConfidenceReport, calculate_confidence
from RSP.preprocessing.quality_engine import check_quality
from RSP.fuzzy_core.inference import evaluate_signal_strength, FuzzySignalReport


@dataclass
class Decision:
    action: str = "NO_TRADE"     # BUY | SELL | HOLD | WAIT | NO_TRADE
    why: List[str] = field(default_factory=list)
    why_not_opposite: List[str] = field(default_factory=list)
    invalidation: List[str] = field(default_factory=list)
    missing_confirmation: List[str] = field(default_factory=list)
    fuzzy_report: Optional[FuzzySignalReport] = None
    # FIX v2.1: added so callers (backtest_engine.py) don't need to
    # recompute the same reports twice, and so trade records can carry a
    # confidence/quality figure — these were being read off Decision before
    # anything ever set them.
    confidence: float = 0.0
    trade_quality: float = 0.0
    fusion: Optional[FusionReport] = None
    mtf: Optional[MTFReport] = None
    contradiction: Optional[ContradictionReport] = None
    confidence_report: Optional[ConfidenceReport] = None


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

    # --- گارد ۲.۶: STRONG_REGIME_ONLY_MODE (آزمایشی) — فقط دو رژیمی که در
    # داده‌ی واقعی بهترین عملکرد رو داشتن (STRONG_UPTREND/STRONG_DOWNTREND)
    # مجاز به معامله‌ان. اگه فعال باشه، خیلی سخت‌گیرانه‌تر از گارد RANGE عمل
    # می‌کنه چون کل رژیم‌های میانه (UPTREND, WEAK_*, DOWNTREND, ...) رو هم می‌بنده.
    if settings.STRONG_REGIME_ONLY_MODE and regime.regime not in ("STRONG_UPTREND", "STRONG_DOWNTREND"):
        d.action = "NO_TRADE"
        d.why.append(f"STRONG_REGIME_ONLY_MODE فعال است و رژیم فعلی ({regime.regime}) "
                      f"جزو دو رژیم مجاز (STRONG_UPTREND/STRONG_DOWNTREND) نیست")
        d.missing_confirmation.append("رسیدن رژیم به STRONG_UPTREND یا STRONG_DOWNTREND")
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

    if settings.FUZZY_ENGINE_ENABLED:
        # مسیر فازی (Phase 27-44، نسخه‌ی حداقلی): به‌جای دو آستانه‌ی سخت
        # جداگانه (۰.۲۰ برای ورود و ۰.۷۰ برای Exhaustion)، یک پایپ‌لاین
        # فازی واحد که هر دو اثر را با گذار نرم پوشش می‌دهد.
        fuzzy = evaluate_signal_strength(net)
        d.fuzzy_report = fuzzy

        if net > 0 and mtf.entry_bias != "DOWN":
            candidate = "BUY"
        elif net < 0 and mtf.entry_bias != "UP":
            candidate = "SELL"
        elif abs(net) < 1e-9:
            candidate = "HOLD"
        else:
            candidate = "WAIT"

        if candidate in ("BUY", "SELL") and fuzzy.trade_permission_score >= settings.FUZZY_TRADE_PERMISSION_MIN:
            d.action = candidate
            evidence = fusion.bullish_evidence if candidate == "BUY" else fusion.bearish_evidence
            opposite_evidence = fusion.bearish_evidence if candidate == "BUY" else fusion.bullish_evidence
            d.why.append(f"[FUZZY] net_score={net:+.2f} (term غالب={fuzzy.dominant_term}, "
                          f"trade_permission={fuzzy.trade_permission_score}/{settings.FUZZY_TRADE_PERMISSION_MIN}) "
                          f"Rules فعال: {', '.join(fuzzy.active_rules)}")
            d.why.extend(evidence[:3])
            if opposite_evidence:
                d.why_not_opposite.append("شواهد مخالف باقیمانده: " + "؛ ".join(opposite_evidence[:2]))
        elif candidate in ("BUY", "SELL"):
            d.action = "WAIT"
            d.why.append(f"[FUZZY] net_score={net:+.2f} جهت‌دار است اما trade_permission="
                          f"{fuzzy.trade_permission_score} کمتر از آستانه‌ی {settings.FUZZY_TRADE_PERMISSION_MIN} "
                          f"(term غالب={fuzzy.dominant_term})")
            d.missing_confirmation.append("افزایش trade_permission_score (سیگنال قوی‌تر یا خارج از ناحیه‌ی افراطی)")
        elif candidate == "HOLD":
            d.action = "HOLD"
            d.why.append(f"[FUZZY] net_score={net:+.2f} صفر - نه شواهد صعودی نه نزولی")
        else:
            d.action = "WAIT"
            d.why.append(f"[FUZZY] net_score={net:+.2f} جهت‌دار است اما تایم‌فریم ورود ({mtf.entry_bias}) هم‌جهت نیست")
            d.missing_confirmation.append("هم‌جهت‌شدن تایم‌فریم پایین (15M) با جهت غالب")

        return d

    # --- مسیر Crisp (پیش‌فرض، رفتار قدیمی - وقتی FUZZY_ENGINE_ENABLED=False) ---
    if net > 0.2 and mtf.entry_bias != "DOWN":
        d.action = "BUY"
        d.why.append(f"net_score={net:+.2f} صعودی، تایم‌فریم ورود ({mtf.entry_bias}) در تضاد نیست")
        d.why.extend(fusion.bullish_evidence[:3])
        d.why_not_opposite.append("شواهد نزولی به‌اندازه‌ی کافی قوی/هم‌جهت نبودند تا SELL توجیه شود")
        if fusion.bearish_evidence:
            d.why_not_opposite.append("شواهد نزولی باقیمانده: " + "؛ ".join(fusion.bearish_evidence[:2]))
    elif net < -0.2 and mtf.entry_bias != "UP":
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

    # --- فیلتر Exhaustion (crisp، فقط وقتی FUZZY_ENGINE_ENABLED=False فعال است) ---
    # طبق داده‌ی واقعی، معاملاتی با net_score خیلی افراطی (اجماع خیلی قوی همه‌ی
    # اندیکاتورها) دو بار پشت‌سرهم win_rate پایین‌تری داشتند - فرضیه: وقتی
    # هماهنگی شواهد به این اندازه کامل است، حرکت احتمالاً به انتها نزدیک است،
    # نه ابتدا. به‌جای اعتماد بیشتر، این‌جا محتاط‌تر می‌شویم.
    if settings.EXHAUSTION_FILTER_ENABLED and d.action in ("BUY", "SELL") \
            and abs(net) >= settings.EXHAUSTION_NET_SCORE_THRESHOLD:
        original_action = d.action
        d.action = "WAIT"
        d.why.append(f"EXHAUSTION FILTER: net_score={net:+.2f} از آستانه‌ی "
                      f"{settings.EXHAUSTION_NET_SCORE_THRESHOLD} فراتر رفته - اجماع بیش‌ازحد کامل "
                      f"شواهد می‌تواند نشانه‌ی انتهای حرکت باشد، نه ابتدای آن "
                      f"(در غیر این صورت تصمیم {original_action} بود)")
        d.missing_confirmation.append("کمی خنک‌شدن net_score یا پولبک قبل از ورود")
        return d

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


# ---------------------------------------------------------------------------
# FIX v2.1 — NEW: make_decision() orchestrator
# ---------------------------------------------------------------------------
# backtest_engine.py (and, implicitly, the documented main.py flow) called
# `make_decision(known_bars, regime)` as if it already existed. It never
# did — only decide() existed, with a completely different signature
# (regime, fusion, mtf, contradiction, confidence, data_quality_ok). Nothing
# in the codebase ever built those five reports and called decide() for the
# backtest loop. This wires them together in the same order RSP/main.py's
# run_analysis() uses for its live one-shot analysis:
#   check_quality -> analyze_confluence -> analyze_mtf -> fuse_signals
#   -> detect_contradictions -> calculate_confidence -> decide
def make_decision(known_bars: dict, regime: RegimeReport) -> Decision:
    base_df = known_bars.get("15M") if known_bars else None
    if base_df is None or base_df.empty or regime is None:
        d = Decision()
        d.action = "NO_TRADE"
        d.why.append("داده‌ی 15M یا رژیم در دسترس نیست")
        return d

    data_quality = check_quality(base_df, "15M")
    confluence = analyze_confluence(base_df, regime)
    mtf = analyze_mtf(known_bars)
    fusion = fuse_signals(regime, confluence, mtf)
    contradiction = detect_contradictions(fusion, mtf)
    # risk_plan isn't known yet at this point in the pipeline (it depends on
    # the action this very call is about to decide) — calculate_confidence
    # already treats a missing risk_plan as a neutral 50.0 component, so we
    # pass None here, matching RSP/main.py's own ordering.
    confidence = calculate_confidence(fusion, mtf, data_quality, None, contradiction, regime)

    d = decide(regime, fusion, mtf, contradiction, confidence, data_quality.quality_ok)
    d.confidence = confidence.confidence
    d.fusion = fusion
    d.mtf = mtf
    d.contradiction = contradiction
    d.confidence_report = confidence
    return d
