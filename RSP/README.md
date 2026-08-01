# RSP — Research & Strategy Playground

آزمایشگاه مستقل تحقیق، آزمایش، توسعه، بک‌تست و ارزیابی نسل‌های بعدی موتور
تصمیم‌گیری آرسان. **کاملاً جدا از آرسان اصلی** — هیچ فایلی در `analyzer/`،
`index.html`، `dashboard.html`، یا `data/` آرسان تغییر نکرده است.

## اجرا

```bash
cd arsan.1-main
pip install pandas numpy requests
python -m RSP.main --coin bitcoin              # تحلیل لحظه‌ای + گزارش Explainable
python -m RSP.main --coin bitcoin --backtest   # بک‌تست کامل روی داده‌ی تاریخی
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
| 26 — Experiment Manager | ثبت JSON با ID (`RSP-EXP-NNN`) |
| 30 — Decision Explainability | گزارش انسانی کامل (DECISION/REASON/MISSING/INVALIDATION) |
| 31 — RSP Dashboard | HTML مستقل، آفلاین، جدا از داشبورد آرسان |
| 32 — Final Evaluation | همه‌ی فیلدهای خواسته‌شده در گزارش Explainability موجودند |

### 🟡 پیاده‌سازی جزئی (چارچوب واقعی دارد، ولی ناقص — صادقانه اعلام می‌شود)
| فاز | چه چیزی هست / چه چیزی نیست |
|---|---|
| 20 — Walk Forward | فقط یک بک‌تست پیوسته‌ی بدون نشتی وجود دارد؛ تقسیم صریح Train/Validate/Test و حرکت پنجره‌ای پیاده‌سازی **نشده** |
| 29 — Arsan Comparison | چارچوب مقایسه (`comparison/arsan_vs_rsp.py`) موجود است و متریک‌های RSP را واقعی محاسبه می‌کند؛ اما اجرای خودکار `analyzer/backtest_lab.py` آرسان انجام **نشده** چون امضای ورودی/خروجی آن مستند نبود و حدس‌زدن آن ریسک تولید عدد غلط داشت — عمداً به‌جای عدد جعلی، وضعیت `NOT_AVAILABLE` برمی‌گرداند |

### ❌ طراحی‌شده اما پیاده‌سازی نشده (به‌صراحت، نه چیزی که پنهان شده باشد)
| فاز | دلیل |
|---|---|
| 21 — Anti-Overfitting Lab (In-Sample vs Out-of-Sample) | نیاز به Walk Forward کامل (فاز ۲۰) به‌عنوان پیش‌نیاز دارد |
| 22 — Stress Test (Bull/Bear/Crash presets) | نیاز به دیتاست‌های تاریخی برچسب‌خورده دارد؛ زیرساخت بک‌تست آماده است ولی سناریوهای از‌پیش‌ساخته ساخته نشده |
| 23 — Monte Carlo / Robustness | تصادفی‌سازی توالی معاملات/اسلیپیج/کارمزد پیاده نشده |
| 24 — Self Evaluation Engine | لاگ معاملات (regime/confidence/reason ثبت‌شده) وجود دارد، اما تحلیل «چرا اشتباه شد» بعد از هر معامله ساخته نشده |
| 25 — Failure Analysis | دسته‌بندی شکست‌ها (Bad Entry, Wrong Regime, ...) ساخته نشده |
| 27 — Versioned Strategy Lab (V1/V2/V3) | فقط یک نسخه از موتور تصمیم وجود دارد؛ سیستم نسخه‌بندی و مقایسه نساخته شده |
| 28 — Challenger System | نیاز به Versioned Strategy Lab دارد |
| Liquidity Zones (بخشی از Phase 8) | فقط Support/Resistance ساده از Swing Point پیاده شده |
| Portfolio Engine (پوشه در ساختار هست) | خالی — چون اسپک روی معامله‌ی تکی تمرکز داشت، مدیریت پرتفوی چندکوینه ساخته نشده |

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
