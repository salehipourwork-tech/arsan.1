"""
diag_fuzzy_funnel.py — read-only diagnostic. Does NOT modify any RSP file,
does NOT touch threshold or any gate. Reproduces the exact "Rules" scenario
from RSP/multi_coin_meta_test.py for a single coin and prints the funnel:

TOTAL BARS -> SIGNAL CANDIDATES (BUY/SELL) -> FUZZY INFERENCE EXECUTED
-> RULES/AHP SCORE VALID -> OPPORTUNITY SCORE VALID -> CAN_TRADE=True
-> ABOVE_THRESHOLD -> FINAL TRADE

Plus per-candidate rows for the first N candidates.
"""
import argparse
import statistics
import sys

from RSP.config import settings
from RSP.ingestion.data_universe import build_data_universe
from RSP.decision_engine.decision_brain import make_decision
from RSP.regime_engine.regime_engine import detect_regime
from RSP.preprocessing.quality_engine import check_quality
from RSP.fuzzy_core.decision_controller import FuzzyDecisionController
from RSP.risk_engine.risk_engine import plan_risk

# ---- mirror multi_coin_meta_test.py "Rules" scenario params exactly ----
NEW_RR = 2.5
NEW_SL_MULT = 1.5
NEW_EXIT = "PROPORTIONAL"
METHOD = "rules"


def _known_slice(bars_by_tf, ts):
    return {tf: df[df.index < ts].copy() for tf, df in bars_by_tf.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coin", default="bitcoin")
    ap.add_argument("--days", type=float, default=90)
    ap.add_argument("--calibrated-threshold", type=float, default=None,
                     help="pass the exact [CALIBRATE] value printed for this coin/run; "
                          "defaults to the static settings default if omitted")
    ap.add_argument("--print-first", type=int, default=20)
    args = ap.parse_args()

    # Apply the same param set the "Rules" scenario uses (RR/SL/exit + method).
    settings.RR_TARGET = NEW_RR
    settings.SL_ATR_MULTIPLIER = NEW_SL_MULT
    settings.CONSERVATIVE_SL_TP_SAME_CANDLE = NEW_EXIT
    settings.FUZZY_BACKTEST_ENABLED = True
    settings.META_CONTROLLER_ENABLED = False
    settings.OPPORTUNITY_SCORING_METHOD = METHOD

    base_threshold = args.calibrated_threshold
    if base_threshold is None:
        base_threshold = settings.FUZZY_OPPORTUNITY_THRESHOLD_BY_METHOD.get(METHOD, settings.FUZZY_OPPORTUNITY_THRESHOLD)
    by_method = dict(settings.FUZZY_OPPORTUNITY_THRESHOLD_BY_METHOD)
    by_method[METHOD] = base_threshold
    settings.FUZZY_OPPORTUNITY_THRESHOLD_BY_METHOD = by_method
    settings.MIN_OPPORTUNITY_SCORE_FOR_TRADE = base_threshold
    settings.FUZZY_OPPORTUNITY_THRESHOLD = base_threshold

    print(f"coin={args.coin} days={args.days} method={METHOD} threshold={base_threshold} "
          f"stability_min={settings.FUZZY_STABILITY_MIN_CONSISTENT} "
          f"permission_min={settings.FUZZY_TRADE_PERMISSION_MIN} "
          f"adaptive={settings.FUZZY_ADAPTIVE_OPPORTUNITY_THRESHOLD} (history=None in backtest loop -> adaptive never engages)\n")

    universe = build_data_universe(args.coin, lookback_days=args.days)
    bars_by_tf = universe.bars
    base_tf = "15M"
    base_df = bars_by_tf.get(base_tf)
    if base_df is None or base_df.empty:
        print("ERROR: no base_tf data"); sys.exit(1)

    min_history = 200
    quality = check_quality(base_df, base_tf)
    print(f"quality_ok={quality.quality_ok} quality_score={getattr(quality, 'quality_score', None)}")

    fuzzy_controller = FuzzyDecisionController()

    counters = {
        "TOTAL_BARS_IN_LOOP": 0,
        "SIGNAL_CANDIDATES_BUY_SELL": 0,
        "FUZZY_EVALUATE_CALLED": 0,
        "FUZZY_RETURNED_NONE": 0,
        "OPPORTUNITY_SCORE_PRODUCED": 0,
        "CAN_TRADE_TRUE": 0,
        "ABOVE_THRESHOLD_EXPLICIT": 0,  # opportunity_score >= threshold, independent of can_trade
        "RISK_PLAN_VALID": 0,
        "RR_ABOVE_MIN": 0,
        "FINAL_TRADE": 0,
    }

    opp_scores = []
    rows = []

    for i in range(min_history, len(base_df)):
        counters["TOTAL_BARS_IN_LOOP"] += 1
        ts = base_df.index[i]
        known = _known_slice(bars_by_tf, ts)
        known_base = known.get(base_tf)
        if known_base is None or known_base.empty:
            continue

        regime = detect_regime(known_base)
        decision = make_decision(known, regime)
        if not decision or decision.action not in ("BUY", "SELL"):
            continue
        counters["SIGNAL_CANDIDATES_BUY_SELL"] += 1

        counters["FUZZY_EVALUATE_CALLED"] += 1
        fuzzy_result = fuzzy_controller.evaluate(
            regime=regime, signals=decision.fusion, mtf=decision.mtf,
            trade_quality=None, history=None, coin=args.coin,
            contradiction=decision.contradiction,
        )

        row = {
            "timestamp": str(ts), "signal": decision.action,
            "regime": getattr(regime, "regime", None),
            "confidence": round(decision.confidence, 4) if decision.confidence else None,
            "contradiction": round(decision.contradiction.conflict_ratio, 4) if decision.contradiction else None,
        }

        if fuzzy_result is None:
            counters["FUZZY_RETURNED_NONE"] += 1
            row.update(opportunity_score=None, threshold=base_threshold, can_trade=False,
                       rejection_reason="fuzzy_evaluate_returned_None", final_score=None)
            rows.append(row)
            continue

        counters["OPPORTUNITY_SCORE_PRODUCED"] += 1
        opp_scores.append(fuzzy_result.opportunity_score)

        method = settings.OPPORTUNITY_SCORING_METHOD
        threshold = settings.FUZZY_OPPORTUNITY_THRESHOLD_BY_METHOD.get(method, settings.FUZZY_OPPORTUNITY_THRESHOLD)

        above_threshold = fuzzy_result.opportunity_score >= threshold
        if above_threshold:
            counters["ABOVE_THRESHOLD_EXPLICIT"] += 1
        if fuzzy_result.can_trade:
            counters["CAN_TRADE_TRUE"] += 1

        rejection_reason = None
        if not fuzzy_result.can_trade:
            if not above_threshold:
                rejection_reason = "opportunity_score_below_threshold"
            elif fuzzy_result.stability_score < settings.FUZZY_STABILITY_MIN_CONSISTENT:
                rejection_reason = "stability_score_below_min"
            elif fuzzy_result.permission_score < settings.FUZZY_TRADE_PERMISSION_MIN:
                rejection_reason = "permission_score_below_min"
            else:
                rejection_reason = "can_trade_false_unexplained"

        row.update(
            opportunity_score=fuzzy_result.opportunity_score,
            stability_score=fuzzy_result.stability_score,
            permission_score=fuzzy_result.permission_score,
            threshold=threshold, can_trade=fuzzy_result.can_trade,
            recommendation=fuzzy_result.recommendation,
            rejection_reason=rejection_reason,
            final_score=fuzzy_result.overall_score,
        )
        rows.append(row)

        if not fuzzy_result.can_trade:
            continue
        if fuzzy_result.opportunity_score < threshold:
            continue

        # past the fuzzy gate -> continue funnel like backtest_engine does
        risk_plan = plan_risk(decision.action, known_base, regime)
        if not risk_plan.valid or risk_plan.risk_reward is None:
            row["rejection_reason"] = "risk_plan_invalid_after_fuzzy_gate"
            continue
        counters["RISK_PLAN_VALID"] += 1
        if risk_plan.risk_reward < settings.MIN_ACCEPTABLE_RISK_REWARD:
            row["rejection_reason"] = "risk_reward_below_min_after_fuzzy_gate"
            continue
        counters["RR_ABOVE_MIN"] += 1
        counters["FINAL_TRADE"] += 1  # (still subject to simulate_trade OPEN-outcome filtering in real engine)

    print("=" * 70)
    print("FUNNEL")
    print("=" * 70)
    for k, v in counters.items():
        print(f"{k:<32} {v}")

    print("\n" + "=" * 70)
    print("OPPORTUNITY SCORE STATS (over all candidates where a score was produced)")
    print("=" * 70)
    if opp_scores:
        print(f"n={len(opp_scores)} min={min(opp_scores):.2f} max={max(opp_scores):.2f} "
              f"mean={statistics.mean(opp_scores):.2f} median={statistics.median(opp_scores):.2f}")
        n_invalid = sum(1 for s in opp_scores if s == -999)
        print(f"scores_equal_to_-999={n_invalid}")
        print(f"threshold_in_effect={base_threshold}")
        n_at_or_above = sum(1 for s in opp_scores if s >= base_threshold)
        print(f"candidates_at_or_above_threshold={n_at_or_above}")
    else:
        print("NO opportunity scores were produced at all (fuzzy_controller.evaluate() "
              "returned None every time, or there were zero BUY/SELL candidates).")

    print("\n" + "=" * 70)
    print(f"FIRST {args.print_first} CANDIDATE ROWS")
    print("=" * 70)
    for row in rows[:args.print_first]:
        print(row)


if __name__ == "__main__":
    main()
