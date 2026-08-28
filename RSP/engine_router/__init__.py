"""
RSP — engine_router

حداقل پل لازم برای Shadow/Paper Testing: هیچ منطق تصمیم‌گیری تغییر نمی‌کند،
نه در analyzer/ (legacy) و نه در RSP/. این پکیج فقط دو موتور موجود را از
بیرون صدا می‌زند و نتیجه را کنار هم، صادقانه، لاگ می‌کند.

سه mode:
  legacy  — فقط موتور فعلی آرسان (analyzer/*) اجرا می‌شود
  rsp     — فقط RSP (پارامترهای baseline قفل‌شده) اجرا می‌شود
  shadow  — هر دو روی همان کوین/همان لحظه اجرا می‌شوند (پیش‌فرض)

هیچ فایل تولیدی legacy (data/analysis.json, data/history.json) در حالت
shadow/rsp نوشته نمی‌شود — آن فایل‌ها فقط دست GitHub Action (analyze.yml)
هستند. هیچ سفارش واقعی، هیچ git commit، هیچ tuning.
"""
