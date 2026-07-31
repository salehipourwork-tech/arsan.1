"""
analyzer/history_logger.py — نسخه ۵

تغییر نسبت به نسخه ۴: فیکس باگ مهم — جلوگیری از ثبت تکراری روزانه.

مشکل کشف‌شده: analyze.yml هر ۳۰ دقیقه اجرا می‌شه، ولی fetch_data.py داده رو
روزانه می‌گیره — یعنی توی یه روز تقویمی، ورودی‌های decision.py عوض نمی‌شن و
دقیقاً همون تصمیم هر بار دوباره ساخته می‌شه. log_decision قبلاً بدون هیچ چکی
هر بار یه رکورد جدید اضافه می‌کرد، پس یه تصمیم واحد می‌تونست ده‌ها بار در یه
روز ثبت بشه. این باعث می‌شد آمار «شفافیت عملکرد» و «پرتفوی فرضی» به‌شدت مخدوش
بشه (یه سیگنال اشتباه، انگار ده‌ها سیگنال اشتباه به نظر می‌رسید).

راه‌حل: قبل از ثبت، چک می‌کنیم که آیا امروز (بر اساس تاریخ، نه ساعت دقیق) قبلاً
برای همین کوین رکوردی ثبت شده یا نه. اگه شده، رکورد جدید اضافه نمی‌شه.
این یعنی حداکثر یک رکورد به‌ازای هر کوین در هر روز — دقیقاً هم‌راستا با قانون
ارزیابی «۲۴ ساعت بعد» که از اول همه‌جای پروژه (evaluate_signals.py,
backtest_lab.py) استفاده می‌شه.

بقیه‌ی فایل بدون تغییر — همون منطق پاک‌سازی MAX_HISTORY_DAYS، همون امضای تابع
log_decision(coin_id, price, decision_result, timestamp=None). فقط این‌بار
تابع ممکنه هیچ کاری نکنه (به‌جای همیشه append کردن) اگه امروز قبلاً ثبت شده.
هیچ چیزی برای main.py یا نحوه‌ی صدا زدن این تابع عوض نشده.
"""
import json
import os
from datetime import datetime, timedelta

HISTORY_PATH = os.path.join(os.path.dirname(file), "..", "data", "history.json")
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


def _already_logged_today(records, coin_id, ts):
    """
    آیا امروز (فقط بخش تاریخ از ISO timestamp، بدون ساعت) قبلاً برای این کوین
    رکوردی ثبت شده؟ اگه بله، دیگه لازم نیست دوباره ثبت بشه — چون داده‌ی ورودی
    (fetch_data.py) روزانه‌ست، توی یه روز چیزی عوض نمی‌شه که بخوایم دوباره
    ثبتش کنیم.
    """
    day = ts[:10]  # مثلاً "2026-07-31" از "2026-07-31T14:30:00+03:30"
    return any(
        r.get("coin") == coin_id and str(r.get("timestamp", ""))[:10] == day
        for r in records
    )


def log_decision(coin_id, price, decision_result, timestamp=None):
    ts = timestamp or datetime.now().astimezone().isoformat(timespec="seconds")
    records = _load_history()

    if _already_logged_today(records, coin_id, ts):
        # امروز قبلاً برای این کوین یه تصمیم ثبت شده — چون داده روزانه‌ست،
        # این اجرا هم همون تصمیم رو دوباره می‌ساخت. از ثبت تکراری جلوگیری می‌کنیم.
        return

    record = {
        "id": f"{coin_id}_{ts}",
        "coin": coin_id,
        "timestamp": ts,
        "price": price,
        "decision": decision_result["decision"],
        "score": decision_result["score"],
        "agreement_ratio": decision_result.get("agreement_ratio"),
        "trend_gate_triggered": decision_result.get("trend_gate_triggered", False),
        "factors": decision_result.get("factors", {}),  # از نسخه ۴ — برای optimize_weights.py
        "market_regime": decision_result.get("market_regime"),  # از نسخه ۵ (چت دیگه) — تحلیل به‌تفکیک رژیم
        "outcome": None,
        "outcome_price": None,
        "outcome_checked_at": None,
    }
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
