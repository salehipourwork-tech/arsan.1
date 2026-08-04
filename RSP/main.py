"""
RSP — main.py (with Fuzzy Engine Integration)
"""
import os
import sys
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

    routed = None
    source_used = "unknown"
    try:
        from RSP.ingestion.multi_source_router import fetch_with_fallback
        routed = fetch_with_fallback(coin, timeframe, limit=500)
        source_used = getattr(routed, "source", "multi_source")
    except Exception as e1:
        print("multi_source_router failed: " + str(e1))
        try:
            from RSP.analyzer.fetch_data import fetch_ohlcv
            routed = fetch_ohlcv(coin, timeframe)
            source_used = "analyzer"
        except Exception as e2:
            print("analyzer.fetch_data failed: " + str(e2))
            try:
                from RSP.ingestion.sources.binance_source import fetch_ohlcv
                routed = fetch_ohlcv(coin, timeframe, limit=500)
                source_used = "binance"
            except Exception as e3:
                print("ERROR: Could not fetch data — " + str(e3))
                return

    # Extract DataFrame — try .data first, then direct object
    base_df = None
    try:
        base_df = routed.data
        print("[DEBUG] Used .data attribute")
    except Exception:
        try:
            base_df = routed.df
            print("[DEBUG] Used .df attribute")
        except Exception:
            try:
                if hasattr(routed, "empty"):
                    base_df = routed
                    print("[DEBUG] Used object directly (DataFrame-like)")
            except Exception:
                pass

    if base_df is None:
        print("ERROR: Could not extract DataFrame from fetcher.")
        return
    if hasattr(base_df, "empty") and base_df.empty:
        print("ERROR: Empty DataFrame returned.")
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

    # --- FUZZY ENGINE ---
    if FUZZY_AVAILABLE and getattr(settings, 'FUZZY_BACKTEST_ENABLED', False):
        try:
            integrated = integrate_fuzzy_decision(
                coin=coin, crisp_decision=decision, regime=regime,
                confluence=confluence, mtf=mtf, structure=None,
                risk_plan=None, atr_pct=2.0, fusion=fusion,
                contradiction=contradiction, confidence=confidence,
            )
            decision.direction = integrated.final_direction
            decision.confidence = int(integrated.final_confidence * 100)
            print("[Fuzzy Engine] Active.")
        except Exception as e:
            print("[Fuzzy Engine] Skipped: " + str(e))

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
    parser = argparse.ArgumentParser(description="RSP")
    parser.add_argument("--coin", default="bitcoin")
    parser.add_argument("--timeframe", default="1h")
    parser.add_argument("--backtest", action="store_true")
    parser.add_argument("--walkforward", action="store_true")
    parser.add_argument("--stress", action="store_true")
    parser.add_argument("--montecarlo", action="store_true")
    parser.add_argument("--versions", action="store_true")
    parser.add_argument("--challenge", nargs=2)
    parser.add_argument("--compare-arsan", action="store_true")
    parser.add_argument("--compare-arsan-live", action="store_true")
    args = parser.parse_args()

    needs_universe = args.backtest or args.walkforward or args.stress or \
        args.montecarlo or args.versions or args.challenge

    universe = None
    if needs_universe:
        try:
            from RSP.ingestion.data_universe import build_data_universe
            universe = build_data_universe(args.coin)
        except Exception as e:
            print("ERROR: Could not build data universe — " + str(e))
            return
        base_tf = "15M"
        base_bars = universe.bars.get(base_tf)
        if base_bars is None or base_bars.empty:
            print("ERROR: No data available for base timeframe " + base_tf +
                  " (coin=" + args.coin + "). Cannot run this command.")
            return

    if args.backtest:
        summary = run_backtest(universe.bars, base_tf="15M")
        print(f"total_trades={summary.total_trades}  win_rate={summary.win_rate}  "
              f"net_return_pct={summary.net_return_pct}  profit_factor={summary.profit_factor}  "
              f"max_drawdown_pct={summary.max_drawdown_pct}")

        if args.compare_arsan or args.compare_arsan_live:
            try:
                from RSP.comparison.arsan_vs_rsp import compare
                project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                comparison = compare(summary, project_root, regenerate=args.compare_arsan_live)
                print("\n--- Arsan vs RSP Comparison ---")
                print("RSP:", comparison.rsp)
                print("Arsan:", comparison.arsan)
                for note in comparison.methodology_notes + comparison.notes:
                    print(" *", note)
            except Exception as e:
                print("Comparison error: " + str(e))

    elif args.walkforward:
        try:
            from RSP.walk_forward.walk_forward import run_walk_forward
            report = run_walk_forward(universe.bars, base_tf="15M")
            print(f"windows={len(report.windows)}  "
                  f"aggregate_test_win_rate={report.aggregate_test_win_rate}  "
                  f"aggregate_test_net_return={report.aggregate_test_net_return}")
            for note in report.notes:
                print(" *", note)
        except Exception as e:
            print("Walk-forward error: " + str(e))

    elif args.stress:
        try:
            from RSP.robustness.stress_test import performance_by_market_type, run_synthetic_scenarios
            summary = run_backtest(universe.bars, base_tf="15M")
            regime_report = performance_by_market_type(summary)
            print("--- Performance by market regime (real data) ---")
            for row in regime_report.by_market_type:
                print(f"  {row.market_type}: trades={row.trades} win_rate={row.win_rate} "
                      f"net_return_pct={row.net_return_pct}")
            for note in regime_report.notes:
                print(" *", note)

            print("\n--- Synthetic engineering scenarios (not a real profitability measure) ---")
            synth = run_synthetic_scenarios()
            for kind, s in synth.items():
                print(f"  {kind}: trades={s.total_trades} win_rate={s.win_rate} "
                      f"net_return_pct={s.net_return_pct}")
        except Exception as e:
            print("Stress test error: " + str(e))

    elif args.montecarlo:
        try:
            from RSP.robustness.monte_carlo import randomize_trade_sequence, run_perturbation_suite
            summary = run_backtest(universe.bars, base_tf="15M")
            seq_report = randomize_trade_sequence(summary)
            print("--- Trade sequence randomization ---")
            print(f"  original_max_drawdown={seq_report.original_max_drawdown} "
                  f"worst_case={seq_report.worst_case_drawdown} p95={seq_report.p95_drawdown} "
                  f"order_dependent={seq_report.order_dependent}")
            for note in seq_report.notes:
                print(" *", note)

            pert_report = run_perturbation_suite(universe.bars, base_tf="15M")
            print("\n--- Fee/slippage & risk parameter perturbation ---")
            print(f"  baseline: trades={pert_report.baseline.total_trades} "
                  f"net_return_pct={pert_report.baseline.net_return_pct}")
            for r in pert_report.results:
                print(f"  {r.label}: trades={r.summary.total_trades} "
                      f"net_return_pct={r.summary.net_return_pct}")
            print(f"  fragile={pert_report.fragile}")
            for note in pert_report.notes:
                print(" *", note)
        except Exception as e:
            print("Monte Carlo error: " + str(e))

    elif args.versions:
        try:
            from RSP.strategy_lab.versioning import compare_versions, ENGINE_VERSIONS
            results = compare_versions(list(ENGINE_VERSIONS.keys()), universe.bars, base_tf="15M")
            print("--- Version comparison ---")
            for vid, res in results.items():
                print(f"  {vid} ({res.description}): trades={res.summary.total_trades} "
                      f"win_rate={res.summary.win_rate} net_return_pct={res.summary.net_return_pct}")
        except Exception as e:
            print("Version compare error: " + str(e))

    elif args.challenge:
        try:
            from RSP.strategy_lab.challenger import run_challenge
            result = run_challenge(args.challenge[0], args.challenge[1], universe.bars, base_tf="15M")
            print("--- Challenger (Out-of-Sample) ---")
            print(f"  champion={result.champion_id} oos_win_rate={result.champion_oos_win_rate} "
                  f"oos_net_return={result.champion_oos_net_return} windows={result.champion_windows}")
            print(f"  challenger={result.challenger_id} oos_win_rate={result.challenger_oos_win_rate} "
                  f"oos_net_return={result.challenger_oos_net_return} windows={result.challenger_windows}")
            print(f"  winner={result.winner}")
            print(f"  reason={result.reason}")
        except Exception as e:
            print("Challenger error: " + str(e))

    else:
        run_analysis(args.coin, args.timeframe)


if __name__ == "__main__":
    main()
