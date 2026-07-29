"""
analyzer/history_logger.py — نسخه ۴

تغییر نسبت به نسخه ۳: یک فیلد جدید "factors" به هر رکورد اضافه شده — همون
dict امتیاز هر شاخص که decision.py برمی‌گردونه (مثلاً {"rsi": 1.2, "macd": -0.4, ...}).

چرا لازم بود: optimize_weights.py (دسته C، وزن‌دهی پویا) برای اینکه بفهمه هر
شاخص چقدر واقعاً «قابل‌اعتماد» بوده، باید بدونه تو لحظه‌ی صدور هر سیگنال، هر
شاخص چه امتیازی داشته — این اطلاعات قبلاً هیچ‌جا ذخیره نمی‌شد، پس اون اسکریپت
همیشه insufficient_data می‌داد حتی اگه ماه‌ها از history.json داده جمع می‌شد.

بقیه‌ی فایل کاملاً بدون تغییره — همون منطق پاک‌سازی MAX_HISTORY_DAYS، همون
امضای تابع log_decision(coin_id, price, decision_result, timestamp=None).
هیچ چیزی برای main.py یا صدا زدن این تابع عوض نشده.
"""
import json
import os
from datetime import datetime, timedelta

HISTORY_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "history.json")
MAX_HISTORY_DAYS = 120  # چند روز تاریخچه نگه داشته بشه قبل از پاک‌سازی خودکار


def _load_history():
    if not os.path.exists(HISTORY_PATH):
        return []
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def _save_history(records):
    os.makedirs(os.path.dirname(HISTORY_PATH), exist_ok=True)
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def log_decision(coin_id, price, decision_result, timestamp=None):
    ts = timestamp or datetime.now().astimezone().isoformat(timespec="seconds")
    record = {
        "id": f"{coin_id}_{ts}",
        "coin": coin_id,
        "timestamp": ts,
        "price": price,
        "decision": decision_result["decision"],
        "score": decision_result["score"],
        "agreement_ratio": decision_result.get("agreement_ratio"),
        "trend_gate_triggered": decision_result.get("trend_gate_triggered", False),
        "factors": decision_result.get("factors", {}),  # جدید در نسخه ۴ — برای optimize_weights.py
        "outcome": None,
        "outcome_price": None,
        "outcome_checked_at": None,
    }
    records = _load_history()
    records.append(record)
    # پاک‌سازی رکوردهای خیلی قدیمی تا فایل خیلی بزرگ نشه
    cutoff = datetime.now().astimezone() - timedelta(days=MAX_HISTORY_DAYS)
    cleaned = []
    for r in records:
        try:
            r_time = datetime.fromisoformat(r["timestamp"])
        except (ValueError, KeyError):
            cleaned.append(r)
            continue
        if r_time >= cutoff:
            cleaned.append(r)
    _save_history(cleaned)
