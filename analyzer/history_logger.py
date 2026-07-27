"""
analyzer/history_logger.py — نسخه ۳

هر بار که main.py برای یک کوین تصمیم می‌گیره، این ماژول یک رکورد به
data/history.json اضافه می‌کنه. بدون این فایل، امکان سنجش دقت واقعی سیستم یا
بک‌تست وجود نداره (مشکل شماره ۵ و ۷ گزارش وضعیت).

نحوه‌ی استفاده در main.py (داخل حلقه‌ی for coin_id in DEFAULT_COINS، بعد از
decision_result = make_decision(indicators)):

    from history_logger import log_decision
    current_price = coin_snapshot.get("usd", indicators["last_price"])
    log_decision(coin_id, current_price, decision_result)

ساختار هر رکورد:
{
    "id": "bitcoin_2026-07-27T08:00:00+03:30",
    "coin": "bitcoin",
    "timestamp": "2026-07-27T08:00:00+03:30",
    "price": 62000.5,
    "decision": "buy",          ← "buy"/"sell"/"hold"/"uncertain"
    "score": 34.2,
    "agreement_ratio": 0.71,
    "trend_gate_triggered": false,
    "outcome": null,            ← بعداً توسط evaluate_signals.py پر می‌شه
    "outcome_price": null,
    "outcome_checked_at": null
}
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
