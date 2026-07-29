"""
آرسان - آشکارساز هشدار حجم/اخبار غیرعادی (نسخه ۴، دسته B)

هدف: جدا از چرخه‌ی معمولی ۳۰ دقیقه‌ای main.py، یه اسکریپت سبک که می‌تونه با
فاصله‌ی زمانی کوتاه‌تر (مثلاً هر ۵-۱۰ دقیقه) در یک ورک‌فلوی جدای گیت‌هاب اکشن
اجرا بشه و فقط دنبال «تغییرات ناگهانی» بگرده — نه یه تحلیل کامل جدید.

دو نوع هشدار:
۱) جهش حجم: وقتی حجم معاملات ۲۴ ساعت اخیر به‌طور غیرعادی (نسبت به میانگین
   چند روز اخیر) بالا رفته باشه.
۲) جهش خبری: وقتی تعداد اخبار مرتبط در بازه‌ی کوتاه (مثلاً ۲ ساعت) به‌طور
   غیرعادی زیاد شده باشه (نشونه‌ی یه رویداد مهم).

نکته‌ی مهم درباره‌ی وابستگی: این فایل فرض می‌کنه از analyzer/fetch_data.py دو
تابع در دسترسه: get_current_snapshot(coin_ids) که در evaluate_signals.py هم
استفاده شده، و یه تابع برای گرفتن حجم ۲۴ ساعته (فرض شده به نام
get_volume_snapshot؛ اگه اسم واقعیش فرق داره، فقط همین import رو اصلاح کن —
بقیه‌ی منطق دست‌نخورده می‌مونه). هدف اینجا نشون‌دادن منطق و ساختار داده‌س، نه
حدس‌زدن دقیق API داخلی fetch_data.py که در اختیارم نبود.

خروجی: data/alerts.json — یه لیست از هشدارهای فعال، که index.html می‌تونه
به‌صورت یه نوار هشدار بالای صفحه نمایش بده (جدا از وضعیت تحلیل معمولی).
"""

import json
import os
from datetime import datetime, timedelta

try:
    from fetch_data import get_current_snapshot, get_volume_snapshot
except ImportError:
    get_current_snapshot = None
    get_volume_snapshot = None

ALERTS_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "alerts.json")
HISTORY_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "volume_history.json")

# نسبت حجم فعلی به میانگین ۷ روز اخیر که بالاترش «جهش» حساب می‌شه
VOLUME_SPIKE_RATIO = 2.5
# چند رکورد آخر (هر کدوم یه نمونه‌گیری) برای محاسبه‌ی میانگین نگه داریم
VOLUME_HISTORY_WINDOW = 7 * 24 * 2  # فرضاً هر ۵ دقیقه یه نمونه، ~۷ روز

# جهش خبری: تعداد خبر در ۲ ساعت اخیر که بالاترش هشدار بده
NEWS_SPIKE_COUNT = 5


def _load_json(path, default):
    if not os.path.exists(path):
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _update_volume_history(coin_id, volume_24h, history):
    history.setdefault(coin_id, [])
    history[coin_id].append({"t": datetime.now().astimezone().isoformat(timespec="seconds"), "v": volume_24h})
    history[coin_id] = history[coin_id][-VOLUME_HISTORY_WINDOW:]
    return history


def _average_volume(records):
    if len(records) < 5:
        return None  # داده‌ی کافی برای مقایسه نیست
    values = [r["v"] for r in records[:-1]]  # به‌جز آخرین نمونه
    return sum(values) / len(values)


def check_volume_spikes(coin_ids):
    """
    خروجی: لیستی از dict های {"coin", "type": "volume_spike", "ratio", "message"}
    اگه fetch_data.get_volume_snapshot در دسترس نباشه، لیست خالی برمی‌گردونه
    (بدون کرش کردن ورک‌فلو).
    """
    if get_volume_snapshot is None:
        return []

    history = _load_json(HISTORY_PATH, {})
    alerts = []
    try:
        volumes = get_volume_snapshot(coin_ids)  # فرض: {"bitcoin": 12345678.0, ...}
    except Exception as exc:
        print(f"[volume_news_alert] نتونستم حجم رو بگیرم: {exc}")
        return []

    for coin_id, vol in volumes.items():
        history = _update_volume_history(coin_id, vol, history)
        avg = _average_volume(history[coin_id])
        if avg and avg > 0:
            ratio = vol / avg
            if ratio >= VOLUME_SPIKE_RATIO:
                alerts.append({
                    "coin": coin_id,
                    "type": "volume_spike",
                    "ratio": round(ratio, 2),
                    "message": f"حجم معاملات {coin_id} حدود {ratio:.1f} برابر میانگین معمول است.",
                })

    _save_json(HISTORY_PATH, history)
    return alerts


def check_news_spikes(recent_headlines_by_coin):
    """
    recent_headlines_by_coin: {"bitcoin": [{"title":..., "published_at": iso_str}, ...], ...}
    این تابع مستقل از منبع خبره — می‌تونه از analyzer/news_sentiment.py صدا زده بشه
    (همون RSS محلی که در گزارش وضعیت اومده) بدون نیاز به تغییر اون فایل.
    """
    alerts = []
    now = datetime.now().astimezone()
    for coin_id, headlines in recent_headlines_by_coin.items():
        recent = []
        for h in headlines:
            try:
                pub = datetime.fromisoformat(h["published_at"])
            except (KeyError, ValueError):
                continue
            if now - pub <= timedelta(hours=2):
                recent.append(h)
        if len(recent) >= NEWS_SPIKE_COUNT:
            alerts.append({
                "coin": coin_id,
                "type": "news_spike",
                "count": len(recent),
                "message": f"{len(recent)} خبر مرتبط با {coin_id} در ۲ ساعت اخیر منتشر شده — بیشتر از حد معمول.",
            })
    return alerts


def run(coin_ids, recent_headlines_by_coin=None):
    """
    نقطه‌ی ورود این ماژول. main.py یا یه ورک‌فلوی جدا می‌تونه این تابع رو صدا بزنه:

        from volume_news_alert import run
        run(coin_ids=["bitcoin", "ethereum", ...])

    خروجی هم برگردونده می‌شه و هم در data/alerts.json ذخیره می‌شه.
    هر هشدار فقط ۳ ساعت معتبر حساب می‌شه (expires_at) تا نوار هشدار در
    index.html قدیمی/گمراه‌کننده نمونه.
    """
    alerts = check_volume_spikes(coin_ids)
    if recent_headlines_by_coin:
        alerts += check_news_spikes(recent_headlines_by_coin)

    now = datetime.now().astimezone()
    for a in alerts:
        a["generated_at"] = now.isoformat(timespec="seconds")
        a["expires_at"] = (now + timedelta(hours=3)).isoformat(timespec="seconds")

    _save_json(ALERTS_PATH, {"generated_at": now.isoformat(timespec="seconds"), "alerts": alerts})
    return alerts


if __name__ == "__main__":
    # اجرای مستقل برای تست دستی؛ در ورک‌فلوی واقعی coin_ids باید از همون لیست
    # کوین‌های اصلی main.py بیاد.
    result = run(coin_ids=["bitcoin", "ethereum"])
    print(json.dumps(result, ensure_ascii=False, indent=2))
