"""
ahp_calibrate.py — وزن‌دهی AHP (Analytic Hierarchy Process) روی feature هایی
که تا الان از نظر آماری روی داده‌ی واقعی تأیید شدن.

فقط ۳ feature (نه هر ۹ تا): trend_quality (بازکالیبره‌شده)، risk_quality_v2،
volatility_quality_v2 — چون بقیه یا هنوز واریانس ندارن یا correlation
معناداری با pnl واقعی نشون ندادن (نگاه کنید به تحلیل‌های قبلی). وزن‌دادن به
معیارهای بی‌معنا فقط نویز رو پیچیده‌تر می‌کنه.

روش: Saaty pairwise comparison + geometric-mean weighting (استاندارد AHP) —
نه grid-search/بهینه‌سازی مستقیم روی PnL. قضاوت‌های pairwise (کدوم feature
چقدر مهم‌تره) از روی رتبه‌ی *نسبی* (نه مقدار دقیق) همبستگی Spearman با pnl
واقعی گرفته شده — این یعنی جهت‌گیری از داده میاد ولی وزن نهایی حاصل جست‌وجو/
optimization روی همین دیتاست نیست؛ فقط یک‌بار محاسبه و اعمال می‌شه.

اجرا:
    python ahp_calibrate.py --data training_data.json

خروجی: وزن‌های AHP + Consistency Ratio + correlation اعتبارسنجی weighted
opportunity score با pnl واقعی (این یک validation یک‌باره‌ست، نه تیونینگ).
"""
import argparse
import json
import math

import numpy as np
from scipy import stats

FEATURES = ["trend_quality", "risk_quality_v2", "volatility_quality_v2"]

# -----------------------------------------------------------------------
# ماتریس Pairwise (Saaty scale 1-9). قضاوت‌ها از رتبه‌ی نسبی |Spearman r| با
# pnl واقعی (روی 2050 رکورد ETH/240D) گرفته شده:
#   trend_quality           |r|=0.099  (ضعیف‌ترین)
#   risk_quality_v2          |r|=0.168
#   volatility_quality_v2    |r|=0.171  (نزدیک به risk_quality_v2)
# نسبت‌ها: risk/trend≈1.7→۲ ("اهمیت کمی بیشتر")، vol/trend≈1.7→۲،
# vol/risk≈1.0→۱ ("تقریباً برابر"). این‌ها گرد شده به نزدیک‌ترین درجه‌ی Saaty
# هستند، نه فیت دقیق روی رقم اعشاری correlation (که می‌شد overfitting).
# -----------------------------------------------------------------------
PAIRWISE = np.array([
    #                trend   risk    vol
    [                1.0,    1/2,    1/2],   # trend_quality
    [                2.0,    1.0,    1.0],   # risk_quality_v2
    [                2.0,    1.0,    1.0],   # volatility_quality_v2
])

RANDOM_INDEX = {1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12, 6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49}


def ahp_weights(matrix: np.ndarray):
    """
    وزن‌دهی با روش Geometric Mean (استاندارد و پایدارتر از eigenvector خام
    برای ماتریس‌های کوچک) + محاسبه‌ی Consistency Ratio (CR) با λmax تقریبی.
    """
    n = matrix.shape[0]
    row_geo_mean = np.array([math.prod(matrix[i, :]) ** (1.0 / n) for i in range(n)])
    weights = row_geo_mean / row_geo_mean.sum()

    # λmax تقریبی: (Matrix @ weights) / weights ، میانگین‌گیری
    weighted_sum = matrix @ weights
    lambda_max = np.mean(weighted_sum / weights)
    ci = (lambda_max - n) / (n - 1) if n > 1 else 0.0
    ri = RANDOM_INDEX.get(n, 1.49)
    cr = ci / ri if ri > 0 else 0.0

    return weights, lambda_max, ci, cr


def load_features(path: str):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    records = data["records"]
    trend = np.array([r["raw_scores"]["trend_quality"] for r in records])
    risk_v2 = np.array([r["raw_scores"].get("risk_quality_v2", r["raw_scores"].get("risk_quality")) for r in records])
    vol_v2_badness = np.array([r["raw_scores"].get("volatility_quality_v2", r["raw_scores"].get("volatility_quality")) for r in records])
    pnl = np.array([r["pnl_pct"] for r in records])
    win = np.array([r["win"] for r in records])
    return trend, risk_v2, vol_v2_badness, pnl, win


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="training_data.json")
    args = ap.parse_args()

    weights, lambda_max, ci, cr = ahp_weights(PAIRWISE)
    print("=== AHP Pairwise Matrix ===")
    print(f"{'':20s}" + "".join(f"{f:>20s}" for f in FEATURES))
    for i, f in enumerate(FEATURES):
        print(f"{f:20s}" + "".join(f"{PAIRWISE[i, j]:20.3f}" for j in range(len(FEATURES))))
    print()
    print("=== AHP Weights ===")
    for f, w in zip(FEATURES, weights):
        print(f"  {f:25s} = {w:.4f}")
    print(f"\nlambda_max={lambda_max:.4f}  CI={ci:.4f}  CR={cr:.4f}  "
          f"({'قابل قبول (CR<0.10)' if cr < 0.10 else 'ناسازگار - بازبینی کن'})")

    trend, risk_v2, vol_badness, pnl, win = load_features(args.data)
    vol_goodness = 1.0 - vol_badness  # AHP روی مقیاس «خوبی» جمع می‌بندیم؛ badness باید معکوس شود

    w_trend, w_risk, w_vol = weights
    weighted_score = w_trend * trend + w_risk * risk_v2 + w_vol * vol_goodness

    r, p = stats.pearsonr(weighted_score, pnl)
    sr, sp = stats.spearmanr(weighted_score, pnl)
    pb, pbp = stats.pointbiserialr(win, weighted_score)

    print("\n=== Validation (یک‌باره، نه optimization) روی همین دیتاست ===")
    print(f"weighted_opportunity_score ~ pnl_pct :  pearson r={r:+.4f} p={p:.5f}   spearman r={sr:+.4f} p={sp:.5f}")
    print(f"weighted_opportunity_score ~ win      :  point-biserial r={pb:+.4f} p={pbp:.5f}")
    print(f"\nمقایسه با تک‌تک feature ها (باید بهتر یا هم‌سطح باشه، نه لزوماً خیلی بهتر):")
    for name, arr in [("trend_quality", trend), ("risk_quality_v2", risk_v2), ("volatility_quality_v2 (goodness)", vol_goodness)]:
        rr, pp = stats.spearmanr(arr, pnl)
        print(f"  {name:35s} spearman r={rr:+.4f} p={pp:.5f}")


if __name__ == "__main__":
    main()
