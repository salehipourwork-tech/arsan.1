"""
RSP — experiment_manager/experiment_manager.py  (Phase 26: EXPERIMENT MANAGER)

هر آزمایش یک ID می‌گیرد (RSP-EXP-001, ...) و در یک فایل JSON append-only
ثبت می‌شود تا هیچ آزمایشی بدون ثبت نتایج از بین نرود. ساده و بدون
وابستگی خارجی (فقط JSON روی دیسک) - مناسب اجرای دستی و GitHub Actions.
"""

import json
import os
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Optional

EXPERIMENT_LOG_PATH = os.path.join(os.path.dirname(__file__), "experiments_log.json")


@dataclass
class ExperimentRecord:
    experiment_id: str
    date: str
    strategy: str
    parameters: dict
    dataset: str
    timeframe: str
    results: dict
    changes: str = ""


def _load_log():
    if not os.path.exists(EXPERIMENT_LOG_PATH):
        return []
    with open(EXPERIMENT_LOG_PATH, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def _save_log(records):
    with open(EXPERIMENT_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def next_experiment_id() -> str:
    records = _load_log()
    return f"RSP-EXP-{len(records) + 1:03d}"


def log_experiment(strategy: str, parameters: dict, dataset: str, timeframe: str,
                    results: dict, changes: str = "") -> ExperimentRecord:
    records = _load_log()
    record = ExperimentRecord(
        experiment_id=next_experiment_id(),
        date=datetime.now(timezone.utc).isoformat(),
        strategy=strategy,
        parameters=parameters,
        dataset=dataset,
        timeframe=timeframe,
        results=results,
        changes=changes,
    )
    records.append(asdict(record))
    _save_log(records)
    return record


def list_experiments():
    return _load_log()
