"""
RSP — main.py

هماهنگ‌کننده‌ی اصلی: کل پایپ‌لاین را برای یک کوین اجرا می‌کند و یک
گزارش کامل و Explainable تولید می‌کند (Phase 32: Final Evaluation).

اجرا:
    python -m RSP.main --coin bitcoin
    python -m RSP.main --coin bitcoin --backtest

این فایل هیچ Live Trading انجام نمی‌دهد، هیچ سفارش واقعی ارسال نمی‌کند و
هیچ API Key معاملاتی نمی‌خواهد (طبق «محدودیت‌های اجرایی» در اسپک پروژه).
"""

import argparse
import json
import os
import sys

# اجازه می‌دهد چه با `python -m RSP.main` و چه مستقیم اجرا شود
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from RSP.ingestion.data_universe import build_data_universe
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


def analyze_coin(coin_id: str, lookback_days: float = settings.DEFAULT_LOOKBACK_DAYS):
    universe = build_data_universe(coin_id, lookback_days=lookback_days)
    quality_reports = check_all_timeframes(universe.bars)

    base_tf = "15M"
    base_df = universe.bars.get(base_tf, None)
    base_quality = quality_reports.get(base_tf)

    regime = determine_regime(base_df) if base_df is not None else None
    confluence = analyze_confluence(base_df) if base_df is not None else None
    mtf = analyze_mtf(universe.bars)
    fusion = fuse_signals(regime, confluence, mtf)
    contradiction = detect_contradictions(fusion, mtf)
    confidence = compute_confidence(fusion, mtf, contradiction,
                                     base_quality.quality_score if base_quality else 0.0,
                                     regime.perception.atr_pct if regime else 0.0)
    decision = decide(regime, fusion, mtf, contradiction, confidence,
                       base_quality.quality_ok if base_quality else False)

    risk_plan = None
    trade_quality = None
    selection = select_strategy(regime, fusion) if regime else None
    if decision.action in ("BUY", "SELL"):
        risk_plan = plan_risk(decision.action, base_df, regime)
        trade_quality = evaluate_trade_quality(
            confidence.confidence, base_quality.quality_score, risk_plan.risk_reward,
            selection.selected is not None if selection else False)
        if not (risk_plan.valid and trade_quality.passed):
            decision.action = "NO_TRADE"
            decision.why.append(f"رد شد در Trade Quality/Risk Gate: risk_ok={risk_plan.valid}, "
                                 f"quality_ok={trade_quality.passed}")

    report = build_report(decision, confidence, regime, selection, risk_plan, trade_quality,
                           base_quality, universe.source_used)

    return {
        "coin_id": coin_id,
        "explainability_text": report.to_text(),
        "data_universe": {
            "availability": universe.availability,
            "source_used": universe.source_used,
            "is_reconstructed": universe.is_reconstructed,
            "attempted_sources": universe.attempted_sources,
        },
        "mtf": mtf.__dict__ if mtf else None,
        "fusion_net_score": fusion.net_score if fusion else None,
    }


def main():
    parser = argparse.ArgumentParser(description="RSP - Research & Strategy Playground")
    parser.add_argument("--coin", default="bitcoin")
    parser.add_argument("--days", type=float, default=settings.DEFAULT_LOOKBACK_DAYS,
                         help=f"تعداد روز تاریخچه‌ی درخواستی (پیش‌فرض {settings.DEFAULT_LOOKBACK_DAYS}). "
                              f"مثال: --days 120")
    parser.add_argument("--backtest", action="store_true", help="اجرای بک‌تست به‌جای تحلیل لحظه‌ای")
    parser.add_argument("--walkforward", action="store_true", help="اجرای Walk Forward + Anti-Overfitting Check")
    parser.add_argument("--stress", action="store_true", help="اجرای Stress Test (رژیم واقعی + سناریوهای مصنوعی)")
    parser.add_argument("--montecarlo", action="store_true", help="اجرای Trade Sequence Randomization + Perturbation")
    parser.add_argument("--versions", action="store_true", help="مقایسه‌ی نسخه‌های V1/V2/V3")
    parser.add_argument("--challenge", nargs=2, metavar=("CHAMPION", "CHALLENGER"),
                         help="مثال: --challenge V1 V2")
    parser.add_argument("--save", metavar="PATH",
                         help="ذخیره‌ی خروجی به‌صورت JSON روی دیسک (برای بارگذاری در RSP Dashboard). "
                              "مثال: --save rsp_report.json")
    parser.add_argument("--compare-arsan", action="store_true",
                         help="بعد از --backtest، با data/backtest_summary.json آرسان مقایسه کن (Phase 29)")
    parser.add_argument("--compare-arsan-live", action="store_true",
                         help="مثل --compare-arsan ولی به‌جای فایل موجود، خودِ backtest_lab.py آرسان را "
                              "زنده اجرا می‌کند (نیاز به شبکه دارد و چند دقیقه طول می‌کشد)")
    parser.add_argument("--sl-multiplier", type=float, default=None,
                         help=f"override موقت settings.STOP_LOSS_ATR_MULTIPLIER (پیش‌فرض "
                              f"{settings.STOP_LOSS_ATR_MULTIPLIER}) برای تست چند مقدار بدون ادیت فایل. "
                              f"مثال: --sl-multiplier 3.0")
    parser.add_argument("--exhaustion-threshold", type=float, default=None,
                         help=f"override موقت settings.EXHAUSTION_NET_SCORE_THRESHOLD (پیش‌فرض "
                              f"{settings.EXHAUSTION_NET_SCORE_THRESHOLD})")
    parser.add_argument("--no-exhaustion-filter", action="store_true",
                         help="غیرفعال‌کردن موقت فیلتر Exhaustion برای مقایسه‌ی با/بدون")
    args = parser.parse_args()

    if args.sl_multiplier is not None:
        settings.STOP_LOSS_ATR_MULTIPLIER = args.sl_multiplier
        print(f"[Override] STOP_LOSS_ATR_MULTIPLIER = {args.sl_multiplier}")
    if args.exhaustion_threshold is not None:
        settings.EXHAUSTION_NET_SCORE_THRESHOLD = args.exhaustion_threshold
        print(f"[Override] EXHAUSTION_NET_SCORE_THRESHOLD = {args.exhaustion_threshold}")
    if args.no_exhaustion_filter:
        settings.EXHAUSTION_FILTER_ENABLED = False
        print("[Override] EXHAUSTION_FILTER_ENABLED = False")

    def _maybe_save(data: dict):
        if args.save:
            with open(args.save, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"\n[ذخیره شد] {args.save} — این فایل را در RSP Dashboard بارگذاری کن.")

    if args.walkforward:
        from RSP.walk_forward.walk_forward import run_walk_forward
        from RSP.anti_overfitting.overfitting_lab import run_overfitting_check
        universe = build_data_universe(args.coin, lookback_days=args.days)
        wf = run_walk_forward(universe.bars, base_tf="15M")
        of = run_overfitting_check(wf)
        print(json.dumps({
            "windows": len(wf.windows), "aggregate_test_win_rate": wf.aggregate_test_win_rate,
            "aggregate_test_net_return": wf.aggregate_test_net_return,
            "overfitting_status": of.overall_status, "overfitting_notes": of.notes,
        }, ensure_ascii=False, indent=2))
        return

    if args.stress:
        from RSP.robustness.stress_test import performance_by_market_type, run_synthetic_scenarios
        universe = build_data_universe(args.coin, lookback_days=args.days)
        summary = run_backtest(universe.bars, base_tf="15M")
        st = performance_by_market_type(summary)
        print("--- عملکرد واقعی به‌تفکیک رژیم ---")
        print(json.dumps([m.__dict__ for m in st.by_market_type], ensure_ascii=False, indent=2))
        print(st.notes)
        print("\n--- سناریوهای مصنوعی مهندسی (نه ارزیابی سود واقعی) ---")
        synth = run_synthetic_scenarios()
        for k, s in synth.items():
            print(f"  {k}: trades={s.total_trades} win_rate={s.win_rate} net_return={s.net_return_pct}")
        return

    if args.montecarlo:
        from RSP.robustness.monte_carlo import randomize_trade_sequence, run_perturbation_suite
        universe = build_data_universe(args.coin, lookback_days=args.days)
        summary = run_backtest(universe.bars, base_tf="15M")
        seqr = randomize_trade_sequence(summary)
        print("Sequence Randomization:", seqr.notes)
        pert = run_perturbation_suite(universe.bars, base_tf="15M")
        print("Perturbation fragile:", pert.fragile, pert.notes)
        for r in pert.results:
            print(f"  {r.label}: trades={r.summary.total_trades} net_return={r.summary.net_return_pct}")
        return

    if args.versions:
        from RSP.strategy_lab.versioning import compare_versions, ENGINE_VERSIONS
        universe = build_data_universe(args.coin, lookback_days=args.days)
        vcmp = compare_versions(list(ENGINE_VERSIONS.keys()), universe.bars, base_tf="15M")
        for vid, res in vcmp.items():
            print(f"{vid} ({res.description}): trades={res.summary.total_trades} "
                  f"win_rate={res.summary.win_rate} net_return={res.summary.net_return_pct}")
        return

    if args.challenge:
        from RSP.strategy_lab.challenger import run_challenge
        universe = build_data_universe(args.coin, lookback_days=args.days)
        result = run_challenge(args.challenge[0], args.challenge[1], universe.bars)
        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))
        return

    if args.backtest:
        universe = build_data_universe(args.coin, lookback_days=args.days)
        print(f"[پوشش داده] بازه‌ی درخواستی: {args.days} روز")
        for tf in ["15M", "1H", "4H", "1D"]:
            req = universe.requested_candles.get(tf, "?")
            got = universe.actual_candles.get(tf, 0)
            src = universe.source_used.get(tf, "N/A")
            recon = " (بازسازی‌شده)" if universe.is_reconstructed.get(tf) else ""
            print(f"  {tf}: درخواست={req} کندل, دریافت={got} کندل, منبع={src}{recon}")
        summary = run_backtest(universe.bars, base_tf="15M")
        backtest_result = {
            "coin_id": args.coin,
            "lookback_days": args.days,
            "data_coverage": {tf: {"requested": universe.requested_candles.get(tf),
                                    "actual": universe.actual_candles.get(tf),
                                    "source": universe.source_used.get(tf),
                                    "is_reconstructed": universe.is_reconstructed.get(tf)}
                               for tf in ["15M", "1H", "4H", "1D"]},
            "total_trades": summary.total_trades,
            "win_rate": summary.win_rate,
            "net_return_pct": summary.net_return_pct,
            "profit_factor": summary.profit_factor,
            "max_drawdown_pct": summary.max_drawdown_pct,
            "average_trade_pct": summary.average_trade_pct,
        }

        # Phase 24/25 — Self Evaluation + Failure Analysis (خودکار، چون evidence_snapshot
        # همین حالا در summary.trades موجود است - نیازی به اسکریپت جدا نیست)
        if summary.trades:
            from dataclasses import asdict
            from RSP.self_evaluation.self_evaluation import evaluate_all, summarize
            from RSP.self_evaluation.failure_analysis import analyze_failures
            evals = evaluate_all(summary.trades)
            failure_report = analyze_failures(summary.trades, evals)
            backtest_result["self_evaluation_summary"] = summarize(evals)
            backtest_result["failure_analysis"] = {
                "total_losses": failure_report.total_losses,
                "category_counts": failure_report.category_counts,
                "category_avg_pnl": failure_report.category_avg_pnl,
                "dominant_failure_mode": failure_report.dominant_failure_mode,
                "worst_regime": failure_report.worst_regime,
                "notes": failure_report.notes,
            }
            print("\n[Self Evaluation]", backtest_result["self_evaluation_summary"])
            print("[Failure Analysis] dominant:", failure_report.dominant_failure_mode,
                  "| worst regime:", failure_report.worst_regime)

        # Phase 29 — مقایسه با آرسان اصلی
        if args.compare_arsan or args.compare_arsan_live:
            from dataclasses import asdict
            from RSP.comparison.arsan_vs_rsp import compare
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            comparison_report = compare(summary, project_root=project_root,
                                         regenerate=args.compare_arsan_live)
            backtest_result["comparison"] = asdict(comparison_report)
            print("\n[Arsan Comparison] source:", comparison_report.arsan.source,
                  "| available:", comparison_report.arsan.available)
            if comparison_report.arsan.available:
                print(f"  ARSAN accuracy ({comparison_report.arsan.window_days}d): "
                      f"{comparison_report.arsan.overall_accuracy_percent}% "
                      f"(n={comparison_report.arsan.overall_total_evaluated})")
                print(f"  RSP win_rate: {summary.win_rate}% (n={summary.total_trades})")
            else:
                print("  ", comparison_report.arsan.error, "-", " ".join(comparison_report.notes))

        print("\n" + json.dumps(backtest_result, ensure_ascii=False, indent=2))
        _maybe_save(backtest_result)
        log_experiment(strategy="mixed_selector", parameters={"base_tf": "15M", "lookback_days": args.days},
                        dataset=args.coin, timeframe="15M",
                        results={k: v for k, v in backtest_result.items() if k != "comparison"},
                        changes="اجرای main.py --backtest")
        return

    result = analyze_coin(args.coin, lookback_days=args.days)
    print(result["explainability_text"])
    print("\n--- DATA UNIVERSE ---")
    print(json.dumps(result["data_universe"], ensure_ascii=False, indent=2))
    _maybe_save(result)


if __name__ == "__main__":
    main()
