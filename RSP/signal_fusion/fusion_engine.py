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


def _trend_score(regime: RegimeReport, confluence: ConfluenceReport) -> EvidenceScore:
    bullish_regimes = {"STRONG_UPTREND": 1.0, "UPTREND": 0.7, "WEAK_UPTREND": 0.35,
                        "RECOVERY": 0.3, "BREAKOUT": 0.5}
    bearish_regimes = {"STRONG_DOWNTREND": -1.0, "DOWNTREND": -0.7, "WEAK_DOWNTREND": -0.35,
                        "BREAKDOWN": -0.5, "CRASH": -1.0}
    base = bullish_regimes.get(regime.regime, bearish_regimes.get(regime.regime, 0.0))

    ema_reading = next((r for r in confluence.readings if r.name == "EMA_CROSS"), None)
    sma_reading = next((r for r in confluence.readings if r.name == "SMA_TREND"), None)
    adx_reading = next((r for r in confluence.readings if r.name == "ADX"), None)
    align = sum(1 for r in [ema_reading, sma_reading, adx_reading] if r and
                ((r.direction == "BULLISH" and base > 0) or (r.direction == "BEARISH" and base < 0)))
    adjustment = 0.15 * align if base != 0 else 0.0
    score = max(-1.0, min(1.0, base + (adjustment if base >= 0 else -adjustment)))
    return EvidenceScore("trend", score, 0.0, 0.0, detail=f"regime={regime.regime}, aligned_indicators={align}/3")


def _momentum_score(confluence: ConfluenceReport) -> EvidenceScore:
    rsi_r = next((r for r in confluence.readings if r.name == "RSI"), None)
    macd_r = next((r for r in confluence.readings if r.name == "MACD"), None)
    stoch_r = next((r for r in confluence.readings if r.name == "STOCH_RSI"), None)
    dirs = [r.direction for r in [rsi_r, macd_r, stoch_r] if r]
    bull = dirs.count("BULLISH")
    bear = dirs.count("BEARISH")
    score = (bull - bear) / max(1, len(dirs))
    momentum_bonus = 0.15 if confluence.momentum_state == "ACCELERATION" else \
                      (-0.15 if confluence.momentum_state == "WEAKENING" else 0.0)
    score = max(-1.0, min(1.0, score + (momentum_bonus if score >= 0 else -momentum_bonus)))
    return EvidenceScore("momentum", score, 0.0, 0.0, detail=f"momentum_state={confluence.momentum_state}")


def _volume_score(confluence: ConfluenceReport) -> EvidenceScore:
    obv_r = next((r for r in confluence.readings if r.name == "OBV"), None)
    vol_r = next((r for r in confluence.readings if r.name == "VOLUME_TREND"), None)
    dirs = [r.direction for r in [obv_r, vol_r] if r]
    bull = dirs.count("BULLISH")
    bear = dirs.count("BEARISH")
    score = (bull - bear) / max(1, len(dirs))
    return EvidenceScore("volume", score, 0.0, 0.0, detail="OBV+VolumeTrend")


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

    if confluence.divergences:
        report.conflicting_evidence.extend(confluence.divergences)

    return report
