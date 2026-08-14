# id: RSP/fuzzy_core/quality_engines.py (Phases 29-38: Fuzzy Quality Engines)
#
# MODIFIED — Phase 2 Controlled Fix
# File changed: RSP/fuzzy_core/quality_engines.py
# Function changed: _raw_risk_quality (v2, not legacy, not bounded)
# Change: Removed ATR percentile dependency to eliminate redundancy with volatility_quality_v2
# Reason: Both risk_quality_v2 and volatility_quality_v2 used rolling_percentile_score(atr_pct, ...)
#         causing 80% of AHP weight to depend on the SAME underlying signal.
# Rollback: Restore original from git: git checkout RSP/fuzzy_core/quality_engines.py
#
# Every other function in this file is UNCHANGED.
"""
RSP — fuzzy_core/quality_engines.py (Phases 29-38: Fuzzy Quality Engines)

هر موتور کیفیت، ورودی‌های خام تحلیلی را می‌گیرد و آن‌ها را به
فضای فازی تبدیل می‌کند. خروجی هر کدام یک dict از درجه‌های عضویت است.

این موتورها «تفسیر» می‌کنند، نه «تصمیم». تصمیم در Decision Controller
اتفاق می‌افتد.
"""
from typing import Dict, Optional
import numpy as np

from RSP.fuzzy_core.membership import (
    get_quality_variable,
    LinguisticVariable,
)
from RSP.regime_engine.regime_engine import RegimeReport
from RSP.signal_engine.confluence import ConfluenceReport
from RSP.multi_timeframe.mtf_brain import MTFReport
from RSP.signal_fusion.fusion_engine import FusionReport
from RSP.contradiction_engine.contradiction_engine import ContradictionReport
from RSP.confidence_engine.confidence_engine import ConfidenceReport
from RSP.risk_engine.risk_engine import RiskPlan
from RSP.market_structure.structure_engine import StructureReport

# ---------------------------------------------------------------------------
# Helper: normalize any score to [0, 1] with clamping
# ---------------------------------------------------------------------------
def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, float(x)))

def _safe_ratio(numerator: float, denominator: float, default: float = 0.0) -> float:
    if denominator == 0 or not np.isfinite(denominator):
        return default
    return numerator / denominator

# =============================================================================
# Phase 29 — Fuzzy Trend Quality
# =============================================================================
def _raw_trend_quality(regime: RegimeReport, confluence: ConfluenceReport) -> float:
    # کالیبره‌شده با داده‌ی واقعی (fuzzy_training_export.py روی ETH/240d، n=2020 معامله‌ی
    # واقعی؛ امتیاز = ترکیب normalized(mean_pnl) و normalized(win_rate) به‌ازای هر رژیم).
    # قبلاً STRONG_UPTREND=0.90 (بالاترین) بود در حالی که در داده‌ی واقعی بدترین عملکرد
    # را داشت (win_rate=29.0%, mean_pnl=-0.310) — این خطای قطبیت اینجا اصلاح شده.
    # رژیم‌هایی که در داده‌ی معاملاتی واقعی نمونه‌ی کافی نداشتند (RANGE/TRANSITION/
    # RECOVERY/CRASH/HIGH_VOLATILITY/UNKNOWN) هنوز مقدار قبلی (حدس دامنه‌ای) را دارند —
    # علامت‌گذاری شده تا معلوم باشد کدام‌ها calibrated و کدام‌ها هنوز حدسی‌اند.
    regime_scores = {
        # --- calibrated from real ETH trade outcomes (n>=15 per regime) ---
        "WEAK_DOWNTREND": 0.90,   # n=237 win_rate=48.1% mean_pnl=+0.208 (بهترین)
        "UPTREND": 0.68,          # n=381 win_rate=43.6% mean_pnl=+0.048
        "LOW_VOLATILITY": 0.64,   # n=61  win_rate=44.3% mean_pnl=-0.019
        "STRONG_DOWNTREND": 0.57, # n=288 win_rate=39.9% mean_pnl=+0.002
        "WEAK_UPTREND": 0.47,     # n=269 win_rate=39.0% mean_pnl=-0.109
        "DOWNTREND": 0.41,        # n=590 win_rate=38.5% mean_pnl=-0.169
        "BREAKOUT": 0.15,         # n=11 (نمونه‌ی کم) win_rate=0.0% mean_pnl=-0.871
        "STRONG_UPTREND": 0.10,   # n=183 win_rate=29.0% mean_pnl=-0.310 (بدترین)
        # --- not yet seen in real trade data — کماکان حدس دامنه‌ای، نه کالیبره‌شده ---
        "BREAKDOWN": 0.60, "RECOVERY": 0.50, "CRASH": 0.10,
        "RANGE": 0.20, "TRANSITION": 0.15, "HIGH_VOLATILITY": 0.25,
        "UNKNOWN": 0.10,
    }
    base = regime_scores.get(regime.regime, 0.30)

    ema = next((r for r in confluence.readings if r.name == "EMA_CROSS"), None)
    sma = next((r for r in confluence.readings if r.name == "SMA_TREND"), None)
    adx = next((r for r in confluence.readings if r.name == "ADX"), None)

    aligned = 0
    bullish_regime = regime.regime in ("STRONG_UPTREND", "UPTREND", "WEAK_UPTREND", "BREAKOUT", "RECOVERY")
    bearish_regime = regime.regime in ("STRONG_DOWNTREND", "DOWNTREND", "WEAK_DOWNTREND", "BREAKDOWN", "CRASH")

    for r in [ema, sma]:
        if r and ((r.direction == "BULLISH" and bullish_regime) or (r.direction == "BEARISH" and bearish_regime)):
            aligned += 1
    if adx and adx.value >= 25:
        aligned += 1

    adjustment = 0.08 * aligned
    if base < 0.5:
        adjustment *= 0.5  # weak regimes can't be saved easily
    return _clamp01(base + adjustment)

def evaluate_trend_quality(regime: RegimeReport, confluence: ConfluenceReport) -> Dict[str, float]:
    """
    ورودی: Regime + Confluence
    خروجی: درجه‌های عضویت در {very_weak, weak, moderate, strong, very_strong}

    منطق:
    - رژیم‌های قوی روند (STRONG_UPTREND/DOWNTREND) -> strong
    - ADX بالا + EMA/SMA هم‌جهت -> bonus
    - TRANSITION/RANGE -> weak
    """
    var = get_quality_variable("trend_quality")
    if var is None:
        return {}
    return var.fuzzify(_raw_trend_quality(regime, confluence))

# =============================================================================
# Phase 30 — Fuzzy Momentum Quality
# =============================================================================
def _raw_momentum_quality(confluence: ConfluenceReport) -> Optional[float]:
    """None یعنی داده‌ی کافی نیست (fallback به fuzzify(0.30) در evaluate_*)."""
    rsi = next((r for r in confluence.readings if r.name == "RSI"), None)
    macd = next((r for r in confluence.readings if r.name == "MACD"), None)
    stoch = next((r for r in confluence.readings if r.name == "STOCH_RSI"), None)

    dirs = [r.direction for r in [rsi, macd, stoch] if r]
    if not dirs:
        return None

    bull = dirs.count("BULLISH")
    bear = dirs.count("BEARISH")
    agreement = max(bull, bear) / len(dirs)

    score = agreement * 0.8 + 0.1
    if confluence.momentum_state == "ACCELERATION":
        score += 0.12
    elif confluence.momentum_state == "WEAKENING":
        score -= 0.20
    if confluence.divergences:
        score -= 0.25
    return _clamp01(score)

def evaluate_momentum_quality(confluence: ConfluenceReport) -> Dict[str, float]:
    """
    ورودی: Confluence Report
    خروجی: fuzzy momentum quality

    منطق:
    - ACCELERATION + Agreement -> strong
    - WEAKENING -> weak
    - DIVERGENCE -> very_weak
    """
    var = get_quality_variable("momentum_quality")
    if var is None:
        return {}
    raw = _raw_momentum_quality(confluence)
    return var.fuzzify(0.30 if raw is None else raw)

# =============================================================================
# Phase 31 — Fuzzy Entry Quality
# =============================================================================
def _raw_entry_quality(mtf: MTFReport, structure: StructureReport) -> float:
    score = 0.50  # neutral start

    if mtf.aligned:
        score += 0.25
    if mtf.entry_bias in ("BULLISH", "BEARISH"):
        score += 0.10
    else:
        score -= 0.25

    if structure.last_structure_event in ("BOS_BULLISH", "BOS_BEARISH"):
        score += 0.15
    elif structure.last_structure_event in ("CHOCH_BULLISH", "CHOCH_BEARISH"):
        score += 0.10
    elif structure.pattern == "MIXED":
        score -= 0.10

    return _clamp01(score)

def evaluate_entry_quality(mtf: MTFReport, structure: StructureReport) -> Dict[str, float]:
    """
    ورودی: MTF + Market Structure
    خروجی: fuzzy entry quality

    منطق:
    - MTF aligned + entry_bias هم‌جهت -> strong
    - Structure BOS/CHoCH confirming -> strong
    - MTF disagreement -> weak
    """
    var = get_quality_variable("entry_quality")
    if var is None:
        return {}
    return var.fuzzify(_raw_entry_quality(mtf, structure))

# =============================================================================
# Phase 32 — Fuzzy Risk Quality (بازطراحی‌شده: percentile-based + بدون آستانه‌ی مرده)
# =============================================================================
def _raw_risk_quality_legacy(risk_plan: Optional[RiskPlan], atr_pct: float) -> float:
    """
    فرمول قدیمی (fallback وقتی تاریخچه‌ی ATR کافی نیست). روی داده‌ی واقعی این
    پروژه (ETH/15M) عملاً همیشه ثابت ۰.۷۵ می‌دهد، چون risk_reward طراحی‌شده
    همیشه دقیقاً ۲.۰ است و atr_pct هیچ‌وقت به آستانه‌ی ۴٪ نمی‌رسد — نگه داشته
    شده فقط برای رفتار یکسان وقتی history در دسترس نیست (مثلاً چند کندل اول).
    """
    if risk_plan is None or not risk_plan.valid:
        return 0.10

    rr = risk_plan.risk_reward or 0.0
    if rr >= 3.0:
        score = 0.95
    elif rr >= 2.0:
        score = 0.75 + (rr - 2.0) * 0.20
    elif rr >= 1.5:
        score = 0.50 + (rr - 1.5) * 0.50
    else:
        score = 0.20 + rr * 0.20

    if atr_pct > 6.0:
        score -= 0.15
    elif atr_pct > 4.0:
        score -= 0.08

    return _clamp01(score)

_REGIME_RISK_ADJUST = {
    # چقدر مدیریت ریسک در این رژیم «قابل‌اتکاتر»ه — رژیم‌های روند‌دار قوی
    # ریسک قابل‌پیش‌بینی‌تری دارند تا رنج/برک‌اوت. اعداد کوچک‌اند (± ۰.۱۰ سقف)
    # که فقط یک تعدیل باشند، نه محرک اصلی امتیاز.
    "STRONG_UPTREND": 0.05, "STRONG_DOWNTREND": 0.05,
    "UPTREND": 0.03, "DOWNTREND": 0.03,
    "WEAK_UPTREND": 0.0, "WEAK_DOWNTREND": 0.0,
    "LOW_VOLATILITY": 0.05, "HIGH_VOLATILITY": -0.10,
    "BREAKOUT": -0.05,
}

# ---------------------------------------------------------------------------
# MODIFIED FUNCTION — _raw_risk_quality (v2)
# ---------------------------------------------------------------------------
# CHANGE LOG:
#   Date: 2026-08-14
#   Phase: 2 Controlled Fix
#   Hypothesis: risk_quality_v2 and volatility_quality_v2 are redundant
#               because both use rolling_percentile_score(atr_pct, ...).
#               80% of AHP weight depends on the same underlying signal.
#   Fix: Removed ATR percentile dependency from risk_quality_v2.
#        Now risk_quality_v2 uses ONLY actual Risk/Reward from risk_plan.
#        This makes it independent from volatility_quality_v2.
#   Impact: AHP now receives two truly independent signals:
#           - trend_quality (directional information)
#           - risk_quality_v2 (actual R:R of the setup)
#           - volatility_quality_v2 (market volatility, separate)
#   Rollback: git checkout RSP/fuzzy_core/quality_engines.py
# ---------------------------------------------------------------------------
def _raw_risk_quality(risk_plan: Optional[RiskPlan], atr_pct: float,
                      atr_history: Optional[list] = None,
                      regime: Optional[RegimeReport] = None) -> float:
    """
    MODIFIED — Phase 2 Fix: Removed ATR percentile dependency.

    Root cause: risk_quality_v2 and volatility_quality_v2 both used
    rolling_percentile_score(atr_pct, ...) — 80% of AHP weight on the SAME
    underlying signal (ATR percentile), causing redundancy and score saturation.

    Fix: risk_quality_v2 now uses ONLY actual Risk/Reward from risk_plan,
    making it independent from volatility_quality_v2.

    ROLLBACK: git checkout RSP/fuzzy_core/quality_engines.py

    --- MODIFIED (R:R only, independent from volatility) ---
    Logic:
    - RR >= 3.0: excellent risk/reward setup → score 0.95
    - RR 2.0-3.0: good → score 0.75-0.95
    - RR 1.5-2.0: moderate → score 0.50-0.75
    - RR < 1.5: poor → score 0.20-0.50
    - Invalid risk_plan: score 0.10 (same as before)

    Regime adjustment kept but halved (was ±0.10 max, now ±0.05 max)
    to prevent regime guesswork from dominating the actual R:R signal.
    """
    if risk_plan is None or not risk_plan.valid:
        return 0.10

    rr = risk_plan.risk_reward or 0.0
    if rr >= 3.0:
        rr_score = 0.95
    elif rr >= 2.0:
        rr_score = 0.75 + (rr - 2.0) * 0.20
    elif rr >= 1.5:
        rr_score = 0.50 + (rr - 1.5) * 0.50
    else:
        rr_score = 0.20 + rr * 0.20

    # Regime adjustment: small modifier only (halved from original).
    # Rationale: regime calibration is ETH-only and 60% regimes are guessed;
    # it should not override the actual R:R signal.
    regime_adj = _REGIME_RISK_ADJUST.get(regime.regime, 0.0) * 0.5 if regime is not None else 0.0

    score = rr_score + regime_adj
    return _clamp01(score)

# ---------------------------------------------------------------------------
# END MODIFIED FUNCTION
# ---------------------------------------------------------------------------

def _raw_risk_quality_bounded(risk_plan: Optional[RiskPlan], atr_pct: float,
                              atr_history: Optional[list] = None,
                              regime: Optional[RegimeReport] = None):
    """نسخه‌ی Bounded Uncertainty: هم value و هم بازه‌ی اطمینان/confidence."""
    from RSP.fuzzy_core.bounded_uncertainty import rolling_percentile_score, BoundedScore
    from RSP.config import settings as _s
    value = _raw_risk_quality(risk_plan, atr_pct, atr_history, regime)
    pct = rolling_percentile_score(
        atr_pct, atr_history,
        min_samples=_s.RISK_QUALITY_PERCENTILE_MIN_SAMPLES,
        target_samples=_s.VOLATILITY_PERCENTILE_TARGET_SAMPLES,
    )
    if pct is None:
        # بدون تاریخچه‌ی کافی، بازه‌ی خیلی گسترده و confidence پایین گزارش می‌شود
        # (صادقانه: یعنی «نمی‌دانیم»، نه یک بازه‌ی دلخواه تنگ)
        return BoundedScore(value=round(value, 4), lower=0.0, upper=1.0,
                            confidence=0.0, n_samples=0 if not atr_history else len(atr_history))
    spread = pct.upper - pct.lower
    return BoundedScore(
        value=round(value, 4),
        lower=round(_clamp01(value - spread * 0.35), 4),
        upper=round(_clamp01(value + spread * 0.35), 4),
        confidence=pct.confidence, n_samples=pct.n_samples,
    )

def evaluate_risk_quality(risk_plan: Optional[RiskPlan], atr_pct: float,
                          atr_history: Optional[list] = None,
                          regime: Optional[RegimeReport] = None) -> Dict[str, float]:
    """
    ورودی: RiskPlan + ATR% (+ اختیاری: تاریخچه‌ی ATR برای percentile scoring،
    و regime برای تعدیل کوچک بر اساس نوع رژیم)
    خروجی: fuzzy risk quality

    منطق (بازطراحی‌شده): RR + رتبه‌ی نسبی ATR% درون تاریخچه‌ی خودش (نه آستانه‌ی
    مطلق مرده) + تعدیل کوچک رژیم. اگر atr_history داده نشود، به فرمول قدیمی
    (آستانه‌ی ثابت) برمی‌گردد — کاملاً backward-compatible.
    """
    var = get_quality_variable("risk_quality")
    if var is None:
        return {}
    return var.fuzzify(_raw_risk_quality(risk_plan, atr_pct, atr_history, regime))

# =============================================================================
# Phase 33 — Fuzzy Volatility Quality (بازطراحی‌شده: percentile-based)
# UNCHANGED — kept as-is for comparison with modified risk_quality
# =============================================================================
def _raw_volatility_quality_legacy(atr_pct: float, regime: RegimeReport) -> float:
    """
    فرمول قدیمی (fallback). جهت این فرمول («بدی» بالا وقتی ATR% بالا) روی
    ۲۰۴۹ رکورد واقعی تست شد و جهتش درست بود (correlation منفی معنادار با pnl،
    p<0.0001) — مشکل polarity نبود؛ مشکل این بود که آستانه‌های مطلق (۰.۵٪ تا
    ۶٪+) برای این نماد/تایم‌فریم خیلی بزرگ‌اند: ATR% واقعی این داده هیچ‌وقت از
    ۱.۹۳٪ رد نشد، پس ۷۳٪ رکوردها در ناحیه‌ی تخت "goodness=1.0" افتادند و امتیاز
    برای اکثر معاملات عملاً ثابت (بدون تفکیک‌پذیری) بود.
    """
    if atr_pct <= 0.5:
        goodness = 1.0
    elif atr_pct <= 1.5:
        goodness = 0.90 - (atr_pct - 0.5) * 0.10
    elif atr_pct <= 2.5:
        goodness = 0.80 - (atr_pct - 1.5) * 0.15
    elif atr_pct <= 4.0:
        goodness = 0.65 - (atr_pct - 2.5) * 0.10
    elif atr_pct <= 6.0:
        goodness = 0.50 - (atr_pct - 4.0) * 0.15
    else:
        goodness = 0.20 - min(0.15, (atr_pct - 6.0) * 0.05)

    if regime.regime == "HIGH_VOLATILITY":
        goodness = min(goodness, 0.35)
    elif regime.regime == "LOW_VOLATILITY":
        goodness = max(goodness, 0.70)

    return _clamp01(1.0 - goodness)

def _raw_volatility_quality(atr_pct: float, regime: RegimeReport,
                            atr_history: Optional[list] = None) -> float:
    """
    خروجی روی مقیاس «بدی» (۱.۰ = خیلی بد/نامنظم)، همان جهتی که قبلاً هم بود
    و روی داده‌ی واقعی تأیید شد. تفاوت: به‌جای آستانه‌ی مطلق، رتبه‌ی درصلی
    ATR% فعلی نسبت به تاریخچه‌ی خودِ همین نماد (walk-forward safe) استفاده
    می‌شود تا امتیاز واقعاً درون کل بازه‌ی داده پخش شود، نه اینکه اکثر
    رکوردها روی یک عدد ثابت بیفتند.
    """
    from RSP.fuzzy_core.bounded_uncertainty import rolling_percentile_score
    from RSP.config import settings as _s
    pct = rolling_percentile_score(
        atr_pct, atr_history,
        min_samples=_s.VOLATILITY_PERCENTILE_MIN_SAMPLES,
        target_samples=_s.VOLATILITY_PERCENTILE_TARGET_SAMPLES,
    )
    if pct is None:
        return _raw_volatility_quality_legacy(atr_pct, regime)

    badness = pct.value  # رتبه‌ی بالا = نسبت به تاریخچه‌ی خودش پرنوسان‌تر = بدتر
    if regime.regime == "HIGH_VOLATILITY":
        badness = max(badness, 0.65)
    elif regime.regime == "LOW_VOLATILITY":
        badness = min(badness, 0.30)

    return _clamp01(badness)

def _raw_volatility_quality_bounded(atr_pct: float, regime: RegimeReport,
                                    atr_history: Optional[list] = None):
    """نسخه‌ی Bounded Uncertainty برای volatility_quality."""
    from RSP.fuzzy_core.bounded_uncertainty import rolling_percentile_score, BoundedScore
    from RSP.config import settings as _s
    pct = rolling_percentile_score(
        atr_pct, atr_history,
        min_samples=_s.VOLATILITY_PERCENTILE_MIN_SAMPLES,
        target_samples=_s.VOLATILITY_PERCENTILE_TARGET_SAMPLES,
    )
    value = _raw_volatility_quality(atr_pct, regime, atr_history)
    if pct is None:
        return BoundedScore(value=round(value, 4), lower=0.0, upper=1.0,
                            confidence=0.0, n_samples=0 if not atr_history else len(atr_history))
    return BoundedScore(value=round(value, 4), lower=pct.lower, upper=pct.upper,
                        confidence=pct.confidence, n_samples=pct.n_samples)

def evaluate_volatility_quality(atr_pct: float, regime: RegimeReport,
                                atr_history: Optional[list] = None) -> Dict[str, float]:
    """
    ورودی: ATR% + Regime (+ اختیاری: تاریخچه‌ی ATR برای percentile scoring)
    خروجی: fuzzy volatility quality

    منطق (بازطراحی‌شده): رتبه‌ی درصلی ATR% فعلی نسبت به تاریخچه‌ی خودِ همین
    نماد (نه آستانه‌ی مطلق). اگر atr_history داده نشود یا نمونه کافی نباشد،
    به فرمول قدیمی (آستانه‌ی ثابت) برمی‌گردد — کاملاً backward-compatible.

    کالیبراسیون گیت: چون خروجی percentile-based یک مقیاس کاملاً متفاوت
    (تقریباً Uniform روی [0,1]) از فرمول قدیمی دارد، وقتی مسیر percentile
    واقعاً فعال است از یک LinguisticVariable جداگانه و کالیبره‌شده
    ("volatility_quality_v2") استفاده می‌شود؛ در غیر این صورت همان متغیر
    قدیمی. این یعنی _permission_gate با هر دو مسیر سازگار می‌ماند بدون اینکه
    شکل قدیمی برای مقیاس جدید (که باعث رد ۳۰٪+ معاملات می‌شد) دوباره استفاده شود.
    """
    from RSP.fuzzy_core.bounded_uncertainty import rolling_percentile_score
    from RSP.config import settings as _s
    pct = rolling_percentile_score(
        atr_pct, atr_history,
        min_samples=_s.VOLATILITY_PERCENTILE_MIN_SAMPLES,
        target_samples=_s.VOLATILITY_PERCENTILE_TARGET_SAMPLES,
    )
    var_name = "volatility_quality_v2" if pct is not None else "volatility_quality"
    var = get_quality_variable(var_name)
    if var is None:
        return {}
    return var.fuzzify(_raw_volatility_quality(atr_pct, regime, atr_history))

# =============================================================================
# Phase 34 — Fuzzy Market Stability
# =============================================================================
def _raw_market_stability(regime: RegimeReport, structure: StructureReport) -> float:
    stability_map = {
        "RANGE": 0.80, "LOW_VOLATILITY": 0.85,
        "UPTREND": 0.65, "DOWNTREND": 0.65,
        "STRONG_UPTREND": 0.55, "STRONG_DOWNTREND": 0.55,
        "WEAK_UPTREND": 0.50, "WEAK_DOWNTREND": 0.50,
        "BREAKOUT": 0.30, "BREAKDOWN": 0.30,
        "RECOVERY": 0.35, "TRANSITION": 0.20,
        "CRASH": 0.05, "HIGH_VOLATILITY": 0.25,
        "FAKE_BREAKOUT": 0.15, "UNKNOWN": 0.30,
    }
    score = stability_map.get(regime.regime, 0.40)

    if structure.pattern == "HH_HL":
        score += 0.05
    elif structure.pattern == "LH_LL":
        score += 0.05
    elif structure.pattern == "MIXED":
        score -= 0.10

    if structure.last_structure_event in ("CHOCH_BULLISH", "CHOCH_BEARISH"):
        score -= 0.10

    return _clamp01(score)

def evaluate_market_stability(regime: RegimeReport, structure: StructureReport) -> Dict[str, float]:
    """
    ورودی: Regime + Structure
    خروجی: fuzzy market stability

    منطق:
    - RANGE/LOW_VOL -> stable
    - TRANSITION/BREAKOUT/CRASH -> unstable
    - Mixed structure -> less stable
    """
    var = get_quality_variable("market_stability")
    if var is None:
        return {}
    return var.fuzzify(_raw_market_stability(regime, structure))

# =============================================================================
# Phase 35 — Fuzzy Signal Strength
# =============================================================================
def _raw_signal_strength(fusion: FusionReport) -> float:
    score = abs(fusion.net_score)
    if fusion.conflicting_evidence:
        score -= 0.10 * min(1.0, len(fusion.conflicting_evidence) / 3.0)
    return _clamp01(score)

def evaluate_signal_strength(fusion: FusionReport) -> Dict[str, float]:
    """
    ورودی: FusionReport
    خروجی: fuzzy signal strength (on absolute net_score)

    منطق:
    - |net_score| > 0.7 -> very_strong/extreme
    - |net_score| 0.4-0.7 -> strong
    - Agreement ratio high -> bonus
    """
    var = get_quality_variable("signal_strength")
    if var is None:
        return {}
    return var.fuzzify(_raw_signal_strength(fusion))

# =============================================================================
# Phase 36 — Fuzzy Signal Confidence
# =============================================================================
def _raw_signal_confidence(confidence: ConfidenceReport) -> float:
    return _clamp01(confidence.confidence / 100.0)

def evaluate_signal_confidence(confidence: ConfidenceReport) -> Dict[str, float]:
    """
    ورودی: ConfidenceReport
    خروجی: fuzzy signal confidence

    منطق: normalize confidence (0..100) to (0..1)
    """
    var = get_quality_variable("signal_confidence")
    if var is None:
        return {}
    return var.fuzzify(_raw_signal_confidence(confidence))

# =============================================================================
# Phase 37 — Fuzzy Contradiction Severity (بازطراحی‌شده: decoupled از گیت گسسته)
# =============================================================================
def _raw_contradiction_severity_legacy(contradiction: ContradictionReport) -> float:
    """
    فرمول قدیمی. Root cause یافته‌شده: contradiction.severity فقط وقتی
    SEVERE/MODERATE می‌شود که contradiction.conflict_detected=True — و در آن
    حالت decide() (تصمیم‌گیر Crisp) از قبل خودش action را WAIT/NO_TRADE کرده
    (RSP/decision_engine/decision_brain.py حدود خط ۷۳). یعنی هر رکوردی که
    اصلاً به BUY/SELL برسد، severity="NONE" تضمین‌شده است و این فرمول برایش
    فقط conflict_ratio خام (که با آستانه‌ی فعلی BLOCK_THRESHOLD=0.15 عملاً
    almost-binary است) را برمی‌گرداند — دقیقاً همان چیزی که در export دیدیم:
    ثابت ۰.۰ برای هر ۲۰۴۹ معامله‌ی واقعی. این «باگ» نیست، محدودیت ساختاری
    فرمول فعلی است؛ نگه داشته شده فقط برای مقایسه/فالبک.
    """
    score = contradiction.conflict_ratio
    if contradiction.mtf_disagreement:
        score += 0.15
    if contradiction.severity == "SEVERE":
        score = max(score, 0.75)
    elif contradiction.severity == "MODERATE":
        score = max(score, 0.45)
    if contradiction.reasons and len(contradiction.reasons) >= 2:
        score += 0.05
    return _clamp01(score)

def _raw_contradiction_severity(contradiction: ContradictionReport) -> float:
    """
    نسخه‌ی پیوسته و decoupled از گیت گسسته‌ی Crisp.

    Root cause (محور ۱): در fuzzy_training_export.py امتیاز فقط برای رکوردهایی
    محاسبه می‌شود که decision.action از قبل BUY/SELL شده — یعنی contradiction
    قبلاً conflict_detected=False بوده (وگرنه decide() خودش WAIT/NO_TRADE
    می‌داد). در نتیجه severity همیشه "NONE" است و امتیاز قدیمی (که برای
    SEVERE/MODERATE یک max() گسسته می‌زد) برای این جمعیت همیشه در بهترین حالت
    fadeی از conflict_ratio تنها می‌ماند — که خودش هم با BLOCK_THRESHOLD فعلی
    (۰.۱۵) و اندازه‌ی معمول شواهد، عملاً یا ۰ یا بالای آستانه است (بدون حالت
    میانی قابل مشاهده در جمعیت survivor). در backtest_engine.py برعکس، لایه‌ی
    فازی روی *همه‌ی* کندل‌ها اجرا می‌شود (چه decision.action=BUY/SELL باشد چه
    WAIT/NO_TRADE) — پس آنجا می‌توانیم severity=SEVERE (raw≈۰.۸۰ -> μ_severe
    فازی‌شده ≈۰.۵۰، دقیقاً همان عددی که در --fuzzy-compare دیده شد) را هم
    ببینیم. این دو مسیر روی دو جمعیت متفاوت از کندل‌ها کار می‌کردند؛ عدم‌تطابق
    واقعی، «باگ pipeline» به‌معنای خطای محاسباتی نبود.

    برای این‌که contradiction_severity یک feature قابل‌استفاده برای
    AHP/ANFIS روی دقیقاً همان جمعیتی باشد که واقعاً معامله می‌شوند (BUY/SELL
    survivors)، امتیاز را از سیگنال‌های پیوسته‌ای می‌سازیم که مستقل از threshold
    گسسته‌ی conflict_detected همیشه در دسترس‌اند:
    - قدرت اجماع (|net_score|) — هرچه پایین‌تر، عدم‌قطعیت جهت بیشتر
    - conflict_ratio نسبت به BLOCK_THRESHOLD (به‌جای max() گسسته، یک رمپ خطی)
    - mtf_disagreement (bonus کوچک، فقط چون این خودش می‌تواند conflict_detected
      را true کند، در جمعیت survivor همیشه False است ولی برای بارهای دیگر —
      مثلاً مصرف تشخیصی روی کل جمعیت — همچنان معنا دارد)

    این تابع منطق گیت Crisp (decision_brain.py) را عوض نمی‌کند — فقط سیگنال
    مصرفی fuzzy/feature را از آن گیت گسسته جدا می‌کند.
    """
    from RSP.config import settings as _s
    weak_consensus = _clamp01(1.0 - abs(contradiction.net_score))
    ratio_component = _clamp01(contradiction.conflict_ratio / max(_s.CONTRADICTION_BLOCK_THRESHOLD, 1e-6))

    score = 0.55 * weak_consensus + 0.45 * ratio_component
    if contradiction.mtf_disagreement:
        score = _clamp01(score + 0.15)
    if contradiction.reasons and len(contradiction.reasons) >= 2:
        score = _clamp01(score + 0.05)
    return _clamp01(score)

def evaluate_contradiction_severity(contradiction: ContradictionReport) -> Dict[str, float]:
    """
    ورودی: ContradictionReport
    خروجی: fuzzy contradiction severity

    کنترل rollback: settings.CONTRADICTION_SCORING_MODE
    - "legacy" (پیش‌فرض — Baseline فعلی دست‌نخورده می‌ماند): فرمول قدیمی
    - "continuous": فرمول جدید decoupled (برای کالیبراسیون/AHP-ANFIS از feature
      واقعاً دارای واریانس روی جمعیت BUY/SELL survivor)
    تغییر mode روی گیت Permission (decision_controller._permission_gate) هم اثر
    می‌گذارد چون از همین dict مصرف می‌کند — به همین دلیل پیش‌فرض را عوض نکردیم.
    """
    from RSP.config import settings as _s
    var = get_quality_variable("contradiction_severity")
    if var is None:
        return {}
    mode = getattr(_s, "CONTRADICTION_SCORING_MODE", "legacy")
    raw = _raw_contradiction_severity(contradiction) if mode == "continuous"         else _raw_contradiction_severity_legacy(contradiction)
    return var.fuzzify(raw)

# =============================================================================
# Phase 38 — Fuzzy Opportunity Quality
# =============================================================================
def evaluate_opportunity_quality(
    trend_q: Dict[str, float],
    momentum_q: Dict[str, float],
    entry_q: Dict[str, float],
    risk_q: Dict[str, float],
    volatility_q: Dict[str, float],
    stability_q: Dict[str, float],
    signal_str: Dict[str, float],
    signal_conf: Dict[str, float],
    contradiction_sev: Dict[str, float],
) -> Dict[str, float]:
    """
    ورودی: خروجی‌های فازی تمام موتورهای کیفیت
    خروجی: fuzzy opportunity quality

    منطق:
    - این یک ترکیب اولیه است؛ ترکیب نهایی در Rule Engine انجام می‌شود
    - اینجا فقط یک heuristic aggregate برای گزارش‌دهی
    """
    var = get_quality_variable("opportunity_quality")
    if var is None:
        return {}

    def _weighted_term_score(fuzzy_dict: Dict[str, float], weights: Dict[str, float]) -> float:
        return sum(fuzzy_dict.get(k, 0.0) * w for k, w in weights.items())

    # Convert each fuzzy quality to a crisp 0..1 score (centroid-like)
    t = _weighted_term_score(trend_q, {"very_weak": 0.0, "weak": 0.2, "moderate": 0.5, "strong": 0.8, "very_strong": 1.0})
    m = _weighted_term_score(momentum_q, {"very_weak": 0.0, "weak": 0.2, "moderate": 0.5, "strong": 0.8, "very_strong": 1.0})
    e = _weighted_term_score(entry_q, {"very_weak": 0.0, "weak": 0.2, "moderate": 0.5, "strong": 0.8, "very_strong": 1.0})
    r = _weighted_term_score(risk_q, {"very_weak": 0.0, "weak": 0.2, "moderate": 0.5, "strong": 0.8, "very_strong": 1.0})
    v = _weighted_term_score(volatility_q, {"very_poor": 0.0, "poor": 0.2, "moderate": 0.5, "good": 0.8, "excellent": 1.0})
    s = _weighted_term_score(stability_q, {"very_weak": 0.0, "weak": 0.2, "moderate": 0.5, "strong": 0.8, "very_strong": 1.0})
    sig = _weighted_term_score(signal_str, {"very_weak": 0.0, "weak": 0.2, "moderate": 0.5, "strong": 0.8, "very_strong": 1.0, "extreme": 0.9})
    conf = _weighted_term_score(signal_conf, {"very_weak": 0.0, "weak": 0.2, "moderate": 0.5, "strong": 0.8, "very_strong": 1.0})
    contr = _weighted_term_score(contradiction_sev, {"none": 1.0, "low": 0.8, "moderate": 0.5, "high": 0.2, "severe": 0.0})

    # Weighted aggregate (heuristic)
    score = (
        t * 0.15 + m * 0.15 + e * 0.20 + r * 0.15 +
        v * 0.10 + s * 0.05 + sig * 0.10 + conf * 0.05 + contr * 0.05
    )

    return var.fuzzify(_clamp01(score))
