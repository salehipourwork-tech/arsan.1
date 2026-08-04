"""
RSP — main.py (with Fuzzy Engine Integration)
Compatible with existing project structure.
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Fuzzy integration (safe import)
try:
    from RSP.fuzzy_integration_bridge import integrate_fuzzy_decision
    FUZZY_AVAILABLE = True
except Exception:
    FUZZY_AVAILABLE = False

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
    print("\n" + "=" * 60)
    print("RSP Analysis: " + coin.upper() + " | " + timeframe)
    print("=" * 60 + "\n")

    # Fetch data directly from multi_source_router
    base_df = None
    source_used = "unknown"
    try:
        from RSP.ingestion.multi_source_router import fetch_with_fallback
        base_df = fetch_with_fallback(coin, timeframe, limit=500)
        source_used = "multi_source"
    except Exception as e1:
        print("multi_source_router failed: " + str(e1))
        try:
            from RSP.analyzer.fetch_data import fetch_ohlcv
            base_df = fetch_ohlcv(coin, timeframe)
            source_used = "analyzer"
        except Exception as e2:
            print("analyzer.fetch_data failed: " + str(e2))
            try:
                from RSP.ingestion.sources.binance_source import fetch_ohlcv
                base_df = fetch_ohlcv(coin, timeframe, limit=500)
                source_used = "binance"
            except Exception as e3:
                print("ERROR: Could not fetch data — " + str(e3))
                return

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
    if FUZZY_AVAILABLE and getattr(settings, 'FUZZY_BACKTEST_ENABLED', False):
        try:
            integrated = integrate_fuzzy_decision(
                coin=coin,
                crisp_decision=decision,
                regime=regime,
                confluence=confluence,
                mtf=mtf,
                structure=None,
                risk_plan=None,
                atr_pct=2.0,
                fusion=fusion,
                contradiction=contradiction,
                confidence=confidence,
            )
            decision.direction = integrated.final_direction
            decision.confidence = int(integrated.final_confidence * 100)
            print("[Fuzzy Engine] Decision integrated.")
        except Exception as e:
            print("[Fuzzy Engine] Skipped: " + str(e))
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
                "Trade Quality/Risk Gate: risk_ok=" + str(risk_plan.valid) + 
                ", quality_ok=" + str(trade_quality.passed)
            )

    report = build_report(
        decision, confidence, regime, selection, risk_plan, trade_quality,
        base_quality, source_used
    )
    print(report)

    if getattr(settings, 'LOG_EXPERIMENTS', False):
        log_experiment(coin, report)


def main():
    parser = argparse.ArgumentParser(description="RSP — Research & Strategy Platform")
    parser.add_argument("--coin", default="bitcoin", help="Coin symbol")
    parser.add_argument("--timeframe", default="1h", help="Timeframe")
    parser.add_argument("--backtest", action="store_true", help="Run backtest")
    parser.add_argument("--walkforward", action="store_true")
    parser.add_argument("--stress", action="store_true")
    parser.add_argument("--montecarlo", action="store_true")
    parser.add_argument("--versions", action="store_true")
    parser.add_argument("--challenge", nargs=2, metavar=("V1", "V2"))
    parser.add_argument("--compare-arsan", action="store_true")
    args = parser.parse_args()

    if args.backtest:
        run_backtest(args.coin, args.timeframe)
    elif args.walkforward:
        try:
            from RSP.walk_forward.walk_forward import run_walk_forward
            run_walk_forward(args.coin, args.timeframe)
        except Exception as e:
            print("Walk-forward error: " + str(e))
    elif args.stress:
        try:
            from RSP.robustness.stress_test import run_stress_test
            run_stress_test(args.coin, args.timeframe)
        except Exception as e:
            print("Stress test error: " + str(e))
    elif args.montecarlo:
        try:
            from RSP.robustness.monte_carlo import run_monte_carlo
            run_monte_carlo(args.coin, args.timeframe)
        except Exception as e:
            print("Monte Carlo error: " + str(e))
    elif args.versions:
        try:
            from RSP.strategy_lab.versioning import compare_versions
            compare_versions(args.coin, args.timeframe)
        except Exception as e:
            print("Version compare error: " + str(e))
    elif args.challenge:
        try:
            from RSP.strategy_lab.challenger import run_challenger
            run_challenger(args.coin, args.timeframe, args.challenge[0], args.challenge[1])
        except Exception as e:
            print("Challenger error: " + str(e))
    elif args.compare_arsan:
        try:
            from RSP.comparison.arsan_vs_rsp import compare_with_arsan
            compare_with_arsan(args.coin, args.timeframe)
        except Exception as e:
            print("Comparison error: " + str(e))
    else:
        run_analysis(args.coin, args.timeframe)


if __name__ == "__main__":
    main()
