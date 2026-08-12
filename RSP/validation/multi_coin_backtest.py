"""
RSP — validation/multi_coin_backtest.py

هدف: اجرای موتور فریز‌شده‌ی RSP (بدون تغییر هیچ پارامتر/threshold/weight) روی
همه‌ی کوین‌های موجود در SYMBOL_MAP، برای بررسی تعمیم (generalization) به‌جای
تکیه بر یک کوین (فعلاً فقط bitcoin تست شده بود).

این فایل هیچ فایل production را import-side-effect نمی‌کند و هیچ مقداری در
config/settings.py را تغییر نمی‌دهد؛ فقط توابع موجود run_backtest /
run_walk_forward / run_overfitting_check را برای هر کوین به‌ترتیب صدا می‌زند.

اجرا:
    cd arsan.1-main
    python -m RSP.validation.multi_coin_backtest
    python -m RSP.validation.multi_coin_backtest --days 90 --coins bitcoin ethereum solana
    python -m RSP.validation.multi_coin_backtest --skip-walkforward   # فقط backtest ساده، سریع‌تر

خروجی:
    - جدول متن‌ساده در stdout (قابل کپی در گزارش)
    - JSON کامل در RSP/validation/results/multi_coin_<timestamp>.json

نکته: این اسکریپت هیچ threshold مخصوص هیچ کوینی نمی‌سازد و اگر عملکرد یک
کوین ضعیف بود، همان‌طور در جدول/JSON ثبت می‌شود — نه حذف و نه دستکاری.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from RSP.ingestion.data_universe import build_data_universe
from RSP.ingestion.symbol_map import SYMBOL_MAP
from RSP.backtest_engine.backtest_engine import run_backtest
from RSP.walk_forward.walk_forward import run_walk_forward
from RSP.anti_overfitting.overfitting_lab import run_overfitting_check
from RSP.config import settings

ALL_COINS = list(SYMBOL_MAP.keys())


def _summary_to_dict(s):
    return {
        "total_trades": s.total_trades,
        "wins": s.wins,
        "losses": s.losses,
        "win_rate": s.win_rate,
        "net_return_pct": s.net_return_pct,
        "profit_factor": s.profit_factor,
        "max_drawdown_pct": s.max_drawdown_pct,
        "average_trade_pct": s.average_trade_pct,
    }


def run_one_coin(coin: str, days: float, skip_walkforward: bool, min_history: int):
    result = {
        "coin": coin,
        "lookback_days": days,
        "fuzzy_engine_enabled": bool(getattr(settings, "FUZZY_BACKTEST_ENABLED", False)),
        "opportunity_scoring_method": getattr(settings, "OPPORTUNITY_SCORING_METHOD", None),
        "error": None,
    }

    try:
        universe = build_data_universe(coin, lookback_days=days)
    except Exception as e:
        result["error"] = f"DATA_UNIVERSE_ERROR: {e}"
        return result

    base_df = universe.bars.get("15M")
    result["source_used"] = universe.source_used
    result["is_reconstructed"] = universe.is_reconstructed
    result["actual_candles_15M"] = universe.actual_candles.get("15M", 0)

    if base_df is None or base_df.empty:
        result["error"] = "NO_DATA_15M"
        return result

    # --- Backtest ساده (کل بازه، بدون walk-forward) ---
    try:
        bt = run_backtest(universe.bars, base_tf="15M", min_history=min_history)
        result["backtest"] = _summary_to_dict(bt)
    except Exception as e:
        result["error"] = f"BACKTEST_ERROR: {e}"
        return result

    # --- Walk-Forward + Overfitting ---
    if not skip_walkforward:
        try:
            wf = run_walk_forward(universe.bars, base_tf="15M", min_history=min_history)
            of = run_overfitting_check(wf)
            result["walk_forward"] = {
                "num_windows": len(wf.windows),
                "aggregate_test_win_rate": wf.aggregate_test_win_rate,
                "aggregate_test_net_return": wf.aggregate_test_net_return,
                "aggregate_validate_win_rate": wf.aggregate_validate_win_rate,
                "aggregate_validate_net_return": wf.aggregate_validate_net_return,
                "notes": wf.notes,
            }
            result["overfitting"] = {
                "overall_status": of.overall_status,
                "windows_flagged": of.windows_flagged,
                "notes": of.notes,
            }
        except Exception as e:
            result["walk_forward_error"] = str(e)

    return result


def print_table(results):
    print("\n" + "=" * 100)
    print("RSP — MULTI-COIN VALIDATION (FROZEN ENGINE, NO PARAMETER CHANGES)")
    print("=" * 100)
    header = f"{'coin':<14}{'trades':>8}{'win_rate':>10}{'net_ret%':>10}{'PF':>8}{'maxDD%':>9}{'OOS_status':>16}"
    print(header)
    print("-" * 100)
    for r in results:
        if r.get("error"):
            print(f"{r['coin']:<14}{'ERROR: ' + r['error']}")
            continue
        bt = r.get("backtest", {})
        of = r.get("overfitting", {})
        print(
            f"{r['coin']:<14}"
            f"{bt.get('total_trades', 0):>8}"
            f"{bt.get('win_rate', 0):>10.2f}"
            f"{bt.get('net_return_pct', 0):>10.2f}"
            f"{bt.get('profit_factor', 0):>8.2f}"
            f"{bt.get('max_drawdown_pct', 0):>9.2f}"
            f"{of.get('overall_status', 'N/A'):>16}"
        )
    print("=" * 100)
    n_ok = sum(1 for r in results if not r.get("error"))
    n_err = sum(1 for r in results if r.get("error"))
    print(f"موفق: {n_ok}   خطا/بدون‌داده: {n_err}   (خطا اغلب یعنی دسترسی شبکه‌ی محیط اجرا، نه باگ موتور)")


def main():
    parser = argparse.ArgumentParser(description="RSP multi-coin validation (frozen engine)")
    parser.add_argument("--coins", nargs="*", default=None,
                         help=f"لیست coin_id ها (پیش‌فرض همه‌ی {len(ALL_COINS)} کوین موجود در SYMBOL_MAP)")
    parser.add_argument("--days", type=float, default=settings.DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--skip-walkforward", action="store_true")
    parser.add_argument("--min-history", type=int, default=60)
    args = parser.parse_args()

    coins = args.coins if args.coins else ALL_COINS
    unknown = [c for c in coins if c not in SYMBOL_MAP]
    if unknown:
        print(f"WARNING: این کوین‌ها در SYMBOL_MAP نیستند و رد می‌شوند: {unknown}")
        coins = [c for c in coins if c in SYMBOL_MAP]

    print(f"در حال اجرا روی {len(coins)} کوین: {coins}")
    print(f"lookback_days={args.days}  OPPORTUNITY_SCORING_METHOD={settings.OPPORTUNITY_SCORING_METHOD}  "
          f"FUZZY_BACKTEST_ENABLED={getattr(settings, 'FUZZY_BACKTEST_ENABLED', False)}")

    results = []
    for coin in coins:
        print(f"\n--- {coin} ---")
        r = run_one_coin(coin, args.days, args.skip_walkforward, args.min_history)
        if r.get("error"):
            print(f"  ERROR: {r['error']}")
        else:
            bt = r["backtest"]
            print(f"  trades={bt['total_trades']}  win_rate={bt['win_rate']}  "
                  f"net_return={bt['net_return_pct']}  PF={bt['profit_factor']}  "
                  f"maxDD={bt['max_drawdown_pct']}")
        results.append(r)

    print_table(results)

    out_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(out_dir, f"multi_coin_{ts}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": ts,
            "lookback_days": args.days,
            "config_snapshot": {
                "OPPORTUNITY_SCORING_METHOD": settings.OPPORTUNITY_SCORING_METHOD,
                "FUZZY_BACKTEST_ENABLED": getattr(settings, "FUZZY_BACKTEST_ENABLED", False),
                "RANGE_REGIME_NO_TRADE": getattr(settings, "RANGE_REGIME_NO_TRADE", None),
            },
            "results": results,
        }, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nJSON کامل ذخیره شد در: {out_path}")


if __name__ == "__main__":
    main()
