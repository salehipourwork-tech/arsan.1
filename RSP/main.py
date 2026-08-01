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


def analyze_coin(coin_id: str):
    universe = build_data_universe(coin_id)
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
    parser.add_argument("--backtest", action="store_true", help="اجرای بک‌تست به‌جای تحلیل لحظه‌ای")
    args = parser.parse_args()

    if args.backtest:
        universe = build_data_universe(args.coin)
        summary = run_backtest(universe.bars, base_tf="15M")
        print(json.dumps({
            "coin_id": args.coin,
            "total_trades": summary.total_trades,
            "win_rate": summary.win_rate,
            "net_return_pct": summary.net_return_pct,
            "profit_factor": summary.profit_factor,
            "max_drawdown_pct": summary.max_drawdown_pct,
            "average_trade_pct": summary.average_trade_pct,
        }, ensure_ascii=False, indent=2))
        log_experiment(strategy="mixed_selector", parameters={"base_tf": "15M"},
                        dataset=args.coin, timeframe="15M",
                        results=summary.__dict__, changes="اجرای اولیه از main.py --backtest")
        return

    result = analyze_coin(args.coin)
    print(result["explainability_text"])
    print("\n--- DATA UNIVERSE ---")
    print(json.dumps(result["data_universe"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
