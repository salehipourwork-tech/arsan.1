"""
RSP — signal_fusion/fusion_engine.py  (Phase 9: SIGNAL FUSION ENGINE)

هیچ اندیکاتوری به تنهایی اجازه‌ی صدور تصمیم نهایی ندارد. این ماژول
شواهد را از دسته‌های مستقل جمع می‌کند:

  Trend Evidence     <- regime_engine.perception + confluence (EMA/SMA/ADX)
  Momentum Evidence  <- confluence (RSI/MACD/StochRSI) + momentum_state
  Volume Evidence     <- confluence (OBV/Volume trend)
  Structure Evidence  <- market_structure (BOS/CHoCH/pattern)
  Volatility Evidence <- perception (ATR%)
  MTF Evidence        <- multi_timeframe (اجماع بین تایم‌فریم‌ها)

هر دسته یک امتیاز -1..+1 می‌گیرد (منفی=نزولی، مثبت=صعودی) و با وزن‌های
Adaptive (بر اساس رژیم - Phase 13, در config/settings.py) ترکیب می‌شود.

خروجی شامل چهار سطل شواهد است: Bullish / Bearish / Neutral / Conflicting
دقیقاً طبق اسپک.
"""

from dataclasses import dataclass, field
from typing import Dict, List

from RSP.config import settings
from RSP.regime_engine.regime_engine import RegimeReport
from RSP.signal_engine.confluence import ConfluenceReport
from RSP.multi_timeframe.mtf_brain import MTFReport


@dataclass
class EvidenceScore:
    category: str
    score: float          # -1 (کاملاً نزولی) .. +1 (کاملاً صعودی)
    weight: float
    weighted_score: float
    detail: str = ""


@dataclass
class FusionReport:
    evidences: List[EvidenceScore] = field(default_factory=list)
    bullish_evidence: List[str] = field(default_factory=list)
    bearish_evidence: List[str] = field(default_factory=list)
    neutral_evidence: List[str] = field(default_factory=list)
    conflicting_evidence: List[str] = field(default_factory=list)
    net_score: float = 0.0        # -1..+1  جمع weighted
    weights_used: Dict[str, float] = field(default_factory=dict)


# FIX v2.1: _trend_score/_momentum_score/_volume_score were written against
# an imagined ConfluenceReport shape (a `.readings` list of named indicator
# readings, `.momentum_state`) that analyze_confluence() never produced —
# every call crashed with AttributeError. Rewritten to use the fields
# ConfluenceReport actually has: signal/strength, ema_alignment/trend_strength,
# rsi/rsi_divergence, volume_trend/volume_strength. Same intent (regime +
# indicator alignment => trend score; RSI positioning/divergence => momentum;
# volume trend => volume score), just wired to the real data.

def _trend_score(regime: RegimeReport, confluence: ConfluenceReport) -> EvidenceScore:
    bullish_regimes = {"STRONG_UPTREND": 1.0, "UPTREND": 0.7, "WEAK_UPTREND": 0.35,
                        "RECOVERY": 0.3, "BREAKOUT": 0.5}
    bearish_regimes = {"STRONG_DOWNTREND": -1.0, "DOWNTREND": -0.7, "WEAK_DOWNTREND": -0.35,
                        "BREAKDOWN": -0.5, "CRASH": -1.0}
    base = bullish_regimes.get(regime.regime, bearish_regimes.get(regime.regime, 0.0))

    ema_aligned = ((confluence.ema_alignment == "BULLISH" and base > 0)
                   or (confluence.ema_alignment == "BEARISH" and base < 0))
    strength_aligned = confluence.trend_strength > 50 and base != 0
    align = int(ema_aligned) + int(strength_aligned)
    adjustment = 0.15 * align if base != 0 else 0.0
    score = max(-1.0, min(1.0, base + (adjustment if base >= 0 else -adjustment)))
    return EvidenceScore("trend", score, 0.0, 0.0, detail=f"regime={regime.regime}, aligned_indicators={align}/2")


def _momentum_score(confluence: ConfluenceReport) -> EvidenceScore:
    rsi = confluence.rsi
    rsi_score = 0.0
    if rsi >= 70:
        rsi_score = 1.0
    elif rsi >= 55:
        rsi_score = 0.5
    elif rsi <= 30:
        rsi_score = -1.0
    elif rsi <= 45:
        rsi_score = -0.5

    div_bonus = 0.2 if confluence.rsi_divergence == "BULLISH" else \
                (-0.2 if confluence.rsi_divergence == "BEARISH" else 0.0)
    score = max(-1.0, min(1.0, rsi_score + div_bonus))
    return EvidenceScore("momentum", score, 0.0, 0.0,
                          detail=f"rsi={rsi:.1f}, rsi_divergence={confluence.rsi_divergence}")


def _volume_score(confluence: ConfluenceReport) -> EvidenceScore:
    if "LOW_VOLUME_SKIP" in confluence.tags:
        return EvidenceScore("volume", 0.0, 0.0, 0.0, detail="LOW_VOLUME_SKIP")
    direction = 1.0 if confluence.signal == "BUY" else (-1.0 if confluence.signal == "SELL" else 0.0)
    magnitude = 1.0 if confluence.volume_trend == "INCREASING" else \
                (0.4 if confluence.volume_trend == "NEUTRAL" else 0.15)
    score = max(-1.0, min(1.0, direction * magnitude))
    return EvidenceScore("volume", score, 0.0, 0.0,
                          detail=f"volume_trend={confluence.volume_trend}, signal={confluence.signal}")


def _structure_score(regime: RegimeReport) -> EvidenceScore:
    struct = regime.structure
    event_score = {
        "BOS_BULLISH": 0.7, "CHOCH_BULLISH": 0.5,
        "BOS_BEARISH": -0.7, "CHOCH_BEARISH": -0.5,
        "NONE": 0.0,
    }.get(struct.last_structure_event, 0.0)
    pattern_score = {"HH_HL": 0.4, "LH_LL": -0.4, "MIXED": 0.0, "UNKNOWN": 0.0}.get(struct.pattern, 0.0)
    score = max(-1.0, min(1.0, 0.6 * event_score + 0.4 * pattern_score))
    return EvidenceScore("structure", score, 0.0, 0.0,
                          detail=f"event={struct.last_structure_event}, pattern={struct.pattern}")


def _volatility_score(regime: RegimeReport) -> EvidenceScore:
    """نوسان بالا خودش جهت‌دار نیست، فقط ریسک را افزایش می‌دهد -> این را به‌عنوان
    یک 'penalty' نه یک جهت مدل می‌کنیم: امتیاز نزدیک صفر ولی وزنش در تصمیم
    نهایی از طریق risk_engine اثر می‌گذارد؛ اینجا فقط informational است."""
    atr_pct = regime.perception.atr_pct
    if atr_pct > 5.0:
        return EvidenceScore("volatility", 0.0, 0.0, 0.0, detail=f"HIGH_VOLATILITY atr%={atr_pct:.2f} (ریسک بالا)")
    if atr_pct < 0.8:
        return EvidenceScore("volatility", 0.0, 0.0, 0.0, detail=f"LOW_VOLATILITY atr%={atr_pct:.2f}")
    return EvidenceScore("volatility", 0.0, 0.0, 0.0, detail=f"NORMAL atr%={atr_pct:.2f}")


def _mtf_score(mtf: MTFReport) -> EvidenceScore:
    return EvidenceScore("mtf", mtf.consensus_score, 0.0, 0.0, detail=mtf.summary)


def fuse_signals(regime: RegimeReport, confluence: ConfluenceReport, mtf: MTFReport) -> FusionReport:
    weights = settings.get_weights_for_regime(regime.regime).as_dict()

    raw_scores = {
        "trend": _trend_score(regime, confluence),
        "momentum": _momentum_score(confluence),
        "volume": _volume_score(confluence),
        "structure": _structure_score(regime),
        "volatility": _volatility_score(regime),
        "mtf": _mtf_score(mtf),
    }

    report = FusionReport(weights_used=weights)
    net = 0.0
    for category, ev in raw_scores.items():
        w = weights.get(category, 0.0)
        ev.weight = w
        ev.weighted_score = round(ev.score * w, 4)
        net += ev.weighted_score
        report.evidences.append(ev)

        label = f"{category.upper()}: {ev.detail} (score={ev.score:+.2f}, weighted={ev.weighted_score:+.3f})"
        if ev.score > 0.15:
            report.bullish_evidence.append(label)
        elif ev.score < -0.15:
            report.bearish_evidence.append(label)
        else:
            report.neutral_evidence.append(label)

    # Conflicting evidence: دسته‌هایی که در جهت مخالف net_score حرکت می‌کنند و اندازه‌ی
    # قابل‌توجهی دارند
    report.net_score = round(max(-1.0, min(1.0, net)), 4)
    for ev in report.evidences:
        if report.net_score > 0.1 and ev.score < -0.15:
            report.conflicting_evidence.append(f"{ev.category.upper()} خلاف جهت نتیجه‌ی کلی (score={ev.score:+.2f})")
        elif report.net_score < -0.1 and ev.score > 0.15:
            report.conflicting_evidence.append(f"{ev.category.upper()} خلاف جهت نتیجه‌ی کلی (score={ev.score:+.2f})")

    # FIX v2.1: ConfluenceReport has no .divergences list — divergence info
    # lives in .rsi_divergence / .tags.
    if confluence.rsi_divergence != "NONE":
        report.conflicting_evidence.append(f"RSI_DIVERGENCE_{confluence.rsi_divergence}")

    return report
