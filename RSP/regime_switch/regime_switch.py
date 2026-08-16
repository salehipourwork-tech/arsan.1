#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP Regime Switch v1.0
بر اساس نتایج Audit 90 روزه 15M:
- هر اندیکاتور فقط در رژیم "خانه" خودش فعال است
- HIGH_VOLATILITY = هیچ‌کدام مجاز نیستند (ریسک بیش از حد)
"""

from RSP.market_regime.regime_engine import detect_regime

# ───────────────────────────────────────────────
# نقشهٔ مجوز اندیکاتورها بر اساس رژیم (دادهٔ Audit)
# ───────────────────────────────────────────────
REGIME_INDICATOR_MAP = {
    "STRONG_UPTREND":   ["EMA_CROSS_20_50"],           # فقط EMA (خودش کم‌سیگنال)
    "UPTREND":          ["EMA_CROSS_20_50", "MACD_HIST"],  # MACD در uptrend PF=0.881
    "RANGE":            ["RSI_MR_30_70", "BB_MR"],     # کم‌ضررترین‌ها در RANGE
    "DOWNTREND":        ["BB_MR", "RSI_MR_30_70"],     # BB در downtrend PF=0.744
    "STRONG_DOWNTREND": ["BB_MR"],                      # فقط BB
    "HIGH_VOLATILITY":  [],                              # اصلاً وارد نشو
}

# confidence پایه برای هر رژیم (هرچی کمتر = تردید بیشتر)
REGIME_BASE_CONFIDENCE = {
    "STRONG_UPTREND":   0.85,
    "UPTREND":          0.75,
    "RANGE":            0.45,  # RANGE پرریسک‌ترین
    "DOWNTREND":        0.55,
    "STRONG_DOWNTREND": 0.60,
    "HIGH_VOLATILITY":  0.0,
}


def get_allowed_indicators(regime):
    """لیست اندیکاتورهای مجاز برای یک رژیم."""
    return REGIME_INDICATOR_MAP.get(regime, [])


def filter_signals_by_regime(raw_signals, regime):
    """
    raw_signals: dict {indicator_name: signal_str/None}
    خروجی: dict فیلترشده (فقط اندیکاتورهای مجاز که سیگنال غیرNone دارند)
    """
    allowed = set(get_allowed_indicators(regime))
    filtered = {}
    for ind, sig in raw_signals.items():
        if ind in allowed and sig is not None:
            filtered[ind] = sig
    return filtered


def is_trade_allowed(regime, signal_count):
    """
    فیلتر سخت‌گیرانه RANGE:
    در RANGE حداقل ۳ اندیکاتور باید موافق باشند.
    """
    if regime == "HIGH_VOLATILITY":
        return False, "High volatility — no trade"
    if regime == "RANGE" and signal_count < 3:
        return False, f"RANGE with only {signal_count} agreements — need >=3"
    return True, "OK"


def get_regime_weights(regime):
    """
    وزن‌های پویا بر اساس رژیم.
    هرچه اندیکاتور کمتر = وزن بالاتر (جمع‌کل = 1.0)
    """
    allowed = get_allowed_indicators(regime)
    if not allowed:
        return {}
    w = 1.0 / len(allowed)
    return {ind: round(w, 3) for ind in allowed}
