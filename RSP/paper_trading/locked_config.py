#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP — paper_trading/locked_config.py

هدف: پارامترهای baseline که در RSP.calibration.run_calibration قفل شدند را
بدون هیچ تغییری از روی گزارش JSON کالیبراسیون می‌خواند و روی موتور اعمال
می‌کند. این ماژول هیچ‌وقت مقداری را تغییر/بهینه نمی‌کند — فقط همان چیزی که
در گزارش قفل شده را عیناً اعمال می‌کند. اگر گزارش وجود نداشته باشد یا
mode برنده baseline نباشد، صراحتاً خطا می‌دهد تا هیچ پارامتر تنظیم‌نشده‌ای
به‌صورت خاموش وارد validation phase نشود.
"""

import glob
import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from RSP.calibration.param_registry import apply_overrides, MODE_BASELINE
from RSP.config import settings

CALIBRATION_REPORTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "baseline_reports", "calibration",
)


@dataclass
class LockedBaseline:
    coin: str
    report_path: str
    generated_at: str
    winner_mode: str
    final_verdict: str
    locked_params: Dict[str, Any]


def find_latest_report(coin: str, reports_dir: str = CALIBRATION_REPORTS_DIR) -> str:
    pattern = os.path.join(reports_dir, f"{coin}_*.json")
    matches = sorted(glob.glob(pattern))
    if not matches:
        raise FileNotFoundError(
            f"هیچ گزارش کالیبراسیونی برای «{coin}» در {reports_dir} پیدا نشد. "
            f"ابتدا RSP.calibration.run_calibration را اجرا کنید."
        )
    return matches[-1]  # filenames are timestamp-suffixed → sorted = chronological


def load_locked_baseline(coin: str, report_path: Optional[str] = None) -> LockedBaseline:
    """
    گزارش کالیبراسیون را می‌خواند و پارامترهای قفل‌شده‌ی mode برنده (که طبق
    این پروژه باید baseline باشد — هیچ mode دیگری تا امروز از golden rule رد
    نشده) را برمی‌گرداند. عمداً هیچ مقداری را دستکاری نمی‌کند.
    """
    path = report_path or find_latest_report(coin)
    with open(path, "r", encoding="utf-8") as f:
        report = json.load(f)

    winner_mode = report.get("final_holdout", {}).get("winner_mode", MODE_BASELINE)
    final_verdict = report.get("final_verdict", "UNKNOWN")

    if winner_mode != MODE_BASELINE:
        # این validation runner فقط برای baseline نوشته شده. اگر روزی مدی
        # واقعاً از golden rule رد شد (SUCCESS)، runner باید صریحاً به‌روزرسانی
        # شود تا آن mode را هم بشناسد — به‌جای فرض‌کردن سایلنت که پارامترهای
        # baseline کافی‌اند.
        raise ValueError(
            f"گزارش کالیبراسیون winner_mode='{winner_mode}' را نشان می‌دهد، نه baseline. "
            f"final_verdict='{final_verdict}'. این runner فعلاً فقط baseline را پشتیبانی "
            f"می‌کند — قبل از استفاده باید عمداً بررسی/به‌روزرسانی شود."
        )

    locked_params = report.get("mode_comparison", {}).get(MODE_BASELINE, {}).get(
        "locked_params_last_fold", {}
    )
    if not locked_params:
        raise ValueError(f"locked_params_last_fold برای baseline در {path} خالی است.")

    return LockedBaseline(
        coin=report.get("coin", coin),
        report_path=path,
        generated_at=report.get("generated_at", ""),
        winner_mode=winner_mode,
        final_verdict=final_verdict,
        locked_params=dict(locked_params),
    )


def apply_locked_baseline(locked: LockedBaseline):
    """
    پارامترهای قفل‌شده را روی engine اعمال می‌کند (همان مسیر کدی که خود
    کالیبراسیون استفاده می‌کرد: RSP.calibration.param_registry.apply_overrides)
    و صراحتاً فازی/متا را خاموش می‌کند — چون ablation پذیرفته‌شده
    ("baseline_risk_only") دقیقاً با این دو فلگ خاموش تولید شد.
    برمی‌گرداند: یک تابع restore() بدون آرگومان.
    """
    restore_params = apply_overrides(locked.locked_params)
    prev_fuzzy = getattr(settings, "FUZZY_BACKTEST_ENABLED", False)
    prev_meta = getattr(settings, "META_CONTROLLER_ENABLED", False)
    settings.FUZZY_BACKTEST_ENABLED = False
    settings.META_CONTROLLER_ENABLED = False

    def restore():
        restore_params()
        settings.FUZZY_BACKTEST_ENABLED = prev_fuzzy
        settings.META_CONTROLLER_ENABLED = prev_meta

    return restore
