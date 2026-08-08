"""
fuzzy_training_export.py — زیرساخت مشترک AHP و ANFIS (Task 2 و 3)

کنار main.py (توی arsan.1، بیرون از RSP) بگذارید و اجرا کنید:

    python fuzzy_training_export.py --coin ethereum --days 240 --out training_data.json

برای هر نقطه‌ای که موتور Crisp تصمیم BUY/SELL می‌گیرد، این‌ها را ذخیره می‌کند:
  - تمام امتیازهای خام (پیش از فازی‌سازی) هر ۹ موتور کیفیت
  - نتیجه‌ی واقعیِ آن معامله (WIN/LOSS، pnl_pct) — از همان شبیه‌ساز معاملات
    backtest_engine استفاده می‌کند تا کاملاً با بک‌تست شما سازگار باشد.

خروجی: یک فایل JSON (training_data.json) — این را برای من می‌فرستید (یا از
طریق ahp_calibrate.py / anfis_train.py که جداگانه می‌فرستم پردازشش می‌کنید).

هیچ فایلی از RSP را تغییر نمی‌دهد؛ فقط می‌خواند و یک فایل جدید JSON می‌سازد.
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
    _raw_risk_quality, _raw_volatility_quality, _raw_market_stability,
    _raw_signal_strength, _raw_signal_confidence, _raw_contradiction_severity,
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
    args = ap.parse_args()

    universe = build_data_universe(args.coin, lookback_days=args.days)
    bars = universe.bars
    base_df = bars.get("15M")

    records = []
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

        if decision.action in ("BUY", "SELL"):
            rp = plan_risk(decision.action, known_base, regime)
            if rp.valid:
                future_bars = base_df.iloc[i + 1:]
                trade_result = simulate_trade(decision.action, rp.entry, rp.stop_loss, rp.take_profit, future_bars)

                momentum_raw = _raw_momentum_quality(confluence)
                record = {
                    "timestamp": str(current_ts),
                    "action": decision.action,
                    "regime": regime.regime,
                    "raw_scores": {
                        "trend_quality": _raw_trend_quality(regime, confluence),
                        "momentum_quality": 0.30 if momentum_raw is None else momentum_raw,
                        "entry_quality": _raw_entry_quality(mtf, regime.structure),
                        "risk_quality": _raw_risk_quality(rp, regime.perception.atr_pct),
                        "volatility_quality": _raw_volatility_quality(regime.perception.atr_pct, regime),
                        "market_stability": _raw_market_stability(regime, regime.structure),
                        "signal_strength": _raw_signal_strength(fusion),
                        "signal_confidence": _raw_signal_confidence(confidence),
                        "contradiction_severity": _raw_contradiction_severity(contradiction),
                    },
                    "risk_reward": rp.risk_reward,
                    "atr_pct": regime.perception.atr_pct,
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

    wins = sum(r["win"] for r in records)
    print(f"\nSaved {len(records)} records to {args.out}  "
          f"(wins={wins}, losses={len(records)-wins}, win_rate={wins/len(records)*100:.1f}%)"
          if records else "\nNo tradeable records found.")


if __name__ == "__main__":
    main()
