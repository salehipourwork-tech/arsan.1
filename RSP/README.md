# RSP — Research & Strategy Playground

آزمایشگاه مستقل تحقیق، آزمایش، توسعه، بک‌تست و ارزیابی نسل‌های بعدی موتور
تصمیم‌گیری آرسان. **کاملاً جدا از آرسان اصلی** — هیچ فایلی در `analyzer/`،
`index.html`، `dashboard.html`، یا `data/` آرسان تغییر نکرده است.

## اجرا

```bash
cd arsan.1-main
pip install pandas numpy requests
python -m RSP.main --coin bitcoin                    # تحلیل لحظه‌ای + گزارش Explainable
python -m RSP.main --coin bitcoin --backtest         # بک‌تست کامل روی داده‌ی تاریخی
python -m RSP.main --coin bitcoin --walkforward      # Walk Forward + Anti-Overfitting (Phase 20/21)
python -m RSP.main --coin bitcoin --stress           # Stress Test رژیم‌محور + سناریوهای مصنوعی (Phase 22)
python -m RSP.main --coin bitcoin --montecarlo       # Sequence Randomization + Perturbation (Phase 23)
python -m RSP.main --coin bitcoin --versions         # مقایسه‌ی V1/V2/V3 (Phase 27)
python -m RSP.main --coin bitcoin --challenge V1 V2  # داوری Out-of-Sample بین دو نسخه (Phase 28)
```

Self Evaluation و Failure Analysis (فاز ۲۴/۲۵) روی خروجی یک بک‌تست اجرا می‌شوند
(چون به `evidence_snapshot` هر معامله نیاز دارند)، نه از خط فرمان مستقیم -
نمونه‌ی استفاده:

```python
from RSP.ingestion.data_universe import build_data_universe
from RSP.backtest_engine.backtest_engine import run_backtest
from RSP.self_evaluation.self_evaluation import evaluate_all, summarize
from RSP.self_evaluation.failure_analysis import analyze_failures

universe = build_data_universe("bitcoin")
summary = run_backtest(universe.bars, base_tf="15M")
evals = evaluate_all(summary.trades)
print(summarize(evals))
print(analyze_failures(summary.trades, evals).notes)
```

خروجی `--backtest` را می‌توانید در فایل JSON ذخیره کنید و در
`RSP/visualization/rsp_dashboard.html` بارگذاری کنید (فایل را در مرورگر باز
کنید و JSON را از طریق دکمه‌ی بارگذاری انتخاب کنید — کاملاً استاتیک و آفلاین).

## داده — منابع رایگان چند-گانه (طبق درخواست شما)

هر تایم‌فریم به‌ترتیب از این منابع (همه رایگان، بدون API Key) fallback
می‌شود تا وابستگی به یک منبع نباشد:

1. **Binance** — کندل واقعی صرافی، همه‌ی تایم‌فریم‌ها
2. **KuCoin** — کندل واقعی، پوشش بهتر آلت‌کوین
3. **Kraken** — کندل واقعی
4. **Coinbase Exchange** — کندل واقعی (4H از تجمیع کندل‌های واقعی 1H)
5. **CoinGecko** — آخرین fallback؛ چون فقط سری قیمت می‌دهد نه کندل صرافی، با
   resample بازسازی می‌شود و `is_reconstructed=True` علامت می‌خورد تا هیچ‌وقت
   به‌جای داده‌ی واقعی جا زده نشود.

این‌که واقعاً از کدام منبع برای هر تایم‌فریم استفاده شده، در خروجی
`data_universe.source_used` و در گزارش Explainability ثبت می‌شود.

## ⚠️ محدودیت مهم تست در این محیط

کدها **syntax-check** شدند و پایپ‌لاین کامل (Perception → Regime → MTF →
Confluence → Fusion → Contradiction → Decision → Confidence → Risk → Trade
Quality → Simulator → Backtest) روی **داده‌ی مصنوعی OHLCV** به‌طور کامل تا
انتها اجرا و صحت‌سنجی شد (دو سناریو: random-walk بدون Edge واقعی → سیستم
عملکرد ضعیف/محافظه‌کارانه داد، نه سود ساختگی؛ روند صعودی قوی → سیستم BUY
داد و سودده بود). اما اتصال زنده به Binance/KuCoin/Kraken/Coinbase/CoinGecko
در این sandbox قابل تست نبود چون خروجی شبکه‌ی این محیط به دامنه‌های محدودی
(GitHub، PyPI، npm و...) قفل است و صرافی‌ها در فهرست مجاز نیستند. **حتماً
قبل از اعتماد کامل، یک بار در محیط واقعی پروژه (مثلاً همان GitHub Actions
runner که آرسان اصلی رویش اجرا می‌شود) با `python -m RSP.main --coin
bitcoin` تست دستی انجام بده.**

در حین همین تست با داده‌ی مصنوعی، یک باگ واقعی پیدا و رفع شد: منطق اولیه‌ی
«هم‌جهتی تایم‌فریم‌ها» در `multi_timeframe/mtf_brain.py` به‌قدری سخت‌گیر بود
که خنثی‌بودن تایم‌فریم ۱D به‌تنهایی کل سیستم را همیشه به WAIT می‌برد، حتی در
روند صعودی واضح. طبق مثال خود اسپک («تضاد» یعنی *خلاف‌جهت*، نه خنثی)، این
اصلاح شد.

## وضعیت واقعی هر فاز (طبق درخواست صریح شما — بدون قلمداد کردن ناقص به‌جای کامل)

### ✅ پیاده‌سازی‌شده و کارکردی (تست‌شده روی داده‌ی مصنوعی)
| فاز | وضعیت |
|---|---|
| 1 — RSP Core | ساختار کامل، ۲۶ ماژول مستقل |
| 2 — Data Universe | چند-منبعی با fallback، REQUIRED/OPTIONAL مشخص |
| 3 — Data Quality Engine | تشخیص Gap/Duplicate/Invalid OHLC/Zero Volume/Spike |
| 4 — Market Perception | ترکیب Trend+ADX+MA+Volatility+Volume+Momentum |
| 5 — Market Regime Engine | ۱۶ رژیم + Regime-Aware Strategy Selection |
| 6 — Multi-Timeframe Brain | Context/Trend/Entry + WAIT_FOR_CONFIRMATION |
| 7 — Technical Intelligence | Confluence: Agreement/Conflict/Divergence/Momentum |
| 8 — Market Structure | Swing/HH-HL/LH-LL/BOS/CHoCH/S-R (Liquidity Zones ✗) |
| 9 — Signal Fusion | ۶ دسته شواهد، وزن‌دهی تطبیقی بر اساس رژیم |
| 10 — Contradiction Engine | CONFLICT_DETECTED با آستانه‌ی قابل‌تنظیم |
| 11 — Decision Brain | BUY/SELL/HOLD/WAIT/NO_TRADE + WHY/WHY_NOT/INVALIDATION |
| 12 — Confidence Engine | ترکیب ۶ مؤلفه (نه معادل احتمال سود) |
| 13 — Adaptive Weighting | جدول وزن per-regime در config، ثبت‌شده و قابل بازگشت |
| 14 — Strategy Library | ۶ استراتژی با Entry/Exit/Risk/Invalidation Rules |
| 15 — Strategy Selector | انتخاب بر اساس رژیم + قدرت net_score |
| 16 — Risk Engine | Entry/SL/TP مبتنی بر ATR+ساختار، Position Sizing |
| 17 — Trade Quality Engine | امتیاز ترکیبی، NO_TRADE زیر آستانه |
| 18 — Realistic Trade Simulator | Fee+Slippage+برخورد محافظه‌کارانه‌ی SL/TP هم‌کندل |
| 19 — Backtest Engine | حرکت زمانی گام‌به‌گام، بدون Future Leakage (تضمین ساختاری) |
| 20 — Walk Forward | Train/Validate/Test با پنجره‌ی متحرک، نتایج تک‌تک پنجره‌ها ذخیره می‌شود |
| 21 — Anti-Overfitting Lab | مقایسه‌ی Win Rate + میانگین سود هر معامله بین Validate و Test هر پنجره، هشدار OVERFITTING_WARNING/SEVERE |
| 22 — Stress Test | دو بخش: (الف) عملکرد واقعی به‌تفکیک رژیم از یک بک‌تست واقعی، (ب) سناریوهای مصنوعی Bull/Bear/Sideways/Crash/HighVol/LowVol/FalseBreakout/SuddenReversal برای تست مهندسی موتور |
| 23 — Monte Carlo / Robustness | Trade Sequence Randomization (Bootstrap ترتیب معاملات واقعی) + Fee/Slippage/Parameter Perturbation |
| 24 — Self Evaluation Engine | تحلیل heuristic بعد از هر معامله: کدام شواهد گمراه‌کننده بودند، Entry ضعیف بود یا نه، Risk Management ضعیف بود یا نه |
| 25 — Failure Analysis | دسته‌بندی خودکار زیان‌ها به ۹ دسته‌ی خواسته‌شده در اسپک + تشخیص غالب‌ترین الگوی شکست |
| 26 — Experiment Manager | ثبت JSON با ID (`RSP-EXP-NNN`) |
| 27 — Versioned Strategy Lab | ۳ نسخه (V1 Baseline, V2 محافظه‌کار, V3 تهاجمی) با override موقت و قابل بازگشت تنظیمات، مقایسه‌پذیر |
| 28 — Challenger System | داوری Champion vs Challenger **فقط** بر اساس بازده Out-of-Sample (بخش Test در Walk Forward)، نه In-Sample |
| 30 — Decision Explainability | گزارش انسانی کامل (DECISION/REASON/MISSING/INVALIDATION) |
| 31 — RSP Dashboard | HTML مستقل، آفلاین، جدا از داشبورد آرسان |
| 32 — Final Evaluation | همه‌ی فیلدهای خواسته‌شده در گزارش Explainability موجودند |

همه‌ی فازهای بالا (۲۰ تا ۲۸) روی داده‌ی مصنوعی اجرا و صحت‌سنجی شدند (بدون
کرش، خروجی منطقی) — جزئیات در بخش «تست» پایین همین فایل.

### 🟡 پیاده‌سازی جزئی (چارچوب واقعی دارد، ولی محدودیت مشخصی دارد)
| فاز | چه چیزی هست / چه چیزی نیست |
|---|---|
| 20 — Walk Forward | «Train» چون موتور rule-based است نه ML، فقط به‌معنای گرم‌کردن اندیکاتورهاست، نه Fit پارامتر واقعی؛ محدودیت داخل کد و README مستند شده |
| 29 — Arsan Comparison | چارچوب مقایسه (`comparison/arsan_vs_rsp.py`) موجود است و متریک‌های RSP را واقعی محاسبه می‌کند؛ اما اجرای خودکار `analyzer/backtest_lab.py` آرسان انجام **نشده** چون امضای ورودی/خروجی آن مستند نبود و حدس‌زدن آن ریسک تولید عدد غلط داشت — عمداً به‌جای عدد جعلی، وضعیت `NOT_AVAILABLE` برمی‌گرداند |

### ❌ طراحی‌شده اما پیاده‌سازی نشده (به‌صراحت، نه چیزی که پنهان شده باشد)
| مورد | دلیل |
|---|---|
| Liquidity Zones (بخشی از Phase 8) | فقط Support/Resistance ساده از Swing Point پیاده شده |
| Portfolio Engine (پوشه در ساختار هست) | خالی — چون اسپک روی معامله‌ی تکی تمرکز داشت، مدیریت پرتفوی چندکوینه ساخته نشده |
| اجرای خودکار Stress Test روی بازه‌های تاریخی واقعی برچسب‌خورده (مثل «کریپتوکراش مارس ۲۰۲۰») | نیاز به دیتاست تاریخی طولانی‌مدت دارد که با محدودیت ۳۰۰ کندل هر درخواست (فعلی) به‌صورت خودکار به آن دسترسی نداریم؛ تابع `robustness/stress_test.performance_by_market_type` روی هر بک‌تستی که به آن بدهید کار می‌کند، فقط نیاز به تزریق داده‌ی تاریخی بیشتر دارد |

## ⚡ نکته‌ی کارایی (Performance)

`backtest_engine` برای هر گام زمانی، کل اندیکاتورها را از نو روی slice
تا آن لحظه محاسبه می‌کند (دقیق و بدون نشتی، ولی کند). در نتیجه:
Walk Forward، Perturbation Suite، و Challenger که همگی چندین بار
`run_backtest` را فراخوانی می‌کنند، روی دیتاست‌های بزرگ (چند هزار کندل)
می‌توانند چند ده ثانیه تا چند دقیقه طول بکشند. برای دیتاست‌های خیلی بزرگ،
این بخش نیاز به بهینه‌سازی (محاسبه‌ی incremental به‌جای recompute کامل)
دارد که در این نسخه انجام نشده - مستند و شناخته‌شده است، نه یک باگ پنهان.

## داده‌های همیشه در دسترس نیست (صادقانه، طبق Phase 2/3)

با منابع رایگان فعلی (Binance/KuCoin/Kraken/Coinbase/CoinGecko)، این فیلدها
همیشه `DATA_MISSING` هستند و **هیچ‌جای کد شبیه‌سازی/جعل نمی‌شوند**:
Funding Rate, Open Interest, Liquidation Data, Order Book, Trade Count,
Market Dominance, Market Breadth, Correlation, Relative Strength.

## قانون صفر — رعایت‌شده

هیچ خطی از `analyzer/`, `index.html`, `dashboard.html`, `data/`, یا هر
Workflow موجود در `.github/workflows/` تغییر نکرده است. `RSP/` یک پکیج
پایتون کاملاً مستقل است که فقط از داخل خودش import می‌کند.

هیچ Live Trading، سفارش واقعی، یا API Key معاملاتی در این کد وجود ندارد
(`config/settings.py: LIVE_TRADING_ENABLED = False`, hardcoded).

## تست انجام‌شده روی فازهای ۲۰ تا ۲۸

روی داده‌ی مصنوعی OHLCV (چند سناریو: random-walk، روند صعودی قوی، دیتاست
کوچک‌تر برای تست سرعت)، همه‌ی موارد زیر بدون کرش اجرا و خروجی‌شان منطقی
راستی‌آزمایی شد:

- `run_walk_forward` → پنجره‌بندی صحیح Train/Validate/Test، بدون همپوشانی
- `run_overfitting_check` → به‌درستی وضعیت `OVERFITTING_SEVERE` را روی دیتاست
  کوچک/نویزی تشخیص داد (رفتار مورد انتظار، چون با داده‌ی کم Overfitting شدیدتر است)
- `performance_by_market_type` + `run_synthetic_scenarios` → دسته‌بندی صحیح
  بر اساس رژیم واقعی و اجرای بدون خطا روی ۴ سناریوی مصنوعی
- `randomize_trade_sequence` → توزیع Max Drawdown روی معاملات واقعی جابه‌جاشده
- `run_perturbation_suite` → ۸ سناریوی cost/risk بدون خطا اجرا شد
- `evaluate_all` / `summarize` (Self Evaluation) → دلایل smart و مرتبط با
  evidence واقعی هر معامله تولید کرد
- `analyze_failures` → دسته‌بندی صحیح زیان‌ها (مثلاً `SIGNAL_CONFLICT` به‌عنوان
  غالب‌ترین الگو در یک اجرا)
- `compare_versions` (V1/V2/V3) → override موقت تنظیمات درست کار کرد و بعد از
  اجرا مقادیر اصلی `config/settings.py` بازگردانده شدند (چک شد)
- `run_challenge` → داوری صرفاً بر اساس Out-of-Sample انجام شد و در اجرای تستی
  یک نسخه‌ی محافظه‌کارتر (V2) را به‌درستی برنده اعلام کرد

مثل قبل، تست روی **صرافی‌های واقعی انجام نشد** (محدودیت شبکه‌ی sandbox). قبل
از اعتماد کامل، حتماً یک اجرای واقعی با `--backtest` روی محیط اصلی پروژه بگیر.
