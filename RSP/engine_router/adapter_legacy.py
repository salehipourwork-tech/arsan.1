#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP — engine_router/adapter_legacy.py

فراخوانی read-only موتور فعلی آرسان (analyzer/) برای یک کوین، بدون هیچ‌کدام
از side effectهای analyzer/main.py (بدون نوشتن data/analysis.json یا
data/history.json، بدون git commit، بدون portfolio/alerts). فقط سه مرحله‌ی
خالص محاسباتی صدا زده می‌شوند: fetch → indicators (+ market_regime) → decision.

هیچ منطقی از analyzer/ اینجا کپی/بازنویسی نشده — فقط همان توابع موجود صدا
زده می‌شوند.

نکته‌ی import: فایل‌های analyzer/ (مثل decision.py که `from regime_weights
import ...` می‌زند) با import‌های bare نوشته شده‌اند و فقط وقتی کار می‌کنند
که خودِ پوشه‌ی analyzer/ روی sys.path باشد — دقیقاً همان‌طور که
`python analyzer/main.py` به‌صورت خودکار این کار را می‌کند. اینجا این
مسیر فقط برای مدت یک import scoped اضافه و بلافاصله برداشته می‌شود؛ هیچ
merge دائمی‌ای با namespace اصلی RSP رخ نمی‌دهد.

news_sentiment عمداً صدا زده نمی‌شود (مدل HF سنگین است و شبکه/سرعت شادو را
غیرقابل‌پیش‌بینی می‌کند) — به‌جایش neutral=0.0 پاس داده می‌شود و این صراحتاً
در خروجی (`news_sentiment_used`) ثبت می‌شود تا مقایسه صادقانه بماند، نه
سایلنت.
"""

import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict

ANALYZER_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "analyzer",
)

_legacy_modules = None  # lazy، فقط یک‌بار import می‌شود


def _get_legacy_modules():
    """Import کردن fetch_data/indicators/decision/market_regime به‌صورت
    bare-name، با اضافه‌کردن موقت analyzer/ به sys.path — بلافاصله بعد از
    import، مسیر برداشته می‌شود (چه موفق چه ناموفق)."""
    global _legacy_modules
    if _legacy_modules is not None:
        return _legacy_modules

    added = False
    if ANALYZER_DIR not in sys.path:
        sys.path.insert(0, ANALYZER_DIR)
        added = True
    try:
        import fetch_data as legacy_fetch_data
        import indicators as legacy_indicators
        import decision as legacy_decision
        import market_regime as legacy_market_regime
    finally:
        if added:
            sys.path.remove(ANALYZER_DIR)

    _legacy_modules = {
        "fetch_data": legacy_fetch_data,
        "indicators": legacy_indicators,
        "decision": legacy_decision,
        "market_regime": legacy_market_regime,
    }
    return _legacy_modules


def run_legacy_decision(coin: str, days: int = 100) -> Dict[str, Any]:
    """
    یک تصمیم legacy برای coin برمی‌گرداند — دقیقاً همان مسیر محاسباتی
    analyzer/main.py برای هر کوین (بدون sentiment، بدون فایل‌نویسی).
    خطا را قورت نمی‌دهد؛ اگر چیزی شکست بخورد، در خروجی با
    engine="legacy", error=... ثبت می‌شود تا در لاگ مقایسه‌ای صادقانه بماند.
    """
    call_started_at = datetime.now(timezone.utc).isoformat()
    try:
        m = _get_legacy_modules()
        chart = m["fetch_data"].get_market_chart(coin, days=days)
        prices = chart.get("prices", [])
        if not prices:
            return {
                "engine": "legacy", "coin": coin, "error": "empty price series from CoinGecko",
                "call_started_at": call_started_at,
            }

        data_ts_ms = prices[-1][0]
        data_freshness_iso = datetime.fromtimestamp(data_ts_ms / 1000, tz=timezone.utc).isoformat()
        current_price = float(prices[-1][1])

        ind = m["indicators"].calculate_all_indicators(chart)
        regime = m["market_regime"].calculate_market_regime(ind, prices)
        result = m["decision"].make_decision(
            ind, news_sentiment=0.0, btc_trend_diff_pct=None,
            risk_profile="balanced", market_regime=regime.get("regime"),
        )

        return {
            "engine": "legacy",
            "coin": coin,
            "call_started_at": call_started_at,
            "data_timeframe": "1D (daily, days=100 lookback)",
            "data_freshness_iso": data_freshness_iso,
            "current_price": current_price,
            "decision": result.get("decision"),
            "score_percent": result.get("score_percent"),
            "agreement_ratio": result.get("agreement_ratio"),
            "reasons": result.get("reasons"),
            "market_regime": regime.get("regime"),
            "market_regime_label_fa": regime.get("label_fa"),
            "news_sentiment_used": "neutral_0.0_skipped_for_shadow_speed",
        }
    except Exception as e:
        return {
            "engine": "legacy", "coin": coin, "error": str(e),
            "call_started_at": call_started_at,
        }
