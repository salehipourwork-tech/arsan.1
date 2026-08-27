#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP — paper_trading/ledger.py

ثبت append-only هر تصمیم (شامل NO_TRADE/WAIT) و مدیریت پوزیشن‌های کاغذی
باز/بسته. هیچ سرمایه‌ی واقعی یا اجرای صرافی درگیر نیست — فقط دنبال‌کردن
اینکه اگر واقعاً معامله می‌شد، با قیمت‌های واقعی بعدی چه اتفاقی می‌افتاد.

فایل‌ها (هرکدام per-coin، append-only JSONL برای decisions):
  RSP/paper_trading/logs/<coin>_decisions.jsonl   — هر چرخه، یک خط JSON
  RSP/paper_trading/logs/<coin>_open_positions.json  — state فعلی پوزیشن‌های باز
  RSP/paper_trading/logs/<coin>_closed_trades.jsonl  — هر پوزیشن بسته‌شده، یک خط
"""

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")


def _ensure_dir():
    os.makedirs(LOG_DIR, exist_ok=True)


def _decisions_path(coin: str) -> str:
    return os.path.join(LOG_DIR, f"{coin}_decisions.jsonl")


def _open_positions_path(coin: str) -> str:
    return os.path.join(LOG_DIR, f"{coin}_open_positions.json")


def _closed_trades_path(coin: str) -> str:
    return os.path.join(LOG_DIR, f"{coin}_closed_trades.jsonl")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_decision(coin: str, record: Dict[str, Any]) -> None:
    """هر چرخه‌ی validation، صرف‌نظر از action (شامل NO_TRADE/WAIT)، اینجا ثبت می‌شود."""
    _ensure_dir()
    record = dict(record)
    record.setdefault("logged_at", now_iso())
    with open(_decisions_path(coin), "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def load_open_positions(coin: str) -> List[Dict[str, Any]]:
    path = _open_positions_path(coin)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def save_open_positions(coin: str, positions: List[Dict[str, Any]]) -> None:
    _ensure_dir()
    with open(_open_positions_path(coin), "w", encoding="utf-8") as f:
        json.dump(positions, f, ensure_ascii=False, indent=2, default=str)


def append_closed_trade(coin: str, trade: Dict[str, Any]) -> None:
    _ensure_dir()
    trade = dict(trade)
    trade.setdefault("closed_logged_at", now_iso())
    with open(_closed_trades_path(coin), "a", encoding="utf-8") as f:
        f.write(json.dumps(trade, ensure_ascii=False, default=str) + "\n")


def read_jsonl(path: str) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def load_decisions(coin: str) -> List[Dict[str, Any]]:
    return read_jsonl(_decisions_path(coin))


def load_closed_trades(coin: str) -> List[Dict[str, Any]]:
    return read_jsonl(_closed_trades_path(coin))
