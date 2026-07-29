"""
آرسان - پرتفوی فرضی سراسری (نسخه ۴، دسته D)

هشدار صادقانه‌ی مهم: گزارش وضعیت دسته D رو این‌طور توصیف کرده بود: «کاربر با
پول فرضی دنبال سیگنال‌ها معامله کنه، رتبه‌بندی بشه». اون بخش «رتبه‌بندی بین
کاربران» ذاتاً نیاز به حساب کاربری و یه بک‌اند واقعی (نه فقط GitHub Pages +
Actions) داره — یعنی یه پروژه‌ی جدا با معماری متفاوت، دقیقاً همون‌طور که خود
گزارش هم گفته بود «پروژه‌ی جدا در حد خودشون».

چیزی که *در همین معماری فعلی* (بدون بک‏‌اند، بدون حساب کاربری) واقعاً قابل‌ساختنه:
یه پرتفوی فرضی *سراسری* — یعنی «اگه یکی از روز اول همه‌ی سیگنال‌های buy/sell
سیستم رو با مبلغ ثابت دنبال می‌کرد، الان چقدر سود/ضرر داشت؟». این دقیقاً همون
داده‌ای رو که history.json و evaluate_signals.py از قبل جمع می‌کنن استفاده
می‌کنه، فقط به‌جای درصد دقت (0.5% معیار evaluate_signals.py)، سود/ضرر واقعی
دلاری رو محاسبه می‌کنه. این می‌تونه در صفحه‌ی شفافیت به‌عنوان یه معیار دومِ
اعتمادسازی کنار درصد دقت نمایش داده بشه.

نکته: این پرتفوی صرفاً محاسباتیه، هیچ معامله‌ی واقعی انجام نمی‌شه (کاملاً هم‌سو
با هدف اصلی پروژه: «دستیار تحلیل، نه ربات معامله‌گر»).
"""

import json
import os
from datetime import datetime, timedelta

HISTORY_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "history.json")
PORTFOLIO_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "portfolio.json")

# مبلغ فرضی که هر بار روی هر سیگنال buy/sell "سرمایه‌گذاری" می‌شه
POSITION_SIZE_USD = 100.0
# مدت نگه‌داشتن هر پوزیشن فرضی، هم‌راستا با پنجره‌ی ارزیابی evaluate_signals.py
HOLD_HOURS = 24


def _load_history():
    if not os.path.exists(HISTORY_PATH):
        return []
    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def build_portfolio_summary():
    """
    برای هر رکورد history.json که outcome مشخص داره (یعنی ۲۴ ساعت گذشته)، فرض
    می‌کنه POSITION_SIZE_USD روی اون سیگنال گذاشته شده و P&L واقعی رو با قیمت
    outcome_price (که evaluate_signals.py قبلاً ذخیره کرده) حساب می‌کنه.

    برای buy: سود اگه قیمت بالا رفته باشه.
    برای sell: این یه پوزیشن فرضیِ "short" حساب می‌شه — سود اگه قیمت پایین اومده.
    """
    records = _load_history()
    evaluated = [r for r in records if r.get("outcome") in ("correct", "wrong") and r.get("decision") in ("buy", "sell")]

    trades = []
    total_pnl = 0.0
    for r in evaluated:
        entry_price = r["price"]
        exit_price = r.get("outcome_price")
        if not entry_price or not exit_price:
            continue
        change_ratio = (exit_price - entry_price) / entry_price
        pnl = POSITION_SIZE_USD * change_ratio if r["decision"] == "buy" else POSITION_SIZE_USD * -change_ratio
        total_pnl += pnl
        trades.append({
            "coin": r["coin"], "decision": r["decision"],
            "entry_price": entry_price, "exit_price": exit_price,
            "pnl_usd": round(pnl, 2), "timestamp": r["timestamp"],
        })

    total_invested = POSITION_SIZE_USD * len(trades)
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "position_size_usd": POSITION_SIZE_USD,
        "hold_hours": HOLD_HOURS,
        "total_trades": len(trades),
        "total_invested_usd": round(total_invested, 2),
        "total_pnl_usd": round(total_pnl, 2),
        "return_percent": round(total_pnl / total_invested * 100, 2) if total_invested else None,
        "note": (
            "این یک شبیه‌سازی فرضی سراسری است، نه معامله‌ی واقعی و نه پرتفوی شخصی هر کاربر — "
            "صرفاً نشون می‌ده اگه کسی همه‌ی سیگنال‌های سیستم رو دنبال می‌کرد نتیجه چی می‌شد."
            if trades else
            "هنوز هیچ معامله‌ای برای شبیه‌سازی وجود نداره — این بخش به‌محض ارزیابی اولین "
            "سیگنال‌های خرید/فروش (۲۴ ساعت بعد از صدور) پر می‌شه."
        ),
        "recent_trades": trades[-20:],  # فقط ۲۰ تای آخر برای نمایش سبک در دفتر جلویی
    }


def run():
    summary = build_portfolio_summary()
    with open(PORTFOLIO_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    return summary


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
