"""
fuzzy_training_export.py — زیرساخت مشترک AHP و ANFIS (Task 2 و 3)

کنار main.py (توی arsan.1، بیرون از RSP) بگذارید و اجرا کنید:

    python fuzzy_training_export.py --coin ethereum --days 240 --out training_data.json

برای هر نقطه‌ای که موتور Crisp تصمیم BUY/SELL می‌گیرد، این‌ها را ذخیره می‌کند:
  - تمام امتیازهای خام (پیش از فازی‌سازی) هر ۹ موتور کیفیت — هم نسخه‌ی قدیمی
    (legacy) هم نسخه‌ی بازطراحی‌شده (percentile-based / continuous) برای
    مقایسه‌ی مستقیم قبل/بعد روی همان رکوردها
  - Bounded Uncertainty (lower/upper/confidence) برای risk_quality و
    volatility_quality
  - نتیجه‌ی واقعیِ آن معامله (WIN/LOSS، pnl_pct) — از همان شبیه‌ساز معاملات
    backtest_engine استفاده می‌کند تا کاملاً با بک‌تست شما سازگار باشد.

علاوه‌بر این، یک فایل دوم هم می‌سازد: <out>.contradiction_trace.json — روی
یک نمونه از *همه‌ی* کندل‌ها (نه فقط BUY/SELL) contradiction را trace می‌کند
تا محور ۱ (رفع مغایرت contradiction_severity) قابل تأیید مستقل باشد؛ این فایل
هیچ pnl label ندارد (چون بیشتر این کندل‌ها اصلاً معامله نمی‌شوند).

خروجی: training_data.json — این را برای من می‌فرستید.

هیچ فایلی از RSP را تغییر نمی‌دهد؛ فقط می‌خواند و فایل‌های جدید JSON می‌سازد.
"""
import argparse
import json

from RSP.ingestion.data_universe import build_data_universe
from RSP.config import settings
from RSP.preprocessing.quality_engine import check_quality
from RSP.regime_engine.regime_engine import determine_regime
from RSP.signal_engine.confluence import analyze_confluence
from RSP.multi_timeframe.mtf_brain import analyze_mtf
from RSP.signal_fusion.fusion_engine import fuse_signals
from RSP.contradiction_engine.contradiction_engine import detect_contradictions
from RSP.confidence_engine.confidence_engine import compute_confidence
from RSP.decision_engine.decision_brain import decide
from RSP.risk_engine.risk_engine import plan_risk
from RSP.execution_simulator.trade_simulator import simulate_trade

from RSP.fuzzy_core.quality_engines import (
    _raw_trend_quality, _raw_momentum_quality, _raw_entry_quality,
    _raw_risk_quality, _raw_risk_quality_legacy, _raw_risk_quality_bounded,
    _raw_volatility_quality, _raw_volatility_quality_legacy, _raw_volatility_quality_bounded,
    _raw_market_stability, _raw_signal_strength, _raw_signal_confidence,
    _raw_contradiction_severity, _raw_contradiction_severity_legacy,
)


def _known_slice(df, ts, max_bars=None):
    sliced = df[df.index <= ts]
    if max_bars is not None and len(sliced) > max_bars:
        sliced = sliced.iloc[-max_bars:]
    return sliced


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coin", default="bitcoin")
    ap.add_argument("--days", type=float, default=settings.DEFAULT_LOOKBACK_DAYS)
    ap.add_argument("--out", default="training_data.json")
    ap.add_argument("--trace-every", type=int, default=5,
                     help="هر چند کندل یک‌بار در contradiction_trace ثبت شود (پیش‌فرض هر ۵ کندل، تا فایل خیلی بزرگ نشود)")
    args = ap.parse_args()

    universe = build_data_universe(args.coin, lookback_days=args.days)
    bars = universe.bars
    base_df = bars.get("15M")

    records = []
    contradiction_trace = []  # روی کل جمعیت کندل‌ها (نه فقط BUY/SELL) — برای محور ۱
    i = 60
    n = len(base_df)
    while i < n - 1:
        current_ts = base_df.index[i]
        known = {tf: _known_slice(df, current_ts, max_bars=settings.MAX_WARMUP_BARS) for tf, df in bars.items()}
        known_base = known["15M"]

        quality = check_quality(known_base, "15M")
        regime = determine_regime(known_base)
        confluence = analyze_confluence(known_base)
        mtf = analyze_mtf(known)
        fusion = fuse_signals(regime, confluence, mtf)
        contradiction = detect_contradictions(fusion, mtf)
        confidence = compute_confidence(fusion, mtf, contradiction, quality.quality_score, regime.perception.atr_pct)
        decision = decide(regime, fusion, mtf, contradiction, confidence, quality.quality_ok)

        # --- محور ۱: trace روی کل جمعیت کندل‌ها (این دقیقاً همان جمعیتی است که
        # backtest_engine.py لایه‌ی فازی را رویش اجرا می‌کند - نه فقط BUY/SELL) ---
        if i % args.trace_every == 0:
            contradiction_trace.append({
                "timestamp": str(current_ts),
                "crisp_action": decision.action,
                "conflict_detected": contradiction.conflict_detected,
                "conflict_ratio": contradiction.conflict_ratio,
                "mtf_disagreement": contradiction.mtf_disagreement,
                "severity": contradiction.severity,
                "net_score": contradiction.net_score,
                "raw_contradiction_legacy": _raw_contradiction_severity_legacy(contradiction),
                "raw_contradiction_continuous": _raw_contradiction_severity(contradiction),
            })

        if decision.action in ("BUY", "SELL"):
            rp = plan_risk(decision.action, known_base, regime)
            if rp.valid:
                future_bars = base_df.iloc[i + 1:]
                trade_result = simulate_trade(decision.action, rp.entry, rp.stop_loss, rp.take_profit, future_bars)

                atr_pct = regime.perception.atr_pct
                atr_history = regime.perception.atr_pct_series  # فقط تا همین کندل — walk-forward safe
                momentum_raw = _raw_momentum_quality(confluence)
                record = {
                    "timestamp": str(current_ts),
                    "action": decision.action,
                    "regime": regime.regime,
                    "raw_scores": {
                        "trend_quality": _raw_trend_quality(regime, confluence),
                        "momentum_quality": 0.30 if momentum_raw is None else momentum_raw,
                        "entry_quality": _raw_entry_quality(mtf, regime.structure),
                        "risk_quality": _raw_risk_quality_legacy(rp, atr_pct),
                        "risk_quality_v2": _raw_risk_quality(rp, atr_pct, atr_history, regime),
                        "volatility_quality": _raw_volatility_quality_legacy(atr_pct, regime),
                        "volatility_quality_v2": _raw_volatility_quality(atr_pct, regime, atr_history),
                        "market_stability": _raw_market_stability(regime, regime.structure),
                        "signal_strength": _raw_signal_strength(fusion),
                        "signal_confidence": _raw_signal_confidence(confidence),
                        "contradiction_severity": _raw_contradiction_severity_legacy(contradiction),
                        "contradiction_severity_v2": _raw_contradiction_severity(contradiction),
                    },
                    "bounded": {
                        "risk_quality_v2": _raw_risk_quality_bounded(rp, atr_pct, atr_history, regime).as_dict(),
                        "volatility_quality_v2": _raw_volatility_quality_bounded(atr_pct, regime, atr_history).as_dict(),
                    },
                    "risk_reward": rp.risk_reward,
                    "atr_pct": atr_pct,
                    "atr_history_n": len(atr_history) if atr_history else 0,
                    "outcome": trade_result.outcome,
                    "pnl_pct": trade_result.pnl_pct,
                    "win": 1 if trade_result.outcome == "WIN" else 0,
                }
                records.append(record)

        i += 1
        if i % 2000 == 0:
            print(f"...{i}/{n} steps processed  ({len(records)} tradeable so far)")

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({"coin": args.coin, "days": args.days, "n_records": len(records),
                    "records": records}, f, ensure_ascii=False, indent=1)

    trace_path = args.out.rsplit(".", 1)[0] + ".contradiction_trace.json"
    with open(trace_path, "w", encoding="utf-8") as f:
        json.dump({"coin": args.coin, "days": args.days, "n_bars": len(contradiction_trace),
                    "bars": contradiction_trace}, f, ensure_ascii=False, indent=1)

    wins = sum(r["win"] for r in records)
    print(f"\nSaved {len(records)} records to {args.out}  "
          f"(wins={wins}, losses={len(records)-wins}, win_rate={wins/len(records)*100:.1f}%)"
          if records else "\nNo tradeable records found.")
    print(f"Saved {len(contradiction_trace)} bar-level contradiction traces to {trace_path}")


if __name__ == "__main__":
    main()
