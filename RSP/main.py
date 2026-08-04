import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from RSP.fuzzy_integration_bridge import integrate_fuzzy_decision
from RSP.ingestion.data_universe import build_data_universe
from RSP.ingestion.multi_source_router import fetch_data
from RSP.preprocessing.quality_engine import check_all_timeframes
from RSP.regime_engine.regime_engine import determine_regime
from RSP.signal_engine.confluence import analyze_confluence
from RSP.multi_timeframe.mtf_brain import analyze_mtf
from RSP.signal_fusion.fusion_engine import fuse_signals
from RSP.contradiction_engine.contradiction_engine import detect_contradictions
from RSP.confidence_engine.confidence_engine import compute_confidence
from RSP.decision_engine.decision_brain import decide
from RSP.risk_engine.risk_engine import plan_risk
from RSP.risk_engine.trade_quality import evaluate_trade_quality
from RSP.strategy_lab.selector import select_strategy
from RSP.reporting.explainability import build_report
from RSP.backtest_engine.backtest_engine import run_backtest
from RSP.experiment_manager.experiment_manager import log_experiment
from RSP.config import settings


def run_analysis(coin, timeframe="1h"):
    print(f"\n{'='*60}")
    print(f"RSP Analysis: {coin.upper()} | {timeframe}")
    print(f"{'='*60}\n")

    universe = build_data_universe([coin])
    base_df = fetch_data(coin, timeframe)

    if base_df is None or base_df.empty:
        print("ERROR: No data fetched. Check symbol or network.")
        return

    base_quality = check_all_timeframes(coin, base_df)
    regime = determine_regime(base_df)
    confluence = analyze_confluence(base_df)
    mtf = analyze_mtf(coin, base_df)
    fusion = fuse_signals(regime, confluence, mtf)
    contradiction = detect_contradictions(fusion, mtf)
    confidence = compute_confidence(
        fusion, mtf, contradiction,
        base_quality.quality_score if base_quality else 0.0,
        regime.perception.atr_pct if regime else 0.0
    )

    decision = decide(regime, fusion, mtf, contradiction, confidence,
                      base_quality.quality_ok if base_quality else False)

    # --- FUZZY ENGINE INTEGRATION (Phases 27-50) ---
    integrated = integrate_fuzzy_decision(
        coin=coin,
        crisp_decision=decision,
        regime=regime,
        confluence=confluence,
        mtf=mtf,
        structure=structure if 'structure' in locals() else None,
        risk_plan=risk_plan if 'risk_plan' in locals() else None,
        atr_pct=atr_pct if 'atr_pct' in locals() else 2.0,
        fusion=fusion,
        contradiction=contradiction,
        confidence=confidence,
    )
    decision.direction = integrated.final_direction
    decision.confidence = int(integrated.final_confidence * 100)
    # --- END FUZZY ---

    risk_plan = None
    trade_quality = None
    selection = select_strategy(regime, fusion) if regime else None

    if decision.action in ("BUY", "SELL"):
        risk_plan = plan_risk(decision.action, base_df, regime)
        trade_quality = evaluate_trade_quality(
            confidence.confidence,
            base_quality.quality_score if base_quality else 0.0,
            risk_plan.risk_reward if risk_plan else 0.0,
            selection.selected is not None if selection else False
        )
        if not (risk_plan.valid and trade_quality.passed):
            decision.action = "NO_TRADE"
            decision.why.append(
                f"Trade Quality/Risk Gate: risk_ok={risk_plan.valid}, "
                f"quality_ok={trade_quality.passed}"
            )

    report = build_report(
        decision, confidence, regime, selection, risk_plan, trade_quality,
        base_quality, universe.source_used
    )
    print(report)

    if settings.LOG_EXPERIMENTS:
        log_experiment(coin, report)


def main():
    parser = argparse.ArgumentParser(description="RSP — Research & Strategy Platform")
    parser.add_argument("--coin", default="bitcoin", help="Coin symbol (default: bitcoin)")
    parser.add_argument("--timeframe", default="1h", help="Timeframe (default: 1h)")
    parser.add_argument("--backtest", action="store_true", help="Run backtest mode")
    parser.add_argument("--walkforward", action="store_true", help="Run walk-forward analysis")
    parser.add_argument("--stress", action="store_true", help="Run stress test")
    parser.add_argument("--montecarlo", action="store_true", help="Run Monte Carlo simulation")
    parser.add_argument("--versions", action="store_true", help="Compare strategy versions")
    parser.add_argument("--challenge", nargs=2, metavar=("V1", "V2"), help="Challenger system: V1 vs V2")
    parser.add_argument("--compare-arsan", action="store_true", help="Compare with Arsan baseline")
    args = parser.parse_args()

    if args.backtest:
        run_backtest(args.coin, args.timeframe)
    elif args.walkforward:
        from RSP.walk_forward.walk_forward import run_walk_forward
        run_walk_forward(args.coin, args.timeframe)
    elif args.stress:
        from RSP.robustness.stress_test import run_stress_test
        run_stress_test(args.coin, args.timeframe)
    elif args.montecarlo:
        from RSP.robustness.monte_carlo import run_monte_carlo
        run_monte_carlo(args.coin, args.timeframe)
    elif args.versions:
        from RSP.strategy_lab.versioning import compare_versions
        compare_versions(args.coin, args.timeframe)
    elif args.challenge:
        from RSP.strategy_lab.challenger import run_challenger
        run_challenger(args.coin, args.timeframe, args.challenge[0], args.challenge[1])
    elif args.compare_arsan:
        from RSP.comparison.arsan_vs_rsp import compare_with_arsan
        compare_with_arsan(args.coin, args.timeframe)
    else:
        run_analysis(args.coin, args.timeframe)


if __name__ == "__main__":
    main()
