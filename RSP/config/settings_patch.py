
# =============================================================================
# PROFITABILITY FIXES — Added 2026-08-15
# Target: RR=2.5, Regime-Aware Rules, A+ Filter, TRX Blacklist
# =============================================================================

# --- FIX 1: Real RR=2.5 (TP = 2.5 × SL) ---
# قبلاً TAKE_PROFIT_RR_TARGET=2.0 بود ولی exit logic آن را رعایت نمی‌کرد.
# حالا exit manager این را به‌صورت mandatory enforce می‌کند.
RR_TARGET = 2.5
SL_ATR_MULTIPLIER = 1.5          # SL تنگ‌تر → TP نزدیک‌تر → hit rate بالاتر
TP_ATR_MULTIPLIER = 3.75         # TP = 2.5 × SL = 2.5 × 1.5 = 3.75 ATR
MIN_OPPORTUNITY_SCORE_FOR_TRADE = 75.0  # A+ filter: فقط setup‌های قوی
TRX_BLACKLIST = ["tron", "TRX"]   # TRX هیچ‌وقت سودآور نشد → حذف

# --- FIX 2: Regime-Aware Rule Activation ---
# رژیم‌های تمیز (Strong Uptrend/Downtrend) → MR rules خاموش
# RANGE/Weak → همه‌ی rules فعال
REGIME_RULE_OVERRIDES = {
    "STRONG_UPTREND": {
        "disable": ["R14", "R15", "R16"],  # MR rules خاموش
        "enable": ["R17", "R18"],           # فقط TF rules
        "note": "Trend clean — no mean reversion"
    },
    "STRONG_DOWNTREND": {
        "disable": ["R14", "R15", "R16"],
        "enable": ["R17", "R18"],
        "note": "Trend clean — no mean reversion"
    },
    "RANGE": {
        "disable": ["R17", "R18"],          # TF rules خاموش
        "enable": ["R14", "R15", "R16"],     # فقط MR rules
        "note": "Range — mean reversion only"
    },
    "UPTREND": {
        "disable": [],
        "enable": [],
        "note": "Mixed — all rules active"
    },
    "DOWNTREND": {
        "disable": [],
        "enable": [],
        "note": "Mixed — all rules active"
    },
}

# --- FIX 3: Opportunity Score A+ Filter ---
# قبلاً FUZZY_OPPORTUNITY_THRESHOLD=50.0 بود → خیلی کم
# حالا 75.0 → فقط setup‌های A+ (top 25%)
FUZZY_OPPORTUNITY_THRESHOLD = 75.0
FUZZY_ADAPTIVE_OPPORTUNITY_PERCENTILE = 0.75  # top 25% of coin's own history

# --- FIX 4: Exit Asymmetry Fix ---
# قبلاً CONSERVATIVE_SL_TP_SAME_CANDLE="SL_FIRST" باعث می‌شد
# حتی وقتی TP قبل از SL hit می‌شد، SL ثبت بشه.
# حالا: اگر TP قبل از SL (بر اساس % مسیر کندل)، TP برنده است.
CONSERVATIVE_SL_TP_SAME_CANDLE = "PROPORTIONAL"  # "SL_FIRST" | "TP_FIRST" | "PROPORTIONAL"

# --- FIX 5: Fee/Slippage Reality Check ---
# با RR=2.5 و WR=35%، برای سودآوری:
# Expected = 0.35 × 2.5 - 0.65 × 1 = 0.875 - 0.65 = +0.225 → سودآور
# ولی fee+slippage ~0.15% per trade → با 100 trade = 15%
# پس باید تریدها کمتر و بزرگ‌تر باشن.
MIN_TRADE_DISTANCE_BARS = 3  # حداقل 3 کندل بین تریدها (جلوگیری از over-trading)
