"""
RSP — validation/multi_coin_backtest.py

هدف: اجرای موتور فریز‌شده‌ی RSP (بدون تغییر هیچ پارامتر/threshold/weight) روی
همه‌ی کوین‌های موجود در SYMBOL_MAP، برای بررسی تعمیم (generalization) به‌جای
تکیه بر یک کوین (فعلاً فقط bitcoin تست شده بود).

این فایل هیچ فایل production را import-side-effect نمی‌کند و هیچ threshold/
weight/calibration parameter‌ای را تغییر نمی‌دهد. تنها «مقدار» که این
اسکریپت صراحتاً ست می‌کند settings.FUZZY_BACKTEST_ENABLED است — که طبق
مستندات خودِ RSP/backtest_engine/backtest_engine.py «تنها نقطه‌ی کنترل»
فعال/غیرفعال بودن لایه‌ی فازی است (نه یک threshold تصمیم‌گیری) و دقیقاً
همان مکانیزمی است که main.py با --fuzzy-engine / --fuzzy-compare استفاده
می‌کند (نگاه کن به main.py::_run_fuzzy_compare). یعنی این اسکریپت رفتار
تصمیم‌گیری موتور را تغییر نمی‌دهد، فقط همان سوییچ رسمی و مستندشده را همان‌طور
که main.py هم استفاده می‌کند، صدا می‌زند.

--- چرا قبلاً FUZZY_BACKTEST_ENABLED=false گزارش می‌شد (ریشه‌ی باگ) ---
RSP/config/settings.py مقدار پیش‌فرض FUZZY_BACKTEST_ENABLED را False می‌گذارد
(عمداً، تا رفتار غیر-فازی هیچ فایلی که صریحاً درخواست فازی نمی‌کند عوض نشود).
تنها جایی که این مقدار در زمان اجرا True می‌شود RSP/main.py است: وقتی کاربر
فلگ --fuzzy-engine (یا --fuzzy-compare) را می‌دهد، main.py خط
`settings.FUZZY_BACKTEST_ENABLED = True` را اجرا می‌کند (main.py خطوط
221-222 و 146/149). این اسکریپت (multi_coin_backtest.py) هرگز از طریق
main.py اجرا نمی‌شود — مستقیماً run_backtest/run_walk_forward را صدا می‌زد
— پس هیچ‌کجای مسیر اجرای آن آن خط را نداشت و settings.FUZZY_BACKTEST_ENABLED
همیشه روی مقدار پیش‌فرض False از settings.py می‌ماند؛ این یک باگ در
validation script بود، نه در موتور production. (تأیید با کد: خودِ
run_backtest در هر فراخوانی مقدار زنده‌ی settings.FUZZY_BACKTEST_ENABLED را
می‌خواند — `use_fuzzy = bool(settings.FUZZY_BACKTEST_ENABLED)` — پس تغییر آن
قبل از فراخوانی run_backtest/run_walk_forward کافی و صحیح است؛ نیازی به
تغییر امضای تابع یا فایل production نیست.)

اجرا:
    cd arsan.1-main
    python -m RSP.validation.multi_coin_backtest                       # پیش‌فرض: mode=fuzzy
    python -m RSP.validation.multi_coin_backtest --mode fuzzy --days 90
    python -m RSP.validation.multi_coin_backtest --mode baseline --days 90
    python -m RSP.validation.multi_coin_backtest --mode both --days 90 # baseline و fuzzy جدا، هرگز قاطی نمی‌شوند
    python -m RSP.validation.multi_coin_backtest --days 90 --coins bitcoin ethereum solana
    python -m RSP.validation.multi_coin_backtest --skip-walkforward   # فقط backtest ساده، سریع‌تر

mode:
    fuzzy    (پیش‌فرض) — همان نسخه‌ای که باید اعتبارسنجی شود: AHP + Fuzzy Engine
             روشن، دقیقاً هم‌ارز با main.py --fuzzy-engine. قبل از هر فراخوانی
             build_data_universe/run_backtest/run_walk_forward،
             settings.FUZZY_BACKTEST_ENABLED = True ست می‌شود.
    baseline — فازی خاموش (رفتار قدیمی/crisp). برای مقایسه، نه برای validation.
    both     — هر دو، کاملاً جدا (دو دور اجرای کامل و دو بلوک جدا در JSON:
               results_baseline و results_fuzzy)؛ هیچ‌وقت در یک دیکشنری
               قاطی نمی‌شوند.

خروجی:
    - جدول متن‌ساده در stdout (قابل کپی در گزارش)
    - JSON کامل در RSP/validation/results/multi_coin_<mode>_<timestamp>.json

نکته: این اسکریپت هیچ threshold مخصوص هیچ کوینی نمی‌سازد و اگر عملکرد یک
کوین ضعیف بود، همان‌طور در جدول/JSON ثبت می‌شود — نه حذف و نه دستکاری.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from RSP.ingestion.data_universe import build_data_universe
from RSP.ingestion.symbol_map import SYMBOL_MAP
from RSP.backtest_engine.backtest_engine import run_backtest
from RSP.walk_forward.walk_forward import run_walk_forward
from RSP.anti_overfitting.overfitting_lab import run_overfitting_check
from RSP.config import settings

# Import مستقیم پل فازی همین‌جا (نه فقط داخل backtest_engine) تا اگر import
# فازی fail کند، این validation script صریحاً خطا/هشدار بدهد به‌جای اینکه
# backtest_engine بی‌سروصدا به حالت crisp سقوط کند (نگاه کن به try/except
# اطراف import در backtest_engine.py که عمداً "honest fallback" است، اما
# برای validation باید صراحتاً گزارش شود، نه بی‌صدا رد شود).
try:
    from RSP.fuzzy_integration_bridge import integrate_fuzzy_decision  # noqa: F401
    _FUZZY_IMPORT_OK = True
    _FUZZY_IMPORT_ERROR = None
except Exception as _e:  # pragma: no cover
    _FUZZY_IMPORT_OK = False
    _FUZZY_IMPORT_ERROR = str(_e)

ALL_COINS = list(SYMBOL_MAP.keys())


def _summary_to_dict(s):
    d = {
        "total_trades": s.total_trades,
        "wins": s.wins,
        "losses": s.losses,
        "win_rate": s.win_rate,
        "net_return_pct": s.net_return_pct,
        "profit_factor": s.profit_factor,
        "max_drawdown_pct": s.max_drawdown_pct,
        "average_trade_pct": s.average_trade_pct,
    }
    # --- Fuzzy runtime diagnostics (واقعی، از خودِ BacktestSummary.fuzzy_diagnostics) ---
    # این‌ها را از ساختن metric جعلی خودداری می‌کنیم: هر عددی که اینجا هست
    # مستقیماً از فیلدهایی می‌آید که backtest_engine.run_backtest در هر گام
    # واقعاً محاسبه کرده (fuzzy_steps / fuzzy_overrides / rejection_reasons).
    fd = getattr(s, "fuzzy_diagnostics", None) or {}
    d["fuzzy_steps"] = fd.get("fuzzy_steps")
    d["fuzzy_overrides"] = fd.get("fuzzy_overrides")
    d["fuzzy_opportunity_score_avg"] = fd.get("opportunity_score_avg")
    d["fuzzy_rejection_reasons"] = fd.get("rejection_reasons")
    n_rejections = sum(fd["rejection_reasons"].values()) if fd.get("rejection_reasons") else 0
    d["rejection_rate"] = (
        round(n_rejections / fd["fuzzy_steps"], 4)
        if fd.get("fuzzy_steps") else None
    )
    # exposure واقعاً در BacktestSummary موجود نیست (موتور آن را محاسبه/برنمی‌گرداند)
    # -> عمداً None می‌گذاریم، نه یک عدد ساختگی.
    d["exposure"] = None

    # --- Task 1-3 سند کالیبراسیون: Failure Analysis روی rejected trades ---
    # از حالا که fuzzy_steps/rejection_reasons فقط روی کاندیدهای واقعی BUY/SELL
    # جمع می‌شوند (نه روی هر کندل)، rejected_trade_outcomes همان چیزی است که
    # سند خواسته: هر Gate چند معامله‌ی WIN و چند LOSS را رد کرده.
    rto = fd.get("rejected_trade_outcomes") or {}
    d["rejected_trade_outcomes"] = rto
    total_rejected_wins = sum(v.get("wins", 0) for v in rto.values())
    total_rejected_losses = sum(v.get("losses", 0) for v in rto.values())
    total_rejected_known = total_rejected_wins + total_rejected_losses
    d["rejected_win_rate"] = (
        round(100 * total_rejected_wins / total_rejected_known, 2)
        if total_rejected_known else None
    )
    d["rejected_loss_rate"] = (
        round(100 * total_rejected_losses / total_rejected_known, 2)
        if total_rejected_known else None
    )
    return d


def run_one_coin(coin: str, days: float, skip_walkforward: bool, min_history: int,
                  fuzzy_on: bool):
    """
    fuzzy_on: این تابع، دقیقاً مثل main.py هنگام --fuzzy-engine، قبل از هر
    فراخوانی build_data_universe/run_backtest/run_walk_forward
    settings.FUZZY_BACKTEST_ENABLED را ست می‌کند. هیچ threshold/weight دیگری
    در settings دست نمی‌خورد.
    """
    settings.FUZZY_BACKTEST_ENABLED = bool(fuzzy_on)

    result = {
        "coin": coin,
        "lookback_days": days,
        "fuzzy_enabled": bool(getattr(settings, "FUZZY_BACKTEST_ENABLED", False)),
        "opportunity_scoring_method": getattr(settings, "OPPORTUNITY_SCORING_METHOD", None),
        "fuzzy_import_ok": _FUZZY_IMPORT_OK,
        "fuzzy_import_error": _FUZZY_IMPORT_ERROR,
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
        result["trade_frequency_per_day"] = (
            round(bt.total_trades / days, 4) if days else None
        )
        # --- Runtime verification (نه صرفاً config flag) ---
        # fuzzy_steps در هر گام backtest که integrate_fuzzy_decision موفق و
        # used_fuzzy=True بوده افزایش می‌یابد (نگاه کن به backtest_engine.py و
        # fuzzy_integration_bridge.py::integrate_fuzzy_decision). یعنی
        # fuzzy_steps>0 یعنی «کد فازی واقعاً روی حداقل یک کندل اجرا شده»،
        # نه فقط اینکه فلگ config روی True است.
        fuzzy_steps = (bt.fuzzy_diagnostics or {}).get("fuzzy_steps")
        if fuzzy_on:
            result["fuzzy_runtime_verified"] = bool(fuzzy_steps and fuzzy_steps > 0)
            if not result["fuzzy_runtime_verified"]:
                result["fuzzy_runtime_note"] = (
                    "FUZZY_BACKTEST_ENABLED=True بود اما fuzzy_steps=0 یا خالی شد — "
                    "یعنی کد فازی روی هیچ کندلی واقعاً اجرا نشده (احتمالاً به‌خاطر "
                    "کمبود داده/کندل کافی برای عبور از min_history، نه لزوماً باگ). "
                    "قبل از اعلام PASS این کوین را جداگانه بررسی کن."
                )
        else:
            result["fuzzy_runtime_verified"] = (fuzzy_steps in (None, 0))
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
            # --- تضمین می‌کنیم fuzzy در walk-forward هم واقعاً همان‌قدر فعال
            # بوده که در backtest ساده (نباید Backtest:Fuzzy ON ولی
            # Walk-forward:Fuzzy OFF بشود؛ چون هر دو از همان run_backtest
            # استفاده می‌کنند و ما همان یک بار settings.FUZZY_BACKTEST_ENABLED
            # را ست کردیم، این پاراگراف فقط "verify" است نه "enforce"). ---
            wf_fuzzy_steps_total = 0
            for w in wf.windows:
                wf_fuzzy_steps_total += (w.test_summary.fuzzy_diagnostics or {}).get("fuzzy_steps", 0) or 0
            result["walk_forward"]["fuzzy_steps_total_across_windows"] = wf_fuzzy_steps_total
            if fuzzy_on and wf.windows and wf_fuzzy_steps_total == 0:
                result["walk_forward"]["fuzzy_runtime_note"] = (
                    "fuzzy_on=True ولی مجموع fuzzy_steps تمام پنجره‌های "
                    "walk-forward صفر است — احتمال Backtest:ON / "
                    "Walk-forward:OFF را بررسی کن."
                )
        except Exception as e:
            result["walk_forward_error"] = str(e)

    return result


def print_table(results, label):
    print("\n" + "=" * 100)
    print(f"RSP — MULTI-COIN VALIDATION (FROZEN ENGINE, NO PARAMETER CHANGES) — mode={label}")
    print("=" * 100)
    header = (f"{'coin':<14}{'trades':>8}{'win_rate':>10}{'net_ret%':>10}{'PF':>8}"
              f"{'maxDD%':>9}{'fzy_steps':>10}{'fzy_ovr':>9}{'OOS_status':>16}")
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
            f"{str(bt.get('fuzzy_steps')):>10}"
            f"{str(bt.get('fuzzy_overrides')):>9}"
            f"{of.get('overall_status', 'N/A'):>16}"
        )
    print("=" * 100)
    n_ok = sum(1 for r in results if not r.get("error"))
    n_err = sum(1 for r in results if r.get("error"))
    print(f"موفق: {n_ok}   خطا/بدون‌داده: {n_err}   (خطا اغلب یعنی دسترسی شبکه‌ی محیط اجرا، نه باگ موتور)")
    if label == "fuzzy":
        n_unverified = sum(1 for r in results if not r.get("error") and r.get("fuzzy_runtime_verified") is False)
        if n_unverified:
            print(f"⚠ {n_unverified} کوین با fuzzy_on=True اما fuzzy_runtime_verified=False — بررسی کن.")


def print_failure_analysis(results):
    """
    Task 1-3 سند کالیبراسیون: به ازای هر Gate، در کل ۸ کوین، چند معامله‌ی
    واقعی WIN و چند LOSS رد شده — تا مشخص شود کدام Gate واقعاً false
    rejection بالا دارد (باید محکم شود) و کدام درست عمل می‌کند (نباید صرفاً
    برای افزایش trade count سست شود).
    """
    agg: Dict[str, Dict[str, int]] = {}
    for r in results:
        if r.get("error"):
            continue
        rto = (r.get("backtest") or {}).get("rejected_trade_outcomes") or {}
        for gate, wl in rto.items():
            bucket = agg.setdefault(gate, {"wins": 0, "losses": 0})
            bucket["wins"] += wl.get("wins", 0)
            bucket["losses"] += wl.get("losses", 0)

    if not agg:
        print("\n(هیچ rejected_trade_outcome ثبت نشد — یا فازی خاموش بود یا هیچ "
              "کاندید واقعی BUY/SELL رد نشد)")
        return

    print("\n" + "=" * 100)
    print("FAILURE ANALYSIS — rejected trades به تفکیک Gate (مجموع همه‌ی کوین‌ها)")
    print("=" * 100)
    print(f"{'gate':<32}{'rejected_wins':>15}{'rejected_losses':>17}{'total':>9}{'rejected_win_rate%':>20}")
    print("-" * 100)
    for gate, wl in sorted(agg.items(), key=lambda kv: -(kv[1]["wins"] + kv[1]["losses"])):
        total = wl["wins"] + wl["losses"]
        wr = round(100 * wl["wins"] / total, 2) if total else 0.0
        flag = "  <-- بیشتر WIN رد می‌کند، سست‌تر کن" if wr > 50 else ""
        print(f"{gate:<32}{wl['wins']:>15}{wl['losses']:>17}{total:>9}{wr:>20.2f}{flag}")
    print("=" * 100)
    print("راهنما: rejected_win_rate بالای ۵۰٪ یعنی این Gate بیشتر معاملات "
          "WIN را حذف می‌کند تا LOSS -> کاندید اصلی برای سست‌شدن Calibration. "
          "پایین (نزدیک صفر) یعنی Gate درست عمل می‌کند و نباید صرفاً برای "
          "افزایش trade count تغییر کند (طبق سند کالیبراسیون).")


def _run_suite(coins, days, skip_walkforward, min_history, fuzzy_on):
    results = []
    for coin in coins:
        print(f"\n--- {coin} (fuzzy_on={fuzzy_on}) ---")
        r = run_one_coin(coin, days, skip_walkforward, min_history, fuzzy_on=fuzzy_on)
        if r.get("error"):
            print(f"  ERROR: {r['error']}")
        else:
            bt = r["backtest"]
            print(f"  trades={bt['total_trades']}  win_rate={bt['win_rate']}  "
                  f"net_return={bt['net_return_pct']}  PF={bt['profit_factor']}  "
                  f"maxDD={bt['max_drawdown_pct']}  fuzzy_steps={bt.get('fuzzy_steps')}  "
                  f"fuzzy_overrides={bt.get('fuzzy_overrides')}")
        results.append(r)
    return results


def main():
    parser = argparse.ArgumentParser(description="RSP multi-coin validation (frozen engine)")
    parser.add_argument("--coins", nargs="*", default=None,
                         help=f"لیست coin_id ها (پیش‌فرض همه‌ی {len(ALL_COINS)} کوین موجود در SYMBOL_MAP)")
    parser.add_argument("--days", type=float, default=settings.DEFAULT_LOOKBACK_DAYS)
    parser.add_argument("--skip-walkforward", action="store_true")
    parser.add_argument("--min-history", type=int, default=60)
    parser.add_argument("--mode", choices=["fuzzy", "baseline", "both"], default="fuzzy",
                         help="fuzzy (پیش‌فرض) = نسخه‌ای که باید validate شود (AHP+Fuzzy ON، "
                              "معادل main.py --fuzzy-engine). baseline = فازی خاموش، فقط برای "
                              "مقایسه. both = هر دو، کاملاً جدا از هم.")
    args = parser.parse_args()

    coins = args.coins if args.coins else ALL_COINS
    unknown = [c for c in coins if c not in SYMBOL_MAP]
    if unknown:
        print(f"WARNING: این کوین‌ها در SYMBOL_MAP نیستند و رد می‌شوند: {unknown}")
        coins = [c for c in coins if c in SYMBOL_MAP]

    if not _FUZZY_IMPORT_OK and args.mode in ("fuzzy", "both"):
        print(f"⚠ WARNING: import فازی (fuzzy_integration_bridge) شکست خورد: {_FUZZY_IMPORT_ERROR}\n"
              f"  mode={args.mode} درخواست شده اما کد فازی اصلاً قابل اجرا نیست — نتایج fuzzy_steps "
              f"همیشه 0/خالی خواهند بود و fuzzy_runtime_verified=False می‌شود.")

    print(f"در حال اجرا روی {len(coins)} کوین: {coins}")
    print(f"lookback_days={args.days}  mode={args.mode}  "
          f"OPPORTUNITY_SCORING_METHOD={settings.OPPORTUNITY_SCORING_METHOD}")

    modes_to_run = {"fuzzy": [True], "baseline": [False], "both": [False, True]}[args.mode]
    all_blocks = {}
    for fuzzy_on in modes_to_run:
        label = "fuzzy" if fuzzy_on else "baseline"
        results = _run_suite(coins, args.days, args.skip_walkforward, args.min_history, fuzzy_on)
        print_table(results, label)
        if label == "fuzzy":
            print_failure_analysis(results)
        all_blocks[label] = {
            "config_snapshot": {
                "OPPORTUNITY_SCORING_METHOD": settings.OPPORTUNITY_SCORING_METHOD,
                "FUZZY_BACKTEST_ENABLED": fuzzy_on,
                "RANGE_REGIME_NO_TRADE": getattr(settings, "RANGE_REGIME_NO_TRADE", None),
                "FUZZY_ENGINE_ENABLED_setting": getattr(settings, "FUZZY_ENGINE_ENABLED", None),
                "STOP_LOSS_ATR_MULTIPLIER": getattr(settings, "STOP_LOSS_ATR_MULTIPLIER", None),
                "fuzzy_import_ok": _FUZZY_IMPORT_OK,
            },
            "results": results,
        }

    # همیشه فازی را روی حالت پیش‌فرض امن (خاموش) برمی‌گردانیم تا هیچ اثر جانبی
    # روی فرآیندهای بعدی (مثلاً اگر این ماژول import شود، نه فقط اجرا) نماند.
    settings.FUZZY_BACKTEST_ENABLED = False

    out_dir = os.path.join(os.path.dirname(__file__), "results")
    os.makedirs(out_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = os.path.join(out_dir, f"multi_coin_{args.mode}_{ts}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": ts,
            "mode": args.mode,
            "lookback_days": args.days,
            **all_blocks,
        }, f, ensure_ascii=False, indent=2, default=str)
    print(f"\nJSON کامل ذخیره شد در: {out_path}")


if __name__ == "__main__":
    main()
