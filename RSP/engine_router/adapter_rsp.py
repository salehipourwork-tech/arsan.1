#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP — engine_router/adapter_rsp.py

wrapper نازک روی RSP.paper_trading.runner.run_one_cycle — هیچ منطقی از RSP
اینجا تکرار/بازنویسی نشده. تنها کاری که این فایل می‌کند: صدا زدن تابع
موجود و شکل‌دادن خروجی به همان فرم مشترکی که adapter_legacy برمی‌گرداند تا
router بتواند دو خروجی را کنار هم بگذارد.

توجه: بر خلاف adapter_legacy (که کاملاً read-only است)، این تابع دقیقاً
همان side effectهای طبیعی و از-قبل-طراحی‌شده‌ی RSP.paper_trading را دارد
(نوشتن در RSP/paper_trading/logs/*_decisions.jsonl و مدیریت پوزیشن کاغذی)
— چون خودِ آن ماژول برای همین هدف (ثبت هر تصمیم برای ارزیابی بعدی) ساخته
شده و اجرای Shadow دقیقاً باید همان رفتار واقعی RSP در تست زنده را ببیند.
هیچ سفارش واقعی یا سرمایه‌ی واقعی درگیر نیست (همان تضمین paper_trading).
"""

from datetime import datetime, timezone
from typing import Any, Dict

from RSP.paper_trading.runner import run_one_cycle


def run_rsp_decision(coin: str, locked_report_path: str = None) -> Dict[str, Any]:
    call_started_at = datetime.now(timezone.utc).isoformat()
    try:
        record = run_one_cycle(coin, locked_report_path=locked_report_path)
        error_reasons = [w for w in (record.get("why") or []) if str(w).startswith("ERROR")]
        if error_reasons:
            return {
                "engine": "rsp", "coin": coin, "call_started_at": call_started_at,
                "error": "; ".join(error_reasons),
            }

        return {
            "engine": "rsp",
            "coin": coin,
            "call_started_at": call_started_at,
            "data_timeframe": "15M (live)",
            "data_freshness_iso": record.get("bar_ts"),
            "source_used": record.get("source_used"),
            "decision": record.get("action"),
            "confidence": record.get("confidence"),
            "reasons": record.get("why"),
            "market_regime": record.get("regime"),
            "risk_plan": record.get("risk_plan"),
            "opened_paper_position": bool(record.get("opened_paper_position")),
            "locked_report_used": record.get("locked_report"),
        }
    except Exception as e:
        return {
            "engine": "rsp", "coin": coin, "call_started_at": call_started_at, "error": str(e),
        }
