"""
آرسان - پیشنهاددهنده‌ی وزن‌دهی پویا (نسخه ۴، دسته C)

هشدار صادقانه‌ی مهم: این بخش از گزارش وضعیت («وزن‌دهی پویا بر اساس عملکرد واقعی
هر شاخص») ذاتاً به هفته‌ها داده‌ی واقعی از history.json نیاز داره. الان (طبق
accuracy_summary.json که فرستادی) total=0 است — یعنی هنوز هیچ سیگنالی ارزیابی
نشده. پس این اسکریپت:
  - کاملاً کار می‌کنه و منطقش کامله
  - ولی عمداً به‌جای اینکه با داده‌ی کم یه عدد بی‌معنی دربیاره، اگه نمونه‌ها
    کمتر از MIN_SAMPLES_PER_FACTOR باشن، برای اون شاخص می‌گه "insufficient_data"
  - هیچ‌وقت خودش weights.json رو overwrite نمی‌کنه — فقط یه پیشنهاد در
    data/weights_suggestion.json می‌نویسه که خودت (انسان) باید بررسی و تایید کنی
    قبل از اینکه دستی جایگزین weights.json بشه. تغییر خودکار وزن‌ها بدون نظارت
    انسانی روی سیستمی که به تصمیم مالی مربوطه، ریسکیه.

منطق: برای هر شاخص (کلید base_scores/factors که در decision.py ذخیره می‌شه)،
بین رکوردهای history.json که outcome مشخص دارن (correct/wrong)، بررسی می‌کنه
وقتی اون شاخص با علامت تصمیم نهایی هم‌جهت بوده (agree=True)، سیگنال چند درصد
مواقع "correct" از آب دراومده در مقابل وقتی مخالف بوده (agree=False). اگه
اختلاف معناداری باشه، پیشنهاد افزایش/کاهش وزن می‌ده.

نکته: این اسکریپت فرض می‌کنه هر رکورد history.json شامل فیلد "factors" است
(همون dict که decision.py برمی‌گردونه) — اگه history_logger.py فعلی این فیلد
رو ذخیره نمی‌کنه، باید اضافه‌ش کنی (یه خط ساده: record["factors"] = decision_result["factors"]).
"""

import json
import os
from collections import defaultdict

HISTORY_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "history.json")
SUGGESTION_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "weights_suggestion.json")
WEIGHTS_PATH = os.path.join(os.path.dirname(__file__), "weights.json")

# حداقل تعداد نمونه (هم در حالت agree و هم disagree) که برای اظهار نظر درباره‌ی
# یه شاخص لازمه. زیر این عدد، هر پیشنهادی صرفاً نویز آماریه.
MIN_SAMPLES_PER_FACTOR = 30

# اگه اختلاف دقت agree در مقابل disagree کمتر از این باشه، تغییری پیشنهاد نمی‌شه
# (چون داخل محدوده‌ی نوسان تصادفی قابل قبوله)
MIN_MEANINGFUL_DIFF_PCT = 8.0

MAX_WEIGHT_ADJUST_STEP = 0.15  # حداکثر تغییر پیشنهادی هر بار، تا وزن‌ها یهو نپرن


def _load_history():
    if not os.path.exists(HISTORY_PATH):
        return []
    with open(HISTORY_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_current_weights():
    if not os.path.exists(WEIGHTS_PATH):
        return {}
    with open(WEIGHTS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def analyze_factor_performance(records):
    """
    خروجی: {factor_name: {"agree_accuracy": float|None, "disagree_accuracy": float|None,
                           "agree_n": int, "disagree_n": int, "status": str}}
    """
    evaluated = [r for r in records if r.get("outcome") in ("correct", "wrong") and "factors" in r]
    stats = defaultdict(lambda: {"agree_correct": 0, "agree_total": 0, "disagree_correct": 0, "disagree_total": 0})

    for r in evaluated:
        overall_sign = 1 if r.get("score", 0) >= 0 else -1
        is_correct = r["outcome"] == "correct"
        for factor, value in r["factors"].items():
            if abs(value) < 0.3:
                continue  # خنثی، وارد تحلیل نمی‌شه (هم‌راستا با NEUTRAL_ZONE در decision.py)
            factor_sign = 1 if value > 0 else -1
            agrees = (factor_sign == overall_sign)
            key = "agree" if agrees else "disagree"
            stats[factor][f"{key}_total"] += 1
            if is_correct:
                stats[factor][f"{key}_correct"] += 1

    result = {}
    for factor, s in stats.items():
        agree_n, disagree_n = s["agree_total"], s["disagree_total"]
        if agree_n < MIN_SAMPLES_PER_FACTOR or disagree_n < MIN_SAMPLES_PER_FACTOR:
            result[factor] = {
                "agree_accuracy": round(s["agree_correct"]/agree_n*100, 1) if agree_n else None,
                "disagree_accuracy": round(s["disagree_correct"]/disagree_n*100, 1) if disagree_n else None,
                "agree_n": agree_n, "disagree_n": disagree_n,
                "status": "insufficient_data",
            }
            continue
        agree_acc = s["agree_correct"] / agree_n * 100
        disagree_acc = s["disagree_correct"] / disagree_n * 100
        result[factor] = {
            "agree_accuracy": round(agree_acc, 1), "disagree_accuracy": round(disagree_acc, 1),
            "agree_n": agree_n, "disagree_n": disagree_n,
            "status": "ok",
        }
    return result


def suggest_weight_changes(factor_stats, current_weights):
    suggestions = {}
    for factor, stats in factor_stats.items():
        current = current_weights.get(factor, 1.0)
        if stats["status"] != "ok":
            suggestions[factor] = {
                "current_weight": current, "suggested_weight": current,
                "reason": f"داده کافی نیست (agree_n={stats['agree_n']}, disagree_n={stats['disagree_n']}؛ حداقل لازم: {MIN_SAMPLES_PER_FACTOR})",
            }
            continue
        diff = stats["agree_accuracy"] - stats["disagree_accuracy"]
        if abs(diff) < MIN_MEANINGFUL_DIFF_PCT:
            suggestions[factor] = {
                "current_weight": current, "suggested_weight": current,
                "reason": f"اختلاف دقت ({diff:.1f}٪) معنادار نیست، تغییری پیشنهاد نمی‌شود.",
            }
            continue
        # اگه وقتی این شاخص «موافق» بوده دقت خیلی بیشتر بوده، وزنش رو زیاد کن؛
        # اگه برعکس (موافق بودنش رابطه‌ای با درست بودن نداشته یا حتی بدتر بوده)، کم کن.
        step = min(MAX_WEIGHT_ADJUST_STEP, abs(diff) / 100)
        new_weight = round(max(0.1, current * (1 + step if diff > 0 else 1 - step)), 2)
        suggestions[factor] = {
            "current_weight": current, "suggested_weight": new_weight,
            "reason": f"وقتی این شاخص با تصمیم نهایی هم‌جهت بوده، دقت {diff:+.1f}٪ متفاوت بوده (agree={stats['agree_accuracy']}٪, disagree={stats['disagree_accuracy']}٪).",
        }
    return suggestions


def run():
    from datetime import datetime
    records = _load_history()
    current_weights = _load_current_weights()
    factor_stats = analyze_factor_performance(records)
    suggestions = suggest_weight_changes(factor_stats, current_weights)

    total_evaluated = len([r for r in records if r.get("outcome") in ("correct", "wrong")])
    output = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "total_evaluated_signals": total_evaluated,
        "min_samples_required_per_factor": MIN_SAMPLES_PER_FACTOR,
        "note": (
            "این فقط یک پیشنهاده، نه تغییر خودکار. قبل از اعمال روی weights.json "
            "واقعی، حتماً خودت دستی بررسی کن."
            if total_evaluated > 0 else
            "هنوز هیچ سیگنالی ارزیابی نشده — این فایل تا وقتی history.json رکورد "
            "با outcome داشته باشه، فقط status=insufficient_data برمی‌گردونه."
        ),
        "factor_stats": factor_stats,
        "suggestions": suggestions,
    }
    with open(SUGGESTION_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    return output


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
