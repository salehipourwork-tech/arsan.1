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
    meta_mode: str = ""  # NEW v2.2: populated when META_CONTROLLER_ENABLED


@dataclass
class _InferenceScores:
    """Internal helper — the four numbers evaluate() needs from _run_inference."""
    opportunity_score: float; stability_score: float; permission_score: float; overall_score: float


@dataclass
class _ComputedScores:
    """NEW v2.2 — both scoring methods computed unconditionally (needed for
    the meta-controller to blend/compare them), plus the single-method
    result (`static`) that the pre-existing static threshold path uses."""
    rules_score: float; ahp_score: float
    rules_threshold: float; ahp_threshold: float
    stability_score: float; permission_score: float
    static: _InferenceScores


class FuzzyDecisionController:
    def __init__(self):
        self.regime_filter = RegimeRuleFilter()
        self.history: Dict[str, List[float]] = {}

    def evaluate(self, regime, signals, mtf, trade_quality, history,
                coin: str = "", contradiction=None) -> Optional[FuzzyDecisionResult]:
        notes = []

        # FIX v2.0: Apply RegimeRuleFilter
        if regime and hasattr(regime, 'regime'):
            regime_label = regime.regime
            filtered_signals = self.regime_filter.filter_rules(signals, regime_label)
            if filtered_signals != signals:
                notes.append(f"regime_filter_applied:{regime_label}")
            signals = filtered_signals

        computed = self._run_inference(regime, signals, mtf, trade_quality)
        if computed is None:
            return None

        # NEW v2.2: wire in the previously-orphaned adaptive per-bar
        # RSP.meta_controller — opt-in via settings.META_CONTROLLER_ENABLED
        # (default False, so existing static single-method threshold
        # behavior — and every already-reported backtest number — is
        # unchanged unless explicitly turned on). Unlike the static path,
        # the meta-controller blends Rules/AHP by market context
        # (volatility/contradiction/regime) and can hard-block into
        # PRESERVATION mode on extreme conditions, or fall back to whichever
        # engine has been performing better recently.
        if getattr(settings, "META_CONTROLLER_ENABLED", False):
            return self._evaluate_via_meta_controller(regime, signals, mtf, coin, contradiction, computed, notes)

        fuzzy_result = computed.static
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

    def _evaluate_via_meta_controller(self, regime, signals, mtf, coin, contradiction, computed, notes):
        from ..meta_controller.meta_controller import EngineDecision, run_meta_controller

        direction = "LONG" if signals.net_score > 0 else ("SHORT" if signals.net_score < 0 else "HOLD")
        # NEW v2.2: both engines currently derive direction identically from
        # the same net_score (direction selection isn't the fuzzy layer's
        # job — see decision_brain.decide()); they differ only in
        # opportunity_score/confidence/rejected, which is where the
        # meta-controller's blending actually has something to weigh.
        rules_dec = EngineDecision(
            engine="rules", direction=direction, confidence=computed.rules_score / 100.0,
            opportunity_score=computed.rules_score,
            rejected=computed.rules_score < computed.rules_threshold,
        )
        ahp_dec = EngineDecision(
            engine="ahp", direction=direction, confidence=computed.ahp_score / 100.0,
            opportunity_score=computed.ahp_score,
            rejected=computed.ahp_score < computed.ahp_threshold,
        )

        atr_pct = regime.perception.atr_pct if regime and regime.perception else 2.0
        atr_series = regime.perception.atr_pct_series if regime and regime.perception else None
        adx_val = regime.perception.adx if regime and regime.perception else 25.0

        meta = run_meta_controller(
            coin=coin, rules_decision=rules_dec, ahp_decision=ahp_dec, regime=regime,
            atr_pct=atr_pct, atr_pct_series=atr_series, adx_value=adx_val,
            contradiction_report=contradiction, market_stability_score=computed.stability_score / 100.0,
        )

        can_trade = meta.final_direction in ("LONG", "SHORT") and meta.no_trade_weight < 1.0
        notes = notes + [f"meta_mode:{meta.mode}", meta.mode_reason] + meta.fusion_notes

        result = FuzzyDecisionResult(
            can_trade=can_trade, opportunity_score=round(meta.final_confidence * 100, 2),
            stability_score=computed.stability_score, permission_score=computed.permission_score,
            overall_score=round(meta.final_confidence * 100, 2),
            recommendation=("TRADE" if can_trade else "NO_TRADE"), notes=notes,
            meta_mode=meta.mode,
        )
        return result

    def _run_inference(self, regime, signals, mtf, trade_quality=None):
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

        # FIX (this session): risk_quality and market_stability used to be
        # deterministic mirrors of volatility_quality and contradiction_
        # severity respectively (risk_raw = 1-volatility_raw, stability_raw
        # = 1-conflict_ratio) — i.e. they carried zero independent
        # information, so any rule requiring a *different* tier on the
        # mirrored variable than what the source variable already implied
        # (e.g. R17 needs market_stability="strong" while a clean signal's
        # conflict_ratio≈0 always forces market_stability="very_strong")
        # was structurally unreachable. Rule Liveness Sweep on real BTC
        # data confirmed R12/R17/R19 fire_count=0 for exactly this reason.
        #
        # risk_quality now comes from the real TradeQualityReport
        # (risk:reward + data quality + regime quality + volume + setup —
        # see risk_engine/trade_quality.py), which backtest_engine.py now
        # computes BEFORE calling evaluate() and passes in as
        # trade_quality. Falls back to the old volatility-derived proxy
        # only when no trade_quality is available (e.g. risk_plan invalid,
        # or a caller that hasn't been updated to pass it).
        if trade_quality is not None and getattr(trade_quality, "overall_score", None) is not None:
            risk_raw = max(0.0, min(1.0, trade_quality.overall_score / 100.0))
        else:
            risk_raw = max(0.0, 1.0 - volatility_raw)

        # market_stability now comes from the coefficient of variation of
        # recent ATR% (regime.perception.atr_pct_series) — how consistent
        # recent volatility has been, a genuinely different signal from
        # conflict_ratio (evidence agreement on the CURRENT bar). Falls
        # back to the old conflict_ratio-derived proxy when too little ATR
        # history is available to compute a meaningful variance.
        atr_series = list(getattr(regime.perception, "atr_pct_series", []) or []) \
            if regime and regime.perception else []
        recent_atr = atr_series[-20:] if len(atr_series) >= 10 else []
        if recent_atr:
            mean_atr = sum(recent_atr) / len(recent_atr)
            if mean_atr > 0:
                variance = sum((v - mean_atr) ** 2 for v in recent_atr) / len(recent_atr)
                coeff_of_variation = (variance ** 0.5) / mean_atr
                stability_raw = max(0.0, min(1.0, 1.0 - coeff_of_variation))
            else:
                stability_raw = 0.5
        else:
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

        # FIX v2.1 (round 3) / NEW v2.2: OPPORTUNITY_SCORING_METHOD used to
        # only ever pick a threshold — ahp_opportunity_score() (a genuinely
        # different linear-weighted AHP formula, not the rule-based Sugeno
        # inference above) was never actually called anywhere in the repo.
        # That meant "Fuzzy+Rules" vs "Fuzzy+AHPv2" — and any comparison
        # between them — compared two runs of the *same* scoring math with
        # a slightly different threshold, not two real methodologies.
        # NEW v2.2: both scores are now always computed (not just the
        # currently-configured one), since the meta-controller needs both
        # simultaneously to blend/compare them; risk_raw is still a
        # volatility-based proxy, not a true R:R — no risk_plan exists yet
        # at this point in the pipeline for either method, so this doesn't
        # advantage one method over the other.
        from ..fuzzy_core.ahp_scoring import ahp_opportunity_score
        rules_score = inference_report.defuzzified_score
        ahp_score = ahp_opportunity_score(
            trend_quality_raw=trend_raw, risk_quality_v2_raw=risk_raw,
            volatility_quality_v2_badness_raw=volatility_raw, entry_quality_raw=entry_raw,
        )

        threshold_by_method = getattr(settings, "FUZZY_OPPORTUNITY_THRESHOLD_BY_METHOD", {})
        rules_threshold = threshold_by_method.get("rules", settings.FUZZY_OPPORTUNITY_THRESHOLD)
        ahp_threshold = threshold_by_method.get("ahp", settings.FUZZY_OPPORTUNITY_THRESHOLD) + 5.0

        opportunity_score = ahp_score if settings.OPPORTUNITY_SCORING_METHOD == "ahp" else rules_score

        mtf_ok = mtf.agreement if mtf is not None else True
        stability_score = round(max(0.0, 100.0 - conflict_ratio * 100.0), 2)
        permission_score = 100.0 if mtf_ok else 60.0
        overall_score = round((opportunity_score + stability_score + permission_score) / 3.0, 2)

        return _ComputedScores(
            rules_score=rules_score, ahp_score=ahp_score,
            rules_threshold=rules_threshold, ahp_threshold=ahp_threshold,
            stability_score=stability_score, permission_score=permission_score,
            static=_InferenceScores(
                opportunity_score=opportunity_score, stability_score=stability_score,
                permission_score=permission_score, overall_score=overall_score,
            ),
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
                                       trade_quality=None, history=history,
                                       coin=coin, contradiction=contradiction)

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
