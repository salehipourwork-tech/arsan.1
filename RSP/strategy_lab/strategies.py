"""
RSP — strategy_lab/strategies.py  (Phase 14: STRATEGY LIBRARY)

هر استراتژی: Entry Rules, Exit Rules, Risk Rules, Market Regime سازگار،
Invalidation Rules. این‌ها قوانین اعلامی (declarative) هستند که توسط
strategy_lab/selector.py و execution_simulator استفاده می‌شوند.

پیاده‌سازی این نسخه: قوانین به‌صورت متن ساختاریافته + یک تابع `applies`
که بررسی می‌کند آیا شرایط فعلی (رژیم + فیوژن) با استراتژی سازگار است یا نه.
منطق اجرای واقعی (کِی وارد شو/خارج شو با چه قیمتی) در execution_simulator
پیاده می‌شود؛ اینجا فقط تعریف استراتژی است.
"""

from dataclasses import dataclass, field
from typing import List, Callable


@dataclass
class Strategy:
    name: str
    compatible_regimes: List[str]
    entry_rules: List[str]
    exit_rules: List[str]
    risk_rules: List[str]
    invalidation_rules: List[str]

    def applies_to_regime(self, regime: str) -> bool:
        return regime in self.compatible_regimes


STRATEGY_LIBRARY = {
    "trend_following": Strategy(
        name="Trend Following",
        compatible_regimes=["STRONG_UPTREND", "UPTREND", "STRONG_DOWNTREND", "DOWNTREND", "BREAKDOWN"],
        entry_rules=["net_score هم‌جهت با روند و |net_score| > 0.3",
                      "EMA20 در سمت روند نسبت به EMA50 باشد",
                      "ADX >= 20 (روند دارای قدرت باشد)"],
        exit_rules=["عبور EMA20 از EMA50 در خلاف جهت (کراس معکوس)",
                     "رسیدن به Take Profit مبتنی بر ATR"],
        risk_rules=["Stop Loss = 1.5x ATR پشت آخرین Swing",
                     "Risk/Reward حداقل 1.5"],
        invalidation_rules=["CHOCH خلاف جهت معامله", "افت ADX زیر 15 (از دست‌رفتن قدرت روند)"],
    ),
    "momentum": Strategy(
        name="Momentum",
        compatible_regimes=["STRONG_UPTREND", "STRONG_DOWNTREND", "BREAKOUT"],
        entry_rules=["MACD histogram در حال شتاب‌گیری هم‌جهت با روند",
                      "حجم رو به افزایش (momentum_state=ACCELERATION)"],
        exit_rules=["momentum_state به WEAKENING تغییر کند",
                     "واگرایی RSI/OBV ظاهر شود"],
        risk_rules=["Stop Loss تنگ‌تر (1.0x ATR) به‌خاطر ماهیت پرشتاب معامله"],
        invalidation_rules=["ظهور واگرایی نزولی/صعودی در جهت مخالف معامله"],
    ),
    "mean_reversion": Strategy(
        name="Mean Reversion",
        compatible_regimes=["RANGE", "WEAK_UPTREND", "WEAK_DOWNTREND", "LOW_VOLATILITY", "RECOVERY"],
        entry_rules=["قیمت نزدیک باند پایین/بالای Bollinger باشد (بازگشت به میانگین)",
                      "ADX < 20 (نبود روند قوی)",
                      "RSI در ناحیه‌ی افراطی (>70 یا <30) برای ورود خلاف افراط"],
        exit_rules=["بازگشت قیمت به میانگین متحرک (SMA20)"],
        risk_rules=["Stop Loss بیرون از باند Bollinger مقابل"],
        invalidation_rules=["شکست ساختاری (BOS) که Range را باطل کند"],
    ),
    "breakout": Strategy(
        name="Breakout",
        compatible_regimes=["BREAKOUT"],
        entry_rules=["BOS_BULLISH یا BOS_BEARISH تازه رخ‌داده باشد",
                      "حجم Confirmation داشته باشد (VOLUME_TREND=BULLISH هم‌جهت)"],
        exit_rules=["Take Profit مبتنی بر اندازه‌ی رنج شکسته‌شده"],
        risk_rules=["Stop Loss بلافاصله پشت سطح شکسته‌شده"],
        invalidation_rules=["بازگشت قیمت به داخل رنج ظرف مدت کوتاه (Fake Breakout)"],
    ),
    "pullback": Strategy(
        name="Pullback",
        compatible_regimes=["UPTREND", "WEAK_UPTREND", "DOWNTREND", "WEAK_DOWNTREND"],
        entry_rules=["اصلاح موقت خلاف روند اصلی، سپس بازگشت به جهت روند",
                      "قیمت به EMA20/50 پولبک بزند و از آن حمایت/مقاومت بگیرد"],
        exit_rules=["رسیدن به سقف/کف قبلی روند"],
        risk_rules=["Stop Loss پشت نقطه‌ی پولبک"],
        invalidation_rules=["شکست EMA50 (پولبک به روند تبدیل به تغییر روند شود)"],
    ),
    "reversal": Strategy(
        name="Reversal",
        compatible_regimes=["RECOVERY"],
        entry_rules=["CHOCH_BULLISH بعد از روند نزولی طولانی",
                      "واگرایی صعودی RSI/OBV تایید باشد"],
        exit_rules=["رسیدن به اولین مقاومت ساختاری مهم"],
        risk_rules=["Stop Loss زیر کف اخیر (Swing Low قبل از بازگشت)"],
        invalidation_rules=["ثبت Lower Low جدید (نبود بازگشت واقعی)"],
    ),
}


def get_strategy(name: str) -> Strategy:
    return STRATEGY_LIBRARY[name]
