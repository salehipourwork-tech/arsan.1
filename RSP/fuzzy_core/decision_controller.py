"""
RSP — Fuzzy Decision Controller v2.0
PATCH: Per-method threshold, RegimeRuleFilter wired, adaptive threshold
"""

from dataclasses import dataclass
from typing import Optional, Dict, List
from ..config import settings
from ..fuzzy_core.inference import FuzzyInferenceResult
from ..fuzzy_core.quality_engines import QualityResult
from ..regime_rule_filter import RegimeRuleFilter


@dataclass
class FuzzyDecisionResult:
    can_trade: bool; opportunity_score: float; stability_score: float
    permission_score: float; overall_score: float; recommendation: str; notes: List[str]


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
        from ..fuzzy_core.inference import run_fuzzy_inference
        return run_fuzzy_inference(regime, signals, mtf)

    def _check_quality(self, fuzzy_result, trade_quality):
        return QualityResult(overall_score=70.0, components={})

    def _adaptive_threshold(self, history, base_threshold):
        if not history or len(history) < 30:
            return base_threshold
        sorted_scores = sorted(history)
        idx = int(len(sorted_scores) * settings.FUZZY_ADAPTIVE_OPPORTUNITY_PERCENTILE)
        return max(base_threshold, sorted_scores[min(idx, len(sorted_scores) - 1)])
