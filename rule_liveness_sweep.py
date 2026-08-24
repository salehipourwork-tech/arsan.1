"""
rule_liveness_sweep.py — READ-ONLY. Does not modify any rule, threshold,
weight, membership function, or strategy parameter. Runs the existing
FuzzyDecisionController.evaluate() exactly as-is and only OBSERVES which
rules fire, via evaluate_rules() (also unmodified) on the same fuzzified
inputs the real pipeline computes internally.

Usage (from repo root, same as diag_fuzzy_funnel.py):
    python rule_liveness_sweep.py --coin bitcoin --days 90 --calibrated-threshold 75
"""
import argparse
import statistics

from RSP.config import settings
from RSP.ingestion.data_universe import build_data_universe
from RSP.decision_engine.decision_brain import make_decision
from RSP.regime_engine.regime_engine import detect_regime
from RSP.fuzzy_core.decision_controller import FuzzyDecisionController
from RSP.fuzzy_core.rule_base import evaluate_rules, OPPORTUNITY_RULES
from RSP.fuzzy_core.quality_engines import (
    evaluate_trend_quality, evaluate_momentum_quality,
    evaluate_volatility_quality, evaluate_contradiction_severity,
    evaluate_entry_quality, evaluate_market_stability,
    evaluate_signal_confidence, evaluate_signal_strength,
)
from RSP.fuzzy_core import membership as _mv
from RSP.risk_engine.risk_engine import plan_risk
from RSP.risk_engine.trade_quality import assess_trade_quality
from RSP.preprocessing.quality_engine import check_quality

TARGET_RULES = ["R01", "R02", "R04", "R06", "R10", "R12", "R13", "R14", "R17", "R19", "R20"]

NEW_RR, NEW_SL_MULT, NEW_EXIT, METHOD = 2.5, 1.5, "PROPORTIONAL", "rules"


def _known_slice(bars_by_tf, ts):
    return {tf: df[df.index < ts].copy() for tf, df in bars_by_tf.items()}


def _get_real_fuzzified(fuzzy_controller, regime, signals, mtf, trade_quality):
    """Calls the REAL, current _run_inference() and returns the exact
    fuzzified_inputs dict it used — no hand-copied formulas here, so this
    can never drift out of sync with decision_controller.py again."""
    computed = fuzzy_controller._run_inference(regime, signals, mtf, trade_quality)
    if computed is None:
        return None
    return computed.fuzzified_inputs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coin", default="bitcoin")
    ap.add_argument("--days", type=float, default=90)
    ap.add_argument("--calibrated-threshold", type=float, default=75.0)
    args = ap.parse_args()

    settings.RR_TARGET = NEW_RR
    settings.SL_ATR_MULTIPLIER = NEW_SL_MULT
    settings.CONSERVATIVE_SL_TP_SAME_CANDLE = NEW_EXIT
    settings.FUZZY_BACKTEST_ENABLED = True
    settings.META_CONTROLLER_ENABLED = False
    settings.OPPORTUNITY_SCORING_METHOD = METHOD

    universe = build_data_universe(args.coin, lookback_days=args.days)
    bars_by_tf = universe.bars
    base_tf = "15M"
    base_df = bars_by_tf.get(base_tf)
    min_history = 200
    quality = check_quality(base_df, base_tf)

    fuzzy_controller = FuzzyDecisionController()

    fire_count = {r: 0 for r in TARGET_RULES}
    max_strength = {r: 0.0 for r in TARGET_RULES}
    n_candidates = 0
    opportunity_scores = []

    for i in range(min_history, len(base_df)):
        ts = base_df.index[i]
        known = _known_slice(bars_by_tf, ts)
        known_base = known.get(base_tf)
        if known_base is None or known_base.empty:
            continue

        regime = detect_regime(known_base)
        decision = make_decision(known, regime)
        if not decision or decision.action not in ("BUY", "SELL"):
            continue
        n_candidates += 1

        # Real risk_plan/trade_quality, computed BEFORE the fuzzy call —
        # matches the now-fixed backtest_engine.py order. Previously this
        # script passed trade_quality=None here (mirroring the pre-fix
        # backtest_engine.py), which silently defeated the risk_quality
        # fix even after decision_controller.py and backtest_engine.py
        # were both updated.
        risk_plan = plan_risk(decision.action, known_base, regime)
        trade_quality = None
        if risk_plan.valid and risk_plan.risk_reward is not None:
            try:
                trade_quality = assess_trade_quality(risk_plan, quality, regime, decision.fusion)
            except Exception:
                trade_quality = None

        # Real, unmodified pipeline call (for the actual opportunity_score)
        fuzzy_result = fuzzy_controller.evaluate(
            regime=regime, signals=decision.fusion, mtf=decision.mtf,
            trade_quality=trade_quality, history=None, coin=args.coin,
            contradiction=decision.contradiction,
        )
        if fuzzy_result:
            opportunity_scores.append(fuzzy_result.opportunity_score)

        # Observation-only: the REAL fuzzified inputs (no hand-copied formulas)
        fuzzified = _get_real_fuzzified(fuzzy_controller, regime, decision.fusion, decision.mtf, trade_quality)
        if fuzzified is None:
            continue
        firing = evaluate_rules(fuzzified, OPPORTUNITY_RULES)
        for rid, strength in firing.items():
            if rid in fire_count:
                fire_count[rid] += 1
                if strength > max_strength[rid]:
                    max_strength[rid] = strength

    print(f"n_candidates={n_candidates}")
    print(f"{'rule':<6}{'fire_count':<12}{'fire_rate':<12}{'max_firing_strength':<20}")
    for r in TARGET_RULES:
        rate = (fire_count[r] / n_candidates * 100) if n_candidates else 0.0
        print(f"{r:<6}{fire_count[r]:<12}{rate:<11.2f}%{max_strength[r]:<20.4f}")

    zero_fire = [r for r in TARGET_RULES if fire_count[r] == 0]
    under_5pct = [r for r in TARGET_RULES if n_candidates and (fire_count[r] / n_candidates * 100) < 5 and fire_count[r] > 0]

    print()
    print("fire_count=0:", zero_fire)
    print("fire_rate<5% (and >0):", under_5pct)
    if opportunity_scores:
        print(f"opportunity_score stats: min={min(opportunity_scores):.2f} max={max(opportunity_scores):.2f} "
              f"mean={statistics.mean(opportunity_scores):.2f} median={statistics.median(opportunity_scores):.2f}")
        vals = set(round(v, 2) for v in opportunity_scores)
        print(f"unique opportunity_score values: {sorted(vals)}")


if __name__ == "__main__":
    main()
