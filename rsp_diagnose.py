"""
RSP — اسکریپت تشخیصی موقت (برای اجرای محلی خودت، نه بخشی از پروژه‌ی اصلی)

این اسکریپت را کنار پوشه‌ی RSP (یعنی توی همون ریشه‌ی پروژه که RSP/main.py هست)
بگذار و اجرا کن:

    python rsp_diagnose.py --coin bitcoin --days 120

خروجی:
  1) N نمونه از معاملات UNEXPLAINED با evidence_snapshot کامل
  2) شکست هر رژیم: تعداد معامله / win_rate / net_return / max_drawdown هرکدام
     (تا معلوم شود RANGE واقعاً به‌ازای هر معامله بدتر است یا صرفاً چون بیشترین
     تعداد معامله را دارد "بدترین رژیم" شناخته شده)
"""
import argparse
import json
from collections import defaultdict

from RSP.ingestion.data_universe import build_data_universe
from RSP.backtest_engine.backtest_engine import run_backtest
from RSP.self_evaluation.self_evaluation import evaluate_all
from RSP.self_evaluation.failure_analysis import analyze_failures, _classify_trade
from RSP.walk_forward.walk_forward import run_walk_forward


def dump_walk_forward_windows(universe, base_tf="15M"):
    """هر پنجره‌ی walk-forward رو با جزئیات Validate vs Test چاپ می‌کنه تا
    ببینیم پنجره‌های SEVERE کجای بازه‌ی زمانی خوشه شدن (مثلاً یه دوره‌ی خاص
    پرنوسان، یا پخش و یکنواخت در کل بازه)."""
    wf = run_walk_forward(universe.bars, base_tf=base_tf)
    print(f"windows={len(wf.windows)}  aggregate_test_win_rate={wf.aggregate_test_win_rate}  "
          f"aggregate_test_net_return={wf.aggregate_test_net_return}")
    print()
    for w in wf.windows:
        v, t = w.validate_summary, w.test_summary
        drop_wr = (t.win_rate - v.win_rate)
        drop_avg = (t.average_trade_pct - v.average_trade_pct)
        flag = ""
        if t.total_trades < 5 or v.total_trades < 5:
            flag = "INSUFFICIENT_TRADES"
        elif drop_wr < -15 and drop_avg < -0.1:
            flag = "SEVERE"
        elif drop_wr < -8 or drop_avg < -0.05:
            flag = "WARNING"
        else:
            flag = "OK"
        regime_counts = defaultdict(int)
        for tr in t.trades:
            regime_counts[tr.regime] += 1
        dominant_regime = max(regime_counts.items(), key=lambda kv: kv[1])[0] if regime_counts else "N/A"
        regime_summary = ",".join(f"{k}:{v_}" for k, v_ in sorted(regime_counts.items(), key=lambda kv: -kv[1]))
        print(f"win#{w.window_index:3d}  test=[{w.test_start} .. {w.test_end}]  "
              f"validate(wr={v.win_rate:5.1f}%,avg={v.average_trade_pct:+.3f}%,n={v.total_trades:3d})  "
              f"test(wr={t.win_rate:5.1f}%,avg={t.average_trade_pct:+.3f}%,n={t.total_trades:3d})  "
              f"[{flag}]  dominant_regime={dominant_regime}  ({regime_summary})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coin", default="bitcoin")
    ap.add_argument("--days", type=float, default=120)
    ap.add_argument("--samples", type=int, default=8, help="چند نمونه‌ی UNEXPLAINED نشان بدهد")
    ap.add_argument("--walkforward-detail", action="store_true",
                     help="به‌جای بک‌تست معمولی، جزئیات هر پنجره‌ی walk-forward رو چاپ کن")
    args = ap.parse_args()

    universe = build_data_universe(args.coin, lookback_days=args.days)

    if args.walkforward_detail:
        dump_walk_forward_windows(universe)
        return
    summary = run_backtest(universe.bars, base_tf="15M")
    evals = evaluate_all(summary.trades)
    failure_report = analyze_failures(summary.trades, evals)

    print("=" * 70)
    print(f"total_trades={summary.total_trades}  win_rate={summary.win_rate}  "
          f"net_return_pct={summary.net_return_pct}")
    print("=" * 70)

    # --- بخش ۱: نمونه‌های UNEXPLAINED ---
    print(f"\n### {args.samples} نمونه از معاملات UNEXPLAINED (با evidence_snapshot کامل) ###\n")
    shown = 0
    for trade, ev in zip(summary.trades, evals):
        if trade.outcome != "LOSS":
            continue
        categories = _classify_trade(trade, ev)
        if categories != ["UNEXPLAINED"]:
            continue
        shown += 1
        print(f"--- نمونه {shown} ---")
        print(json.dumps({
            "timestamp": trade.timestamp,
            "action": trade.action,
            "regime": trade.regime,
            "pnl_pct": trade.pnl_pct,
            "bars_held": trade.bars_held,
            "exit_reason": trade.exit_reason,
            "risk_reward": trade.risk_reward,
            "trade_quality": trade.trade_quality,
            "confidence": trade.confidence,
            "evidence_snapshot": trade.evidence_snapshot,
            "confirming_signals": ev.confirming_signals,
            "misleading_signals": ev.misleading_signals,
            "entry_quality_flag": ev.entry_quality_flag,
        }, ensure_ascii=False, indent=2, default=str))
        print()
        if shown >= args.samples:
            break

    if shown == 0:
        print("هیچ معامله‌ی UNEXPLAINED پیدا نشد (عجیب است، چک کن که failure_analysis واقعاً چیزی برگردانده).")

    # --- بخش ۲: شکست هر رژیم ---
    print("\n### شکست عملکرد به تفکیک رژیم ###\n")
    by_regime = defaultdict(lambda: {"trades": 0, "wins": 0, "losses": 0, "pnl_sum": 0.0})
    for trade in summary.trades:
        r = by_regime[trade.regime]
        r["trades"] += 1
        r["pnl_sum"] += trade.pnl_pct
        if trade.outcome == "WIN":
            r["wins"] += 1
        elif trade.outcome == "LOSS":
            r["losses"] += 1

    for regime, stats in sorted(by_regime.items(), key=lambda kv: -kv[1]["trades"]):
        n = stats["trades"]
        wr = round(100 * stats["wins"] / n, 2) if n else 0
        avg_pnl = round(stats["pnl_sum"] / n, 4) if n else 0
        print(f"  {regime:15s}  trades={n:4d}  win_rate={wr:6.2f}%  "
              f"avg_pnl_per_trade={avg_pnl:7.3f}%  total_pnl={round(stats['pnl_sum'],2):8.2f}%")

    # --- بخش ۳: رابطه‌ی Confidence با Win Rate واقعی ---
    print("\n### رابطه‌ی Confidence با نتیجه‌ی واقعی معامله ###\n")
    buckets = [(0, 50), (50, 65), (65, 80), (80, 101)]
    for lo, hi in buckets:
        sub = [t for t in summary.trades if lo <= t.confidence < hi]
        if not sub:
            print(f"  confidence [{lo:3d}-{hi:3d}): بدون نمونه")
            continue
        wins = sum(1 for t in sub if t.outcome == "WIN")
        avg_pnl = sum(t.pnl_pct for t in sub) / len(sub)
        print(f"  confidence [{lo:3d}-{hi:3d})  trades={len(sub):4d}  "
              f"win_rate={round(100*wins/len(sub),2):6.2f}%  avg_pnl={round(avg_pnl,4):7.4f}%")

    # --- بخش ۴: درصد SL_TP_SAME_CANDLE_CONSERVATIVE_SL_FIRST ---
    print("\n### توزیع exit_reason ###\n")
    reason_counts = defaultdict(int)
    for t in summary.trades:
        reason_counts[t.exit_reason] += 1
    total = len(summary.trades) or 1
    for reason, cnt in sorted(reason_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {reason:45s}  {cnt:4d}  ({round(100*cnt/total,2)}%)")


if __name__ == "__main__":
    main()
