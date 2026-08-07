"""
fuzzy_trade_diff.py — Task 1 (Root Cause Analysis) روی داده‌ی واقعی

کنار main.py (یعنی توی arsan.1، بیرون از پوشه‌ی RSP) بگذارید و اجرا کنید:

    python fuzzy_trade_diff.py --coin ethereum --days 240

این اسکریپت دقیقاً همان بک‌تست --backtest و --backtest --fuzzy-engine را
روی یک داده‌ی مشترک اجرا می‌کند، ولی به‌جای فقط خلاصه، دقیقاً نشان می‌دهد:

  - چه معاملاتی را فازی حذف کرد (Baseline داشت، Fuzzy نداشت) و نتیجه‌ی
    واقعی آن‌ها چه بود (سودده بودند یا ضررده؟)
  - چه معاملاتی را فازی اضافه کرد (Baseline نداشت، Fuzzy گرفت) و نتیجه‌ی
    واقعی آن‌ها چه بود
  - برای هر Override، دلیل فازی (Rule Fired) را از evidence_snapshot می‌خواند

هیچ فایلی از RSP را تغییر نمی‌دهد.
"""
import argparse

from RSP.ingestion.data_universe import build_data_universe
from RSP.config import settings
from RSP.backtest_engine.backtest_engine import run_backtest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coin", default="bitcoin")
    ap.add_argument("--days", type=float, default=settings.DEFAULT_LOOKBACK_DAYS)
    args = ap.parse_args()

    universe = build_data_universe(args.coin, lookback_days=args.days)

    settings.FUZZY_BACKTEST_ENABLED = False
    baseline = run_backtest(universe.bars, base_tf="15M")

    settings.FUZZY_BACKTEST_ENABLED = True
    fuzzy = run_backtest(universe.bars, base_tf="15M")

    off = {t.timestamp: t for t in baseline.trades}
    on = {t.timestamp: t for t in fuzzy.trades}

    only_baseline = sorted(set(off) - set(on))   # فازی این‌ها را رد کرد
    only_fuzzy = sorted(set(on) - set(off))       # فازی این‌ها را اضافه کرد
    both = set(off) & set(on)

    def summarize(label, keys, table):
        wins = sum(1 for k in keys if table[k].outcome == "WIN")
        losses = sum(1 for k in keys if table[k].outcome == "LOSS")
        total_pnl = sum(table[k].pnl_pct for k in keys)
        print(f"\n{label}: n={len(keys)}  wins={wins}  losses={losses}  "
              f"total_pnl_pct={total_pnl:.2f}  avg_pnl_pct={(total_pnl/len(keys) if keys else 0):.3f}")
        return total_pnl

    print(f"coin={args.coin}  days={args.days}")
    print(f"baseline: trades={baseline.total_trades}  net_return_pct={baseline.net_return_pct}")
    print(f"fuzzy:    trades={fuzzy.total_trades}  net_return_pct={fuzzy.net_return_pct}")

    skipped_pnl = summarize("REJECTED_BY_FUZZY (baseline had these, fuzzy didn't)", only_baseline, off)
    added_pnl = summarize("ADDED_BY_FUZZY (fuzzy took these, baseline didn't)", only_fuzzy, on)
    print(f"\nNet effect of fuzzy's trade selection changes: "
          f"{(added_pnl - skipped_pnl):+.2f} pct-points "
          f"(added_pnl - skipped_pnl; negative = fuzzy's changes hurt)")

    print("\n--- up to 15 REJECTED trades (were they good or bad?) ---")
    for k in only_baseline[:15]:
        t = off[k]
        print(f"  {k}  action={t.action:<4} regime={t.regime:<18} outcome={t.outcome:<4} "
              f"pnl={t.pnl_pct:>7.3f}  exit={t.exit_reason}")

    print("\n--- up to 15 ADDED trades (were they good or bad?) + fuzzy reason ---")
    for k in only_fuzzy[:15]:
        t = on[k]
        fz = (t.evidence_snapshot or {}).get("fuzzy", {})
        print(f"  {k}  action={t.action:<4} regime={t.regime:<18} outcome={t.outcome:<4} "
              f"pnl={t.pnl_pct:>7.3f}  exit={t.exit_reason}  "
              f"fuzzy_rule={fz.get('rule_fired')}  opp_score={fz.get('opportunity_score')}")


if __name__ == "__main__":
    main()
