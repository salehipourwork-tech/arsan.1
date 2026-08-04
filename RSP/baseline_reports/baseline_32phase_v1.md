# Baseline — RSP 32-Phase (قبل از Fuzzy Engine)
تاریخ ثبت: 2026-08-03 | تنظیمات: STOP_LOSS_ATR_MULTIPLIER=3.0, RANGE_REGIME_NO_TRADE=True,
EXHAUSTION_FILTER_ENABLED=True (threshold=0.70), COOLDOWN_BARS_AFTER_STOP_LOSS=6,
Walk-Forward: train=1200/validate=400/test=400/step=400 bars, lookback=240 روز

| Coin     | Windows | agg_test_win_rate | agg_test_net_return | overfitting_status | OK | WARNING | SEVERE | INSUFFICIENT |
|----------|---------|--------------------|-----------------------|---------------------|----|---------|--------|--------------|
| bitcoin  | 52      | 38.93%             | -42.048%              | OVERFITTING_SEVERE  | 29 | 3       | 18     | 2            |
| ethereum | 52      | 34.70%             | -53.930%              | OVERFITTING_SEVERE  | 29 | 6       | 17     | 0            |
| solana   | 52      | 33.83%             | -78.181%               | OVERFITTING_SEVERE  | 29 | 6       | 17     | 0            |

## نکات مهم برای مقایسه‌ی Fuzzy-vs-Baseline
- SEVERE ratio (از پنجره‌های معتبر/غیر-INSUFFICIENT) هر سه کوین: ~33-36% — الگوی پایدار بین دارایی‌ها
- هیچ کوینی edge مثبت نداره (همه‌ی net_return ها منفی)
- Fuzzy Engine باید حداقل این دو معیار رو بهتر کنه تا "موفق" تلقی بشه:
  1. SEVERE ratio پایین‌تر (ثبات زمانی بیشتر)
  2. aggregate_test_net_return بهتر (نه صرفاً کمتر منفی به خاطر کاهش تعداد معامله)
