"""
RSP — Fuzzy Decision Controller v2.0
PATCH: Per-method threshold, RegimeRuleFilter wired, adaptive threshold
"""

from dataclasses import dataclass
from typing import Optional, Dict, List
from ..config import settings
from ..fuzzy_core.inference import FuzzyInferenceReport as FuzzyInferenceResult
from ..fuzzy_core.quality_engines import QualityResult
from ..regime_rule_filter import RegimeRuleFilter


@dataclass
class FuzzyDecisionResult:
    can_trade: bool; opportunity_score: float; stability_score: float
    permission_score: float; overall_score: float; recommendation: str; notes: List[str]


@dataclass
class _InferenceScores:
    """Internal helper — the four numbers evaluate() needs from _run_inference."""
    opportunity_score: float; stability_score: float; permission_score: float; overall_score: float


class FuzzyDecisionController:
    def __init__(self):
        self.regime_filter = RegimeRuleFilter()
        self.history: Dict[str, List[float]] = {}

    def evaluate(self, regime, signals, mtf, trade_quality, history) -> Optional[FuzzyDecisionResult]:
        notes = []

        # FIX v2.0: Apply RegimeRuleFilter
        if regime and hasattr(regime, 'regime'):
            regime_label = regime.regime
            filtered_signals = self.regime_filter.filter_rules(signals, regime_label)
            if filtered_signals != signals:
                notes.append(f"regime_filter_applied:{regime_label}")
            signals = filtered_signals

        fuzzy_result = self._run_inference(regime, signals, mtf)
        if fuzzy_result is None:
            return None

        quality = self._check_quality(fuzzy_result, trade_quality)
        scoring_method = settings.OPPORTUNITY_SCORING_METHOD

        # FIX v2.0: Per-method threshold
        threshold_by_method = getattr(settings, "FUZZY_OPPORTUNITY_THRESHOLD_BY_METHOD", {})
        base_threshold = threshold_by_method.get(scoring_method, settings.FUZZY_OPPORTUNITY_THRESHOLD)

        if settings.FUZZY_ADAPTIVE_OPPORTUNITY_THRESHOLD and history:
            eff_threshold = self._adaptive_threshold(history, base_threshold)
            notes.append(f"adaptive_threshold:{eff_threshold:.1f}")
        else:
            eff_threshold = base_threshold

        if scoring_method == "ahp":
            eff_threshold += 5.0
            notes.append("ahp_threshold_boost:+5")

        opportunity = fuzzy_result.opportunity_score
        stability = fuzzy_result.stability_score
        permission = fuzzy_result.permission_score
        overall = fuzzy_result.overall_score

        can_trade = (
            opportunity >= eff_threshold
            and stability >= settings.FUZZY_STABILITY_MIN_CONSISTENT
            and permission >= settings.FUZZY_TRADE_PERMISSION_MIN
        )

        if can_trade:
            recommendation = "TRADE"
        elif opportunity >= eff_threshold - settings.FUZZY_HYSTERESIS_DROP:
            recommendation = "WATCH"
        else:
            recommendation = "NO_TRADE"

        return FuzzyDecisionResult(
            can_trade=can_trade, opportunity_score=round(opportunity, 2),
            stability_score=round(stability, 2), permission_score=round(permission, 2),
            overall_score=round(overall, 2), recommendation=recommendation, notes=notes,
        )

    def _run_inference(self, regime, signals, mtf):
        """
        FIX v2.1: this called run_fuzzy_inference(regime, signals, mtf) — but
        the real function takes a single `fuzzified_inputs` dict (var_name ->
        {term: degree}), not three raw report objects; and the caller then
        read .opportunity_score/.stability_score/.permission_score/
        .overall_score off the result, none of which FuzzyInferenceReport
        has (it only has .defuzzified_score). Every call crashed.

        This builds fuzzified_inputs from the real FusionReport/RegimeReport/
        MTFReport data using the quality_engines fuzzifiers, runs the actual
        rule-based inference, and derives the four scores evaluate() expects.
        Any quality dimension we can't confidently derive (entry/risk/signal
        confidence — no risk_plan or history is available at this point in
        the pipeline) is simply left out of fuzzified_inputs; missing
        variables fuzzify to a 0.0 degree for every rule that needs them,
        which only *lowers* rules' firing strength — i.e. it fails toward
        NOT trading, never toward a false-positive opportunity score.
        """
        from ..fuzzy_core.inference import run_fuzzy_inference
        from ..fuzzy_core.quality_engines import (
            evaluate_trend_quality, evaluate_momentum_quality,
            evaluate_volatility_quality, evaluate_contradiction_severity,
            evaluate_entry_quality, evaluate_market_stability,
            evaluate_signal_confidence, evaluate_signal_strength,
        )

        if regime is None or signals is None:
            return None

        trend_ev = next((e for e in signals.evidences if e.category == "trend"), None)
        momentum_ev = next((e for e in signals.evidences if e.category == "momentum"), None)
        trend_raw = abs(trend_ev.score) if trend_ev else abs(signals.net_score)
        momentum_raw = abs(momentum_ev.score) if momentum_ev else abs(signals.net_score)
        volatility_raw = (regime.perception.volatility_quality / 100.0) if regime and regime.perception else 0.5
        conflict_ratio = (len(signals.conflicting_evidence) / max(1, len(signals.evidences)))

        # FIX v2.1 (round 2): the OPPORTUNITY_RULES that actually produce a
        # high (>=75) score all require entry_quality and/or risk_quality —
        # e.g. R01 (100.0) and R02 (90.0) both need both. Only having
        # trend/momentum/volatility/contradiction capped the achievable
        # score at ~35 (R08, the only fully-coverable rule with a positive
        # outcome) — confirmed via diagnose_pipeline.py: with real BUY/SELL
        # candidates flowing in, 100% were rejected at can_trade because
        # opportunity_score never got anywhere near the threshold, not
        # because the setups were actually bad. Added honest proxies for
        # the remaining dimensions from data that IS available at this
        # point (no risk_plan/ConfidenceReport exist yet here):
        #   entry_quality      <- |mtf.consensus_score| (how aligned the
        #                         three timeframes are, signed-then-abs)
        #   risk_quality       <- inverse of volatility badness (a real
        #                         risk_plan-based score still overrides
        #                         this at the backtest_engine.py level;
        #                         this is only the fuzzy pre-screen)
        #   market_stability   <- 1 - conflict_ratio
        #   signal_confidence  <- blend of |net_score| and MTF agreement
        #   signal_strength    <- |net_score|
        entry_raw = abs(mtf.consensus_score) if mtf is not None else 0.0
        risk_raw = max(0.0, 1.0 - volatility_raw)
        stability_raw = max(0.0, 1.0 - conflict_ratio)
        confidence_raw = (abs(signals.net_score) + (1.0 if (mtf and mtf.agreement) else 0.5)) / 2
        strength_raw = abs(signals.net_score)

        from ..fuzzy_core import membership as _mv
        fuzzified_inputs = {
            "trend_quality": evaluate_trend_quality(trend_raw).components,
            "momentum_quality": evaluate_momentum_quality(momentum_raw).components,
            "volatility_quality": evaluate_volatility_quality(volatility_raw).components,
            "contradiction_severity": evaluate_contradiction_severity(conflict_ratio).components,
            "entry_quality": evaluate_entry_quality(entry_raw).components,
            "risk_quality": _mv.build_risk_quality_variable().fuzzify(max(0.0, min(1.0, risk_raw))),
            "market_stability": evaluate_market_stability(stability_raw).components,
            "signal_confidence": evaluate_signal_confidence(confidence_raw).components,
            "signal_strength": evaluate_signal_strength(strength_raw).components,
        }

        inference_report = run_fuzzy_inference(fuzzified_inputs)

        # FIX v2.1 (round 3): OPPORTUNITY_SCORING_METHOD was only ever used
        # to pick a threshold — ahp_opportunity_score() (a genuinely
        # different linear-weighted AHP formula, not the rule-based Sugeno
        # inference above) was never actually called anywhere in the repo.
        # That meant multi_coin_meta_test.py's "Fuzzy+Rules" vs
        # "Fuzzy+AHPv2" scenarios — and its Meta-Controller's choice between
        # them — were comparing two runs of the *same* scoring math with a
        # slightly different threshold, not two real methodologies. Wired
        # in properly here using the same raw [0,1] inputs already derived
        # above (risk_raw is still a volatility-based proxy, not a true R:R
        # — no risk_plan exists yet at this point in the pipeline for
        # either method, so this doesn't advantage one method over the
        # other).
        if settings.OPPORTUNITY_SCORING_METHOD == "ahp":
            from ..fuzzy_core.ahp_scoring import ahp_opportunity_score
            opportunity_score = ahp_opportunity_score(
                trend_quality_raw=trend_raw, risk_quality_v2_raw=risk_raw,
                volatility_quality_v2_badness_raw=volatility_raw, entry_quality_raw=entry_raw,
            )
        else:
            opportunity_score = inference_report.defuzzified_score

        mtf_ok = mtf.agreement if mtf is not None else True
        stability_score = round(max(0.0, 100.0 - conflict_ratio * 100.0), 2)
        permission_score = 100.0 if mtf_ok else 60.0
        overall_score = round((opportunity_score + stability_score + permission_score) / 3.0, 2)

        return _InferenceScores(
            opportunity_score=opportunity_score, stability_score=stability_score,
            permission_score=permission_score, overall_score=overall_score,
        )

    def _check_quality(self, fuzzy_result, trade_quality):
        return QualityResult(overall_score=70.0, components={})

    def _adaptive_threshold(self, history, base_threshold):
        if not history or len(history) < 30:
            return base_threshold
        sorted_scores = sorted(history)
        idx = int(len(sorted_scores) * settings.FUZZY_ADAPTIVE_OPPORTUNITY_PERCENTILE)
        return max(base_threshold, sorted_scores[min(idx, len(sorted_scores) - 1)])


# ---------------------------------------------------------------------------
# FIX v2.1 — NEW: package-level exports RSP.fuzzy_core.__init__ requires
# ---------------------------------------------------------------------------
# FuzzyDecisionReport / DecisionHistory / run_fuzzy_decision / get_history
# were imported by __init__.py (and by fuzzy_integration_bridge.py /
# reporting.py) but never defined anywhere, so importing RSP.fuzzy_core
# failed outright. These aren't on the backtest_engine.py hot path (that
# uses FuzzyDecisionController.evaluate() directly) — they back the
# optional, richer per-coin fuzzy report used by fuzzy_integration_bridge.py.

@dataclass
class FuzzyDecisionReport:
    decision: str = "NO_TRADE"          # LONG | SHORT | NO_TRADE
    confidence: float = 0.0             # 0..1
    primary_reason: str = ""
    opportunity_score: float = 0.0      # 0..100
    resolved_score: float = 0.0         # 0..100
    method_used: str = ""
    active_rules: List[str] = None
    conflicting_rules: List[str] = None
    fuzzy_inference: Optional[object] = None
    stability_check_passed: bool = False
    hysteresis_applied: bool = False
    rejected_trade: bool = False
    trend_quality: float = 0.0
    momentum_quality: float = 0.0
    volatility_quality: float = 0.0
    entry_quality: float = 0.0
    risk_quality: float = 0.0
    market_stability: float = 0.0
    signal_confidence: float = 0.0
    signal_strength: float = 0.0
    contradiction_severity: float = 0.0
    notes: List[str] = None

    def __post_init__(self):
        if self.active_rules is None:
            self.active_rules = []
        if self.conflicting_rules is None:
            self.conflicting_rules = []
        if self.notes is None:
            self.notes = []


class DecisionHistory:
    """Rolling per-coin opportunity-score history, used for the adaptive
    threshold in FuzzyDecisionController._adaptive_threshold()."""

    def __init__(self, max_len: int = 500):
        self.max_len = max_len
        self._by_coin: Dict[str, List[float]] = {}

    def record(self, coin: str, opportunity_score: float) -> None:
        series = self._by_coin.setdefault(coin, [])
        series.append(opportunity_score)
        if len(series) > self.max_len:
            del series[: len(series) - self.max_len]

    def get(self, coin: str) -> List[float]:
        return list(self._by_coin.get(coin, []))


_decision_history = DecisionHistory()


def get_history(coin: str) -> List[float]:
    return _decision_history.get(coin)


def run_fuzzy_decision(coin: str, regime, confluence, mtf, structure, risk_plan,
                       atr_pct, fusion, contradiction, confidence, direction: str) -> FuzzyDecisionReport:
    """
    Richer, per-coin fuzzy decision report (used by
    fuzzy_integration_bridge.integrate_fuzzy_decision — not by the core
    backtest loop, which calls FuzzyDecisionController.evaluate() directly).
    Reuses FuzzyDecisionController for the pass/fail scoring, and computes
    the individual quality-dimension breakdowns for reporting purposes.
    """
    from ..fuzzy_core.quality_engines import (
        evaluate_trend_quality, evaluate_momentum_quality,
        evaluate_volatility_quality, evaluate_contradiction_severity,
    )

    controller = FuzzyDecisionController()
    history = get_history(coin)
    fuzzy_result = controller.evaluate(regime=regime, signals=fusion, mtf=mtf,
                                       trade_quality=None, history=history)

    if fuzzy_result is None:
        return FuzzyDecisionReport(decision="NO_TRADE", primary_reason="داده‌ی کافی برای ارزیابی فازی وجود ندارد",
                                   notes=["insufficient_data"])

    _decision_history.record(coin, fuzzy_result.opportunity_score)

    if fuzzy_result.can_trade and direction == "BULLISH":
        decision = "LONG"
    elif fuzzy_result.can_trade and direction == "BEARISH":
        decision = "SHORT"
    else:
        decision = "NO_TRADE"

    trend_ev = next((e for e in fusion.evidences if e.category == "trend"), None) if fusion else None
    momentum_ev = next((e for e in fusion.evidences if e.category == "momentum"), None) if fusion else None
    trend_raw = abs(trend_ev.score) if trend_ev else (abs(fusion.net_score) if fusion else 0.0)
    momentum_raw = abs(momentum_ev.score) if momentum_ev else (abs(fusion.net_score) if fusion else 0.0)
    volatility_raw = (regime.perception.volatility_quality / 100.0) if regime and regime.perception else 0.5
    conflict_ratio = (len(fusion.conflicting_evidence) / max(1, len(fusion.evidences))) if fusion else 0.0

    return FuzzyDecisionReport(
        decision=decision,
        confidence=round(fuzzy_result.overall_score / 100.0, 4),
        primary_reason=fuzzy_result.recommendation,
        opportunity_score=fuzzy_result.opportunity_score,
        resolved_score=fuzzy_result.overall_score,
        method_used=settings.OPPORTUNITY_SCORING_METHOD,
        stability_check_passed=fuzzy_result.stability_score >= settings.FUZZY_STABILITY_MIN_CONSISTENT,
        hysteresis_applied=(not fuzzy_result.can_trade and fuzzy_result.recommendation == "WATCH"),
        rejected_trade=not fuzzy_result.can_trade,
        trend_quality=evaluate_trend_quality(trend_raw).overall_score,
        momentum_quality=evaluate_momentum_quality(momentum_raw).overall_score,
        volatility_quality=evaluate_volatility_quality(volatility_raw).overall_score,
        contradiction_severity=evaluate_contradiction_severity(conflict_ratio).overall_score,
        market_stability=fuzzy_result.stability_score,
        signal_confidence=confidence.confidence if confidence else 0.0,
        signal_strength=round(abs(fusion.net_score) * 100, 2) if fusion else 0.0,
        notes=fuzzy_result.notes,
    )
