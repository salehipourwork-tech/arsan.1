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
        "WEAK_DOWNTREND": 0.90,     # n=237  win_rate=48.1%  mean_pnl=+0.208  (بهترین)
        "UPTREND": 0.68,            # n=381  win_rate=43.6%  mean_pnl=+0.048
        "LOW_VOLATILITY": 0.64,     # n=61   win_rate=44.3%  mean_pnl=-0.019
        "STRONG_DOWNTREND": 0.57,   # n=288  win_rate=39.9%  mean_pnl=+0.002
        "WEAK_UPTREND": 0.47,       # n=269  win_rate=39.0%  mean_pnl=-0.109
        "DOWNTREND": 0.41,          # n=590  win_rate=38.5%  mean_pnl=-0.169
        "BREAKOUT": 0.15,           # n=11 (نمونه‌ی کم) win_rate=0.0%  mean_pnl=-0.871
        "STRONG_UPTREND": 0.10,     # n=183  win_rate=29.0%  mean_pnl=-0.310  (بدترین)
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
# Phase 32 — Fuzzy Risk Quality
# =============================================================================
def _raw_risk_quality(risk_plan: Optional[RiskPlan], atr_pct: float) -> float:
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


def evaluate_risk_quality(risk_plan: Optional[RiskPlan], atr_pct: float) -> Dict[str, float]:
    """
    ورودی: RiskPlan + ATR%
    خروجی: fuzzy risk quality

    منطق:
      - RR >= 2.0 -> strong
      - RR < 1.5 -> weak
      - ATR% very high -> risk management harder -> moderate penalty
    """
    var = get_quality_variable("risk_quality")
    if var is None:
        return {}
    return var.fuzzify(_raw_risk_quality(risk_plan, atr_pct))


# =============================================================================
# Phase 33 — Fuzzy Volatility Quality
# =============================================================================
def _raw_volatility_quality(atr_pct: float, regime: RegimeReport) -> float:
    """
    خروجی روی مقیاس «بدی» (۱.۰ = خیلی بد/نامنظم) — یعنی مستقیماً قابل fuzzify
    روی volatility_quality است (excellent در x کم، very_poor در x زیاد).
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


def evaluate_volatility_quality(atr_pct: float, regime: RegimeReport) -> Dict[str, float]:
    """
    ورودی: ATR% + Regime
    خروجی: fuzzy volatility quality

    منطق:
      - ATR% 0.5-2.0 -> excellent (predictable)
      - ATR% 2.0-4.0 -> good
      - ATR% 4.0-6.0 -> moderate
      - ATR% > 6.0 -> poor (chaotic)
      - HIGH_VOLATILITY regime -> poor regardless

    نکته: خروجی این تابع خودش («بدی» 0..1) مستقیماً به fuzzify داده می‌شود؛
    دیگر نیازی به معکوس‌کردن دستی در بیرون از تابع نیست.
    """
    var = get_quality_variable("volatility_quality")
    if var is None:
        return {}
    return var.fuzzify(_raw_volatility_quality(atr_pct, regime))


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
# Phase 37 — Fuzzy Contradiction Severity
# =============================================================================
def _raw_contradiction_severity(contradiction: ContradictionReport) -> float:
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


def evaluate_contradiction_severity(contradiction: ContradictionReport) -> Dict[str, float]:
    """
    ورودی: ContradictionReport
    خروجی: fuzzy contradiction severity

    منطق:
      - conflict_ratio -> primary driver
      - mtf_disagreement -> bonus severity
      - severity flag -> direct mapping
    """
    var = get_quality_variable("contradiction_severity")
    if var is None:
        return {}
    return var.fuzzify(_raw_contradiction_severity(contradiction))


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
