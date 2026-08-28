#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP — engine_router/router.py

نقطه‌ی ورود واحد برای انتخاب موتور. سه mode: legacy / rsp / shadow
(پیش‌فرض: shadow، طبق دستور صریح).

صداقت معماری: legacy و RSP دو pipeline کاملاً مستقل با تایم‌فریم متفاوت‌اند
(legacy=روزانه، RSP=15M زنده). این router هرگز ادعا نمی‌کند که این دو از
"داده‌ی یکسان" استفاده کرده‌اند — فقط تضمین می‌کند که هر دو در یک بازه‌ی
زمانی مشترک (یک اجرای router) فراخوانی شده‌اند، و timestamp دقیق داده‌ی
هرکدام را جدا ثبت می‌کند تا هرکسی بعداً بتواند خودش قضاوت کند که چقدر
"هم‌زمان" بوده‌اند. این فیلد صراحتاً same_data=False همیشه است (چون واقعاً
یکسان نیستند) — دروغ گفتن به لاگ ممنوع.

هیچ فایل legacy (data/analysis.json, data/history.json) اینجا نوشته
نمی‌شود. هیچ git commit. هیچ سفارش واقعی.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

from RSP.engine_router import config as router_config
from RSP.engine_router.adapter_legacy import run_legacy_decision
from RSP.engine_router.adapter_rsp import run_rsp_decision

SHADOW_LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shadow_log")


def _shadow_log_path(coin: str) -> str:
    return os.path.join(SHADOW_LOG_DIR, f"{coin}_shadow_compare.jsonl")


def _append_shadow_record(coin: str, record: Dict[str, Any]) -> None:
    os.makedirs(SHADOW_LOG_DIR, exist_ok=True)
    with open(_shadow_log_path(coin), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def run(coin: str, mode: str = None, rsp_report_path: str = None) -> Dict[str, Any]:
    mode = mode or router_config.ENGINE_MODE
    if mode not in router_config.VALID_MODES:
        raise ValueError(f"mode نامعتبر: {mode} — باید یکی از {router_config.VALID_MODES} باشد")

    router_run_started_at = datetime.now(timezone.utc).isoformat()

    if mode == "legacy":
        legacy = run_legacy_decision(coin)
        return {"router_run_started_at": router_run_started_at, "mode": mode,
                "coin": coin, "legacy": legacy}

    if mode == "rsp":
        rsp = run_rsp_decision(coin, locked_report_path=rsp_report_path)
        return {"router_run_started_at": router_run_started_at, "mode": mode,
                "coin": coin, "rsp": rsp}

    # mode == "shadow": هر دو، برای همان کوین، در همین اجرای router
    legacy = run_legacy_decision(coin)
    rsp = run_rsp_decision(coin, locked_report_path=rsp_report_path)

    decisions_agree = (
        legacy.get("decision") is not None and rsp.get("decision") is not None and
        _normalize_action(legacy.get("decision")) == _normalize_action(rsp.get("decision"))
    )

    record = {
        "router_run_started_at": router_run_started_at,
        "mode": "shadow",
        "coin": coin,
        # صادقانه: این دو موتور هیچ‌وقت از "داده‌ی یکسان" استفاده نمی‌کنند —
        # legacy روزانه است، RSP زنده‌ی 15M. فقط در یک بازه‌ی زمانی مشترک
        # (همین اجرای router) صدا زده شده‌اند، هرکدام با pipeline خودش.
        "same_underlying_data": False,
        "same_execution_window": True,
        "legacy": legacy,
        "rsp": rsp,
        "decisions_agree": decisions_agree,
    }
    _append_shadow_record(coin, record)
    return record


def _normalize_action(a) -> str:
    """legacy از 'buy/sell/hold' استفاده می‌کند، RSP از 'BUY/SELL/WAIT/NO_TRADE'.
    فقط برای مقایسه‌ی جهت خام نرمالایز می‌شود — هیچ تصمیمی تغییر نمی‌کند."""
    if a is None:
        return "UNKNOWN"
    a = str(a).upper()
    if a in ("BUY",):
        return "BUY"
    if a in ("SELL",):
        return "SELL"
    if a in ("HOLD", "WAIT", "NO_TRADE"):
        return "NO_TRADE_OR_HOLD"
    return a


def main():
    ap = argparse.ArgumentParser(description="RSP Engine Router — legacy/rsp/shadow")
    ap.add_argument("--coins", nargs="+", default=["bitcoin"])
    ap.add_argument("--mode", choices=router_config.VALID_MODES, default=None,
                     help="پیش‌فرض: متغیر محیطی ARSAN_ENGINE_MODE یا shadow")
    ap.add_argument("--rsp-report", default=None,
                     help="مسیر مشخص گزارش کالیبراسیون RSP (پیش‌فرض: آخرین گزارش baseline)")
    args = ap.parse_args()

    exit_code = 0
    for coin in args.coins:
        try:
            result = run(coin, mode=args.mode, rsp_report_path=args.rsp_report)
            mode = result["mode"]
            if mode == "shadow":
                l, r = result["legacy"], result["rsp"]
                print(f"[{coin}] SHADOW | legacy={l.get('decision', l.get('error'))} "
                      f"(daily, freshness={l.get('data_freshness_iso')}) | "
                      f"rsp={r.get('decision', r.get('error'))} "
                      f"(15M, freshness={r.get('data_freshness_iso')}) | "
                      f"agree={result['decisions_agree']}")
            elif mode == "legacy":
                l = result["legacy"]
                print(f"[{coin}] LEGACY | decision={l.get('decision', l.get('error'))}")
            else:
                r = result["rsp"]
                print(f"[{coin}] RSP | decision={r.get('decision', r.get('error'))}")
        except Exception as e:
            print(f"[{coin}] FATAL: {e}", file=sys.stderr)
            exit_code = 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
