"""
test_volatility_risk_gate_calibration.py

تست‌های regression برای کالیبراسیون گیت‌های risk_quality_v2/volatility_quality_v2
(محور ۱ از دستور کار کالیبراسیون). بدون نیاز به دیتای زنده/اینترنت — کاملاً
synthetic، کنار main.py اجرا کنید:

    python test_volatility_risk_gate_calibration.py

بررسی می‌کند:
  1. Baseline (settings.USE_PERCENTILE_RISK_VOLATILITY=False) دقیقاً رفتار
     legacy را حفظ کرده (raw score قدیمی + متغیر فازی قدیمی).
  2. با flag=True، روی یک توزیع واقع‌گرایانه‌ی ATR% (synthetic ولی با شکل شبیه
     داده‌ی واقعی)، دیگر بیش از حد معقول (اینجا سقف ۲۵٪ گذاشتیم؛ عدد واقعی
     حدود ۱۷.۸٪ روی training_data.json واقعی بود) رد نمی‌شود.
  3. تمام خروجی‌های fuzzify شده در [0,1] هستند.
  4. هیچ NaN/Inf در raw score یا fuzzify تولید نمی‌شود.
"""
import math
import random
import sys

from RSP.config import settings
from RSP.regime_engine.perception import PerceptionReport
from RSP.regime_engine.regime_engine import RegimeReport
from RSP.market_structure.structure_engine import StructureReport
from RSP.risk_engine.risk_engine import RiskPlan
from RSP.fuzzy_core.quality_engines import (
    _raw_volatility_quality, _raw_volatility_quality_legacy,
    _raw_risk_quality, _raw_risk_quality_legacy,
    evaluate_volatility_quality, evaluate_risk_quality,
)


def _make_regime(regime_name="UPTREND", atr_pct=0.4):
    perception = PerceptionReport(state=regime_name, atr_pct=atr_pct)
    structure = StructureReport()
    return RegimeReport(regime=regime_name, perception=perception, structure=structure)


def _synthetic_atr_history(n=500, seed=0):
    random.seed(seed)
    # شبیه توزیع واقعی ETH/15M: چوله به راست، اکثراً زیر ۱٪
    return [round(abs(random.gauss(0.4, 0.25)), 3) for _ in range(n)]


def test_baseline_unchanged_when_no_history_passed():
    """
    decision_controller فقط وقتی settings.USE_PERCENTILE_RISK_VOLATILITY=True
    باشد atr_history را به evaluate_volatility_quality پاس می‌دهد (نگاه کنید
    decision_controller.run_fuzzy_decision). این تست خودِ آن رفتار شرطی را
    مستقل از مقدار فعلی settings آزمایش می‌کند: وقتی atr_history=None باشد
    (یعنی معادل flag=False در سطح فراخوانی)، خروجی باید دقیقاً legacy باشد؛
    مقدار پیش‌فرض فعلی settings.USE_PERCENTILE_RISK_VOLATILITY خودش جداگانه
    در دستور اجرای بک‌تست قابل rollback است (فقط یک خط در settings.py).
    """
    regime = _make_regime(atr_pct=0.8)

    fuzzy_out = evaluate_volatility_quality(0.8, regime, atr_history=None)
    raw_legacy = _raw_volatility_quality_legacy(0.8, regime)
    from RSP.fuzzy_core.membership import get_quality_variable
    expected = get_quality_variable("volatility_quality").fuzzify(raw_legacy)
    assert fuzzy_out == expected, "بدون atr_history باید دقیقاً legacy باشد"
    print("OK: بدون atr_history رفتار دقیقاً legacy است (rollback-safe)")


def test_percentile_mode_does_not_reject_runaway():
    """
    وقتی مسیر percentile واقعاً فعال است (atr_history کافی پاس داده شده)،
    نسبت رکوردهایی که poor/very_poor >= 0.60 می‌گیرند (یعنی در _permission_gate
    رد می‌شوند) نباید یک کاهش افراطی (>25%) مثل قبل از کالیبراسیون (۳۰.۴٪ با
    مرزهای قدیمی روی مقیاس جدید) بدهد.
    """
    history = _synthetic_atr_history(n=600)
    rejected = 0
    total = 0
    for atr in history[100:]:  # فقط بعد از warmup کافی برای percentile
        regime = _make_regime(regime_name="UPTREND", atr_pct=atr)
        fuzzy_out = evaluate_volatility_quality(atr, regime, atr_history=history[:history.index(atr)] or history[:200])
        poor_gate = max(fuzzy_out.get("poor", 0.0), fuzzy_out.get("very_poor", 0.0))
        total += 1
        if poor_gate >= 0.60:
            rejected += 1

    frac = rejected / total
    print(f"fraction rejected by poor/very_poor gate (percentile mode): {frac*100:.1f}%")
    assert frac < 0.25, f"نسبت رد‌شده‌ها {frac*100:.1f}% بیش از حد بالاست (کالیبراسیون ناقص)"


def test_fuzzy_outputs_bounded_and_finite():
    """همه‌ی خروجی‌های fuzzify باید در [0,1] و بدون NaN/Inf باشند."""
    history = _synthetic_atr_history(n=400)
    test_atrs = [0.0, 0.05, 0.4, 0.8, 1.2, 1.93, 5.0, 50.0]  # شامل مقادیر حدی/غیرعادی
    for atr in test_atrs:
        regime = _make_regime(atr_pct=atr)
        for hist in (None, [], history):
            out = evaluate_volatility_quality(atr, regime, atr_history=hist)
            for term, mu in out.items():
                assert not math.isnan(mu) and not math.isinf(mu), f"NaN/Inf در term={term}, atr={atr}"
                assert -1e-9 <= mu <= 1.0 + 1e-9, f"خارج از [0,1]: term={term} mu={mu} atr={atr}"

            rp = RiskPlan(action="BUY", risk_reward=2.0, valid=True)
            out_r = evaluate_risk_quality(rp, atr, atr_history=hist, regime=regime)
            for term, mu in out_r.items():
                assert not math.isnan(mu) and not math.isinf(mu), f"NaN/Inf در risk term={term}, atr={atr}"
                assert -1e-9 <= mu <= 1.0 + 1e-9, f"خارج از [0,1]: risk term={term} mu={mu} atr={atr}"
    print("OK: تمام خروجی‌ها bounded و بدون NaN/Inf هستند")


def test_no_valid_risk_plan_still_bounded():
    """RiskPlan نامعتبر (valid=False) نباید کرش کند یا خارج از بازه بدهد."""
    regime = _make_regime(atr_pct=0.5)
    rp = RiskPlan(action="BUY", valid=False)
    raw = _raw_risk_quality(rp, 0.5, atr_history=None, regime=regime)
    assert 0.0 <= raw <= 1.0
    raw_legacy = _raw_risk_quality_legacy(rp, 0.5)
    assert 0.0 <= raw_legacy <= 1.0
    print("OK: RiskPlan نامعتبر هم bounded می‌ماند")


def test_ahp_score_bounded_and_rollback_safe():
    """
    ahp_opportunity_score همیشه در [0,100] است. و default settings
    (OPPORTUNITY_SCORING_METHOD="rules") یعنی run_fuzzy_decision اصلاً از AHP
    استفاده نمی‌کند - این را با فراخوانی مستقیم تابع AHP (مستقل از فراخوانی
    توسط decision_controller) و بررسی مقدار پیش‌فرض settings تأیید می‌کنیم.
    """
    from RSP.fuzzy_core.ahp_scoring import ahp_opportunity_score
    assert getattr(settings, "OPPORTUNITY_SCORING_METHOD", "rules") == "rules", \
        "پیش‌فرض باید rules بماند (rollback-safe)؛ اگر عمداً به ahp تغییر دادید این تست را نادیده بگیرید"
    for trend, risk, vol_bad in [(0.0, 0.0, 0.0), (1.0, 1.0, 1.0), (0.5, 0.3, 0.9), (-1, 2, -5)]:
        s = ahp_opportunity_score(trend, risk, vol_bad)
        assert 0.0 <= s <= 100.0, f"AHP score خارج از بازه: {s}"
    print("OK: ahp_opportunity_score همیشه bounded [0,100] و پیش‌فرض rollback-safe است")


if __name__ == "__main__":
    tests = [
        test_baseline_unchanged_when_no_history_passed,
        test_percentile_mode_does_not_reject_runaway,
        test_fuzzy_outputs_bounded_and_finite,
        test_no_valid_risk_plan_still_bounded,
        test_ahp_score_bounded_and_rollback_safe,
    ]
    failed = 0
    for t in tests:
        try:
            t()
        except AssertionError as e:
            failed += 1
            print(f"FAIL: {t.__name__}: {e}")
    if failed:
        print(f"\n{failed}/{len(tests)} تست شکست خورد")
        sys.exit(1)
    print(f"\nهمه‌ی {len(tests)} تست پاس شد")
