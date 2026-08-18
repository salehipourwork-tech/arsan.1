"""
RSP — Pipeline Diagnostic Harness (NEW FILE)

هدف: اجرای گام‌به‌گام کل مسیر MTF -> Fusion -> Decision -> Risk -> TradeRecord
-> Simulator روی داده‌ی واقعی (یا هر داده‌ای که بدهید)، با شمارش دقیق این‌که
هر گارد/gate چند بار و با چه دلیلی معامله را رد کرده — نه فقط "صفر معامله
شد"، بلکه دقیقاً کدام گیت مقصر است.

استفاده (روی سیستم خودتان، جایی که به CoinGecko دسترسی دارید):

    python -m RSP.diagnose_pipeline --coin bitcoin --days 90
    python -m RSP.diagnose_pipeline --coin ethereum --days 90 --fuzzy both

این فایل هیچ منطق تصمیم‌گیری/ریسک را عوض نمی‌کند — فقط همان
run_backtest/make_decision واقعی را صدا می‌زند و رد هر بار را با دلیلش لاگ
می‌کند.
"""

import argparse
from collections import Counter
from typing import Dict

from RSP.config import settings
from RSP.ingestion.data_universe import build_data_universe
from RSP.regime_engine.regime_engine import detect_regime
from RSP.decision_engine.decision_brain import make_decision
from RSP.risk_engine.risk_engine import plan_risk
from RSP.risk_engine.trade_quality import assess_trade_quality
from RSP.execution_simulator.trade_simulator import simulate_trade
from RSP.backtest_engine.backtest_engine import _known_slice, _future_bars, TradeRecord
from RSP.fuzzy_core.decision_controller import FuzzyDecisionController


GATE_ORDER = [
    "total_bars_scanned",
    "rejected_STRONG_REGIME_ONLY_MODE",
    "rejected_cooldown",
    "rejected_daily_max_trades",
    "rejected_decision_not_buy_sell",       # includes NO_TRADE / WAIT / HOLD from decide()
    "rejected_volume_filter",
    "rejected_fuzzy_can_trade",
    "rejected_fuzzy_opportunity_threshold",
    "rejected_risk_plan_invalid",
    "rejected_min_risk_reward",
    "rejected_simulation_open",
    "trades_recorded",
]


def diagnose(bars_by_tf: Dict, base_tf: str = "15M", min_history: int = 200,
            fuzzy_enabled: bool = False, coin_label: str = "", step: int = 1) -> dict:
    base_df = bars_by_tf.get(base_tf)
    gates = Counter()
    decision_action_counts = Counter()
    why_samples = Counter()

    if base_df is None or base_df.empty or len(base_df) < min_history:
        return {"error": f"insufficient_base_data (have={0 if base_df is None else len(base_df)}, need={min_history})"}

    from RSP.preprocessing.quality_engine import check_quality
    quality = check_quality(base_df, base_tf)
    if not quality.quality_ok:
        return {"error": f"data_quality_gate_failed: {quality.issues} score={quality.quality_score}"}

    settings.FUZZY_BACKTEST_ENABLED = fuzzy_enabled
    fuzzy_controller = FuzzyDecisionController()
    trades = []

    cooldown_until: Dict[str, int] = {}
    daily_trade_count: Dict[str, int] = {}

    for i in range(min_history, len(base_df), step):
        gates["total_bars_scanned"] += 1
        ts = base_df.index[i]
        known = _known_slice(bars_by_tf, ts)
        known_base = known.get(base_tf)
        if known_base is None or known_base.empty:
            continue

        regime = detect_regime(known_base)
        regime_label = regime.regime if regime else "UNKNOWN"

        if settings.STRONG_REGIME_ONLY_MODE and regime_label not in settings.ALLOWED_REGIMES_FOR_TRADING:
            gates["rejected_STRONG_REGIME_ONLY_MODE"] += 1
            continue

        if i < cooldown_until.get("BUY", 0) or i < cooldown_until.get("SELL", 0):
            gates["rejected_cooldown"] += 1
            continue

        day_key = ts.strftime("%Y-%m-%d")
        if daily_trade_count.get(day_key, 0) >= settings.DAILY_MAX_TRADES:
            gates["rejected_daily_max_trades"] += 1
            continue

        decision = make_decision(known, regime)
        decision_action_counts[decision.action if decision else "NONE"] += 1
        if not decision or decision.action not in ("BUY", "SELL"):
            gates["rejected_decision_not_buy_sell"] += 1
            if decision and decision.why:
                why_samples[decision.why[0][:80]] += 1
            continue

        if settings.VOLUME_FILTER_ENABLED:
            vol_data = known.get(base_tf)
            if vol_data is not None and not vol_data.empty:
                latest_volume = vol_data["volume"].iloc[-1]
                latest_close = vol_data["close"].iloc[-1]
                if latest_volume * latest_close < settings.MIN_VOLUME_USD:
                    gates["rejected_volume_filter"] += 1
                    continue

        if settings.FUZZY_BACKTEST_ENABLED:
            fuzzy_result = fuzzy_controller.evaluate(
                regime=regime, signals=decision.fusion, mtf=decision.mtf,
                trade_quality=None, history=None,
            )
            if not fuzzy_result or not fuzzy_result.can_trade:
                gates["rejected_fuzzy_can_trade"] += 1
                continue
            method = getattr(settings, "OPPORTUNITY_SCORING_METHOD", "rules")
            threshold = getattr(settings, "FUZZY_OPPORTUNITY_THRESHOLD_BY_METHOD", {}).get(
                method, getattr(settings, "MIN_OPPORTUNITY_SCORE_FOR_TRADE", settings.FUZZY_OPPORTUNITY_THRESHOLD))
            if fuzzy_result.opportunity_score < threshold:
                gates["rejected_fuzzy_opportunity_threshold"] += 1
                continue

        entry_price = base_df["close"].iloc[i]
        risk_plan = plan_risk(decision.action, known_base, regime)
        if not risk_plan.valid or risk_plan.risk_reward is None:
            gates["rejected_risk_plan_invalid"] += 1
            continue
        if risk_plan.risk_reward < settings.MIN_ACCEPTABLE_RISK_REWARD:
            gates["rejected_min_risk_reward"] += 1
            continue

        try:
            trade_quality = assess_trade_quality(risk_plan, quality, regime, decision.fusion)
            decision.trade_quality = trade_quality.overall_score
        except Exception:
            pass

        future_bars = _future_bars(base_df, i)
        sim = simulate_trade(decision.action, entry_price, risk_plan.stop_loss,
                             risk_plan.take_profit, future_bars)
        if sim.outcome == "OPEN":
            gates["rejected_simulation_open"] += 1
            continue

        gates["trades_recorded"] += 1
        trades.append({
            "ts": str(ts), "action": decision.action, "entry": entry_price,
            "sl": risk_plan.stop_loss, "tp": risk_plan.take_profit,
            "rr": risk_plan.risk_reward, "outcome": sim.outcome,
            "pnl_pct": sim.pnl_pct, "regime": regime_label,
        })

        if sim.outcome == "LOSS" and sim.exit_reason == "STOP_LOSS_HIT":
            cooldown_until[decision.action] = i + settings.COOLDOWN_BARS_AFTER_STOP_LOSS
        elif sim.outcome == "WIN" and sim.exit_reason == "TAKE_PROFIT_HIT":
            cooldown_until[decision.action] = i + settings.COOLDOWN_BARS_AFTER_TAKE_PROFIT
        daily_trade_count[day_key] = daily_trade_count.get(day_key, 0) + 1

    wins = sum(1 for t in trades if t["outcome"] == "WIN")
    losses = sum(1 for t in trades if t["outcome"] == "LOSS")
    total = len(trades)
    win_rate = (wins / total * 100) if total else 0.0
    avg_win = sum(t["pnl_pct"] for t in trades if t["outcome"] == "WIN") / wins if wins else 0.0
    avg_loss = sum(t["pnl_pct"] for t in trades if t["outcome"] == "LOSS") / losses if losses else 0.0
    pf = abs(avg_win * wins / (avg_loss * losses)) if losses and avg_loss != 0 else (float("inf") if wins else 0.0)
    equity = [1.0]
    for t in trades:
        equity.append(equity[-1] * (1 + t["pnl_pct"] / 100.0))
    net_return = (equity[-1] - 1.0) * 100 if len(equity) > 1 else 0.0
    peak, max_dd = 1.0, 0.0
    for e in equity:
        peak = max(peak, e)
        max_dd = max(max_dd, (peak - e) / peak)

    return {
        "coin": coin_label, "fuzzy_enabled": fuzzy_enabled,
        "gates": {g: gates.get(g, 0) for g in GATE_ORDER},
        "decision_action_counts": dict(decision_action_counts),
        "top_wait_reasons": dict(why_samples.most_common(5)),
        "total_trades": total, "wins": wins, "losses": losses,
        "win_rate": round(win_rate, 2), "net_return_pct": round(net_return, 2),
        "profit_factor": round(pf, 3) if pf != float("inf") else "inf",
        "max_drawdown_pct": round(max_dd * 100, 2),
        "sample_trades": trades[:5],
    }


def _print_report(report: dict):
    if "error" in report:
        print(f"  ERROR: {report['error']}")
        return
    print(f"  coin={report['coin']} fuzzy={report['fuzzy_enabled']}")
    print("  --- gate funnel ---")
    for g in GATE_ORDER:
        print(f"    {g}: {report['gates'][g]}")
    print("  --- decision action counts ---", report["decision_action_counts"])
    if report["top_wait_reasons"]:
        print("  --- top WAIT/NO_TRADE reasons ---")
        for reason, count in report["top_wait_reasons"].items():
            print(f"    [{count}x] {reason}")
    print(f"  trades={report['total_trades']} WR={report['win_rate']}% "
          f"Net={report['net_return_pct']:+.2f}% PF={report['profit_factor']} "
          f"MaxDD={report['max_drawdown_pct']}%")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coin", default="bitcoin")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--min-history", type=int, default=200)
    ap.add_argument("--fuzzy", choices=["on", "off", "both"], default="both")
    ap.add_argument("--step", type=int, default=1,
                    help="sample every Nth bar for faster diagnostics (does not change production run_backtest)")
    args = ap.parse_args()

    print(f">>> Fetching {args.days}d of data for {args.coin} ...")
    universe = build_data_universe(args.coin, lookback_days=args.days)

    modes = [True, False] if args.fuzzy == "both" else [args.fuzzy == "on"]
    for fz in modes:
        print(f"\n=== {args.coin} | FUZZY_BACKTEST_ENABLED={fz} ===")
        report = diagnose(universe.bars, base_tf="15M", min_history=args.min_history,
                          fuzzy_enabled=fz, coin_label=args.coin, step=args.step)
        _print_report(report)


if __name__ == "__main__":
    main()
