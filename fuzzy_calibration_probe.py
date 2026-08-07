"""
fuzzy_calibration_probe.py — Task 2 داده‌جمع‌کن (نه یک فایل تغییر یافته‌ی RSP)

این اسکریپت را کنار main.py (یعنی داخل ریشه‌ی arsan.1) بگذارید و اجرا کنید:

    python fuzzy_calibration_probe.py --coin ethereum --days 240

خروجی: برای هر ورودی خام موتورهای کیفیت فازی (پیش از fuzzify شدن)،
percentile های p10/p25/p50/p75/p90 چاپ می‌شود — این اعداد واقعی بازار
هستند، نه حدسی. این خروجی را برای من بفرستید تا Membership Function ها
را بر اساس توزیع واقعی (نه اعداد ثابت) کالیبره کنم (Task 2 سند).

هیچ فایلی از RSP را تغییر نمی‌دهد؛ فقط می‌خواند و گزارش می‌دهد.
"""
import argparse
import statistics
import sys

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


def _known_slice(df, ts, max_bars=None):
    sliced = df[df.index <= ts]
    if max_bars is not None and len(sliced) > max_bars:
        sliced = sliced.iloc[-max_bars:]
    return sliced


def _pct(values, p):
    if not values:
        return None
    s = sorted(values)
    k = (len(s) - 1) * p
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    if f == c:
        return round(s[f], 4)
    return round(s[f] + (s[c] - s[f]) * (k - f), 4)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--coin", default="bitcoin")
    ap.add_argument("--days", type=float, default=settings.DEFAULT_LOOKBACK_DAYS)
    args = ap.parse_args()

    universe = build_data_universe(args.coin, lookback_days=args.days)
    bars = universe.bars
    base_df = bars.get("15M")
    if base_df is None or base_df.empty:
        print("ERROR: no 15M data for", args.coin)
        sys.exit(1)

    # هر ورودی خام (پیش از fuzzify) که موتورهای کیفیت فازی می‌سازند
    samples = {
        "atr_pct_all_steps": [],
        "risk_reward_when_tradeable": [],
        "contradiction_conflict_ratio": [],
        "entry_score_raw": [],  # از evaluate_entry_quality بازسازی‌شده (0.50 base + ...)
    }
    n_total = 0
    n_tradeable = 0

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

        n_total += 1
        samples["atr_pct_all_steps"].append(regime.perception.atr_pct)
        samples["contradiction_conflict_ratio"].append(contradiction.conflict_ratio)

        if decision.action in ("BUY", "SELL"):
            n_tradeable += 1
            rp = plan_risk(decision.action, known_base, regime)
            if rp.valid:
                samples["risk_reward_when_tradeable"].append(rp.risk_reward)

            entry_score = 0.50
            entry_score += 0.25 if mtf.aligned else -0.25
            if mtf.aligned and mtf.entry_bias in ("BULLISH", "BEARISH"):
                entry_score += 0.10
            if regime.structure.last_structure_event in ("BOS_BULLISH", "BOS_BEARISH"):
                entry_score += 0.15
            elif regime.structure.last_structure_event in ("CHOCH_BULLISH", "CHOCH_BEARISH"):
                entry_score += 0.10
            elif regime.structure.pattern == "MIXED":
                entry_score -= 0.10
            samples["entry_score_raw"].append(max(0.0, min(1.0, entry_score)))

        i += 1
        if i % 2000 == 0:
            print(f"...{i}/{n} steps processed", file=sys.stderr)

    print(f"\ncoin={args.coin}  days={args.days}  total_steps={n_total}  tradeable_steps(BUY/SELL)={n_tradeable}\n")
    for key, values in samples.items():
        if not values:
            print(f"{key:<32} (no samples)")
            continue
        print(f"{key:<32} n={len(values):<6} "
              f"mean={statistics.mean(values):.4f}  "
              f"p10={_pct(values,0.10)}  p25={_pct(values,0.25)}  "
              f"p50={_pct(values,0.50)}  p75={_pct(values,0.75)}  p90={_pct(values,0.90)}")


if __name__ == "__main__":
    main()
