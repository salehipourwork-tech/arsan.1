"""
RSP — fuzzy_core/decision_controller.py (Phases 45-50: Decision Control Layer)

نسخه‌ی ۲: 
- گیت VOLATILITY نرم‌تر شد (۰.۶۰ → ۰.۸۰)
- AHP با entry_quality و compensatory bonus
- Hysteresis threshold از config خوانده می‌شود
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from collections import deque

from RSP.fuzzy_core.inference import FuzzyInferenceReport, run_fuzzy_inference
from RSP.fuzzy_core.quality_engines import (
    evaluate_trend_quality, evaluate_momentum_quality,
    evaluate_entry_quality, evaluate_risk_quality,
    evaluate_volatility_quality, evaluate_market_stability,
    evaluate_signal_strength, evaluate_signal_confidence,
    evaluate_contradiction_severity, evaluate_opportunity_quality,
)
from RSP.config import settings

@dataclass
class FuzzyDecisionReport:
    decision: str = "NO_TRADE"
    confidence: float = 0.0
    opportunity_score: float = 0.0
    trend_quality: Dict[str, float] = field(default_factory=dict)
    momentum_quality: Dict[str, float] = field(default_factory=dict)
    entry_quality: Dict[str, float] = field(default_factory=dict)
    risk_quality: Dict[str, float] = field(default_factory=dict)
    volatility_quality: Dict[str, float] = field(default_factory=dict)
    market_stability: Dict[str, float] = field(default_factory=dict)
    signal_strength: Dict[str, float] = field(default_factory=dict)
    signal_confidence: Dict[str, float] = field(default_factory=dict)
    contradiction_severity: Dict[str, float] = field(default_factory=dict)
    opportunity_quality: Dict[str, float] = field(default_factory=dict)
    primary_reason: str = ""
    active_rules: List[str] = field(default_factory=list)
    rejected_trade: bool = True
    hysteresis_applied: bool = False
    stability_check_passed: bool = True
    notes: List[str] = field(default_factory=list)
    fuzzy_inference: Optional[FuzzyInferenceReport] = None


class DecisionHistory:
    def __init__(self, max_len: int = 5):
        self.history: deque = deque(maxlen=max_len)
        self.last_trade_decision: Optional[str] = None
        self.last_trade_score: float = 0.0
        self.opportunity_scores: deque = deque(maxlen=500)

    def record_opportunity_score(self, score: float):
        self.opportunity_scores.append(score)

    def adaptive_threshold(self, fallback: float, percentile: float,
                           min_samples: int = 30) -> float:
        hist = list(self.opportunity_scores)
        if len(hist) < min_samples:
            return fallback
        hist_sorted = sorted(hist)
        idx = min(len(hist_sorted) - 1, max(0, int(round(percentile * (len(hist_sorted) - 1)))))
        return hist_sorted[idx]

    def push(self, decision: str, score: float):
        self.history.append((decision, score))

    def is_stable(self, min_consistent: int = 3) -> bool:
        if len(self.history) < min_consistent:
            return True
        recent = [d for d, _ in list(self.history)[-min_consistent:]]
        return len(set(recent)) == 1

    def hysteresis_block(self, new_decision: str, new_score: float,
                         threshold_drop: float = 15.0) -> bool:
        if self.last_trade_decision in ("LONG", "SHORT"):
            if new_decision in ("HOLD", "NO_TRADE"):
                if self.last_trade_score - new_score < threshold_drop:
                    return True
        return False

    def update_last_trade(self, decision: str, score: float):
        if decision in ("LONG", "SHORT"):
            self.last_trade_decision = decision
            self.last_trade_score = score


_decision_histories: Dict[str, DecisionHistory] = {}

def get_history(coin: str) -> DecisionHistory:
    if coin not in _decision_histories:
        _decision_histories[coin] = DecisionHistory(max_len=settings.FUZZY_DECISION_HISTORY_LEN)
    return _decision_histories[coin]


def _permission_gate(
    opportunity_score: float,
    contradiction_sev: Dict[str, float],
    risk_q: Dict[str, float],
    entry_q: Dict[str, float],
    volatility_q: Dict[str, float],
    effective_threshold: Optional[float] = None,
) -> tuple:
    """
    بررسی‌های نهایی قبل از صدور مجوز معامله.
    نسخه‌ی ۲: گیت VOLATILITY نرم‌تر (۰.۸۰ به‌جای ۰.۶۰)
    """
    # Hard reject: contradiction severe
    severe_contra = contradiction_sev.get("severe", 0.0)
    if severe_contra >= 0.30:
        return False, f"CONTRADICTION_SEVERE (μ={severe_contra:.2f})"

    # Hard reject: entry quality very weak
    weak_entry = max(entry_q.get("very_weak", 0.0), entry_q.get("weak", 0.0))
    if weak_entry >= 0.60:
        return False, f"ENTRY_QUALITY_TOO_WEAK (μ_weak={weak_entry:.2f})"

    # Hard reject: risk quality very weak
    weak_risk = max(risk_q.get("very_weak", 0.0), risk_q.get("weak", 0.0))
    if weak_risk >= 0.60:
        return False, f"RISK_QUALITY_TOO_WEAK (μ_weak={weak_risk:.2f})"

    # Hard reject: volatility very poor — نسخه‌ی ۲: ۰.۸۰ به‌جای ۰.۶۰
    poor_vol = max(volatility_q.get("very_poor", 0.0), volatility_q.get("poor", 0.0))
    if poor_vol >= 0.80:
        return False, f"VOLATILITY_TOO_POOR (μ_poor={poor_vol:.2f})"

    # Adaptive threshold
    threshold = settings.FUZZY_OPPORTUNITY_THRESHOLD if effective_threshold is None else effective_threshold
    if opportunity_score < threshold:
        return False, f"OPPORTUNITY_SCORE_BELOW_THRESHOLD ({opportunity_score:.1f} < {threshold:.1f})"

    return True, "ALL_GATES_PASSED"


def run_fuzzy_decision(
    coin: str,
    regime,
    confluence,
    mtf,
    structure,
    risk_plan,
    atr_pct: float,
    fusion,
    contradiction,
    confidence,
    direction: str,
) -> FuzzyDecisionReport:
    """
    نسخه‌ی ۲: AHP با entry_quality + compensatory bonus
    """
    report = FuzzyDecisionReport()
    notes = []

    # Phase 29-38: Quality Engines
    report.trend_quality = evaluate_trend_quality(regime, confluence)
    report.momentum_quality = evaluate_momentum_quality(confluence)
    report.entry_quality = evaluate_entry_quality(mtf, structure)

    atr_history = None
    if settings.USE_PERCENTILE_RISK_VOLATILITY and regime is not None:
        atr_history = getattr(getattr(regime, "perception", None), "atr_pct_series", None)
    report.risk_quality = evaluate_risk_quality(risk_plan, atr_pct, atr_history, regime)
    report.volatility_quality = evaluate_volatility_quality(atr_pct, regime, atr_history)
    report.market_stability = evaluate_market_stability(regime, structure)
    report.signal_strength = evaluate_signal_strength(fusion)
    report.signal_confidence = evaluate_signal_confidence(confidence)
    report.contradiction_severity = evaluate_contradiction_severity(contradiction)

    report.opportunity_quality = evaluate_opportunity_quality(
        report.trend_quality, report.momentum_quality, report.entry_quality,
        report.risk_quality, report.volatility_quality, report.market_stability,
        report.signal_strength, report.signal_confidence, report.contradiction_severity,
    )

    # Phase 42-44: Fuzzy Inference
    fuzzified_inputs = {
        "trend_quality": report.trend_quality,
        "momentum_quality": report.momentum_quality,
        "entry_quality": report.entry_quality,
        "risk_quality": report.risk_quality,
        "volatility_quality": report.volatility_quality,
        "market_stability": report.market_stability,
        "signal_strength": report.signal_strength,
        "signal_confidence": report.signal_confidence,
        "contradiction_severity": report.contradiction_severity,
    }

    inference = run_fuzzy_inference(
        fuzzified_inputs,
        method=settings.FUZZY_INFERENCE_METHOD,
        conflict_method=settings.FUZZY_CONFLICT_METHOD,
    )
    report.fuzzy_inference = inference
    report.active_rules = inference.active_rules
    report.opportunity_score = inference.defuzzified_score

    # AHP Opportunity Scoring — نسخه‌ی ۲
    if getattr(settings, "OPPORTUNITY_SCORING_METHOD", "rules") == "ahp":
        from RSP.fuzzy_core.ahp_scoring import ahp_opportunity_score
        from RSP.fuzzy_core.quality_engines import (
            _raw_trend_quality, _raw_risk_quality, _raw_volatility_quality,
            _raw_entry_quality,
        )
        trend_raw = _raw_trend_quality(regime, confluence)
        risk_raw = _raw_risk_quality(risk_plan, atr_pct, atr_history, regime)
        vol_raw = _raw_volatility_quality(atr_pct, regime, atr_history)
        entry_raw = _raw_entry_quality(mtf, structure)
        report.opportunity_score = ahp_opportunity_score(trend_raw, risk_raw, vol_raw, entry_raw)
        notes.append(f"AHPv2 opportunity_score={report.opportunity_score} "
                     f"(rule-based was: {inference.defuzzified_score}, "
                     f"trend={trend_raw:.2f} risk={risk_raw:.2f} vol_badness={vol_raw:.2f} entry={entry_raw:.2f})")

    # Phase 46: Dynamic Confidence Calibration
    raw_conf = report.opportunity_score / 100.0
    no_contra = report.contradiction_severity.get("none", 0.0) + report.contradiction_severity.get("low", 0.0)
    if no_contra > 0.7:
        raw_conf = min(1.0, raw_conf * 1.05 + 0.02)
    if report.market_stability.get("strong", 0.0) + report.market_stability.get("very_strong", 0.0) > 0.6:
        raw_conf = min(1.0, raw_conf * 1.03)
    report.confidence = round(raw_conf, 4)

    # Phase 50: Permission Gate
    history = get_history(coin)
    eff_threshold = None
    if getattr(settings, "FUZZY_ADAPTIVE_OPPORTUNITY_THRESHOLD", False):
        eff_threshold = history.adaptive_threshold(
            fallback=settings.FUZZY_OPPORTUNITY_THRESHOLD,
            percentile=settings.FUZZY_ADAPTIVE_OPPORTUNITY_PERCENTILE,
        )
        notes.append(f"ADAPTIVE_THRESHOLD={eff_threshold:.1f} (self-relative, coin={coin})")

    allowed, gate_reason = _permission_gate(
        report.opportunity_score,
        report.contradiction_severity,
        report.risk_quality,
        report.entry_quality,
        report.volatility_quality,
        effective_threshold=eff_threshold,
    )
    history.record_opportunity_score(report.opportunity_score)

    if not allowed:
        report.decision = "NO_TRADE"
        report.rejected_trade = True
        report.primary_reason = gate_reason
        notes.append(f"GATE_REJECTED: {gate_reason}")
    else:
        if direction == "BULLISH":
            report.decision = "LONG"
        elif direction == "BEARISH":
            report.decision = "SHORT"
        else:
            report.decision = "HOLD"
        report.rejected_trade = False
        report.primary_reason = f"OpportunityScore={report.opportunity_score:.1f} | Dominant={inference.dominant_term}"
        notes.append(f"GATE_PASSED: {gate_reason}")

    # Phase 48-49: Stability & Hysteresis
    if not history.is_stable(min_consistent=settings.FUZZY_STABILITY_MIN_CONSISTENT):
        report.stability_check_passed = False
        notes.append("STABILITY_CHECK_FAILED: تصمیمات اخیر ناپایدار هستند")

    if not report.rejected_trade and history.hysteresis_block(
        report.decision, report.opportunity_score,
        threshold_drop=settings.FUZZY_HYSTERESIS_DROP):
        report.hysteresis_applied = True
        notes.append("HYSTERESIS_APPLIED: تغییر تصمیم بلاک شد")
        if history.last_trade_decision:
            report.decision = history.last_trade_decision
            report.primary_reason += " [HYSTERESIS_LOCKED]"

    history.push(report.decision, report.opportunity_score)
    if report.decision in ("LONG", "SHORT"):
        history.update_last_trade(report.decision, report.opportunity_score)

    report.notes = notes
    return report
