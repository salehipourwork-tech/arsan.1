"""
analyzer/evaluate_signals.py — نسخه ۳

بعد از EVALUATION_HOURS ساعت از هر سیگنال "buy"/"sell"، این اسکریپت قیمت
واقعی الان رو (با همون تابع fetch_data.get_current_snapshot که در main.py هم
استفاده می‌شه) می‌گیره و مشخص می‌کنه سیگنال درست بوده یا نه. نتیجه رو به
data/history.json برمی‌گردونه و یه خلاصه‌ی آماری در data/accuracy_summary.json
می‌سازه (که داشبورد می‌تونه ازش برای نمایش «نرخ موفقیت واقعی سیستم» استفاده کنه).

این اسکریپت رو می‌تونی هر بار در انتهای run_analysis() در main.py هم صدا بزنی
(هزینه‌ی اضافه‌ای نداره چون خودش فقط رکوردهای رسیده‌به‌موعد رو چک می‌کنه)، یا
به‌عنوان یک step جدا در ورک‌فلوی گیت‌هاب اکشن اجرا کنی.
"""

import json
import os
from datetime import datetime, timedelta

from fetch_data import get_current_snapshot

HISTORY_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "history.json")
SUMMARY_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "accuracy_summary.json")

EVALUATION_HOURS = 24
MIN_MOVE_PERCENT = 0.5  # حداقل درصد حرکت قیمت تا سیگنال «درست» حساب بشه


def _load_history():
    if not os.path.exists(HISTORY_PATH):
        return []
    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_history(records):
    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def evaluate_pending_signals():
    records = _load_history()
    now = datetime.now().astimezone()

    pending = []
    for r in records:
        if r["outcome"] is not None or r["decision"] not in ("buy", "sell"):
            continue
        try:
            signal_time = datetime.fromisoformat(r["timestamp"])
        except ValueError:
            continue
        if now - signal_time >= timedelta(hours=EVALUATION_HOURS):
            pending.append(r)

    if not pending:
        summary = _build_summary(records)
        with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        return {"updated_records": 0, "summary": summary}

    coin_ids = sorted({r["coin"] for r in pending})
    try:
        snapshot = get_current_snapshot(coin_ids)  # یک درخواست برای همه‌ی کوین‌های در انتظار
    except Exception as exc:
        print(f"[evaluate_signals] نتونستم قیمت فعلی رو بگیرم: {exc}")
        return {"updated_records": 0, "summary": None}

    updated = 0
    for r in pending:
        current_price = snapshot.get(r["coin"], {}).get("usd")
        if current_price is None:
            continue  # این کوین رو رد کن، دفعه‌ی بعد دوباره تلاش می‌شه

        change_percent = (current_price - r["price"]) / r["price"] * 100
        if r["decision"] == "buy":
            correct = change_percent >= MIN_MOVE_PERCENT
        else:  # sell
            correct = change_percent <= -MIN_MOVE_PERCENT

        r["outcome"] = "correct" if correct else "wrong"
        r["outcome_price"] = current_price
        r["outcome_checked_at"] = now.isoformat(timespec="seconds")
        updated += 1

    _save_history(records)
    summary = _build_summary(records)
    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return {"updated_records": updated, "summary": summary}


def _build_summary(records):
    evaluated = [r for r in records if r["outcome"] is not None]
    by_decision = {}
    for decision in ("buy", "sell"):
        subset = [r for r in evaluated if r["decision"] == decision]
        correct = sum(1 for r in subset if r["outcome"] == "correct")
        by_decision[decision] = {
            "total": len(subset),
            "correct": correct,
            "accuracy_percent": round(correct / len(subset) * 100, 1) if subset else None,
        }

    total_correct = sum(v["correct"] for v in by_decision.values())
    total_count = sum(v["total"] for v in by_decision.values())

    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "overall": {
            "total": total_count,
            "correct": total_correct,
            "accuracy_percent": round(total_correct / total_count * 100, 1) if total_count else None,
        },
        "by_decision": by_decision,
    }


if __name__ == "__main__":
    result = evaluate_pending_signals()
    print(json.dumps(result, ensure_ascii=False, indent=2))
