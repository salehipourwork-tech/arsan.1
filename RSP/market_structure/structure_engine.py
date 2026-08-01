"""
RSP — market_structure/structure_engine.py  (Phase 8: MARKET STRUCTURE ENGINE)

تشخیص Swing High/Low، الگوی HH/HL/LH/LL، Break of Structure (BOS)،
Change of Character (CHoCH) و سطوح Support/Resistance ساده (بر اساس
swing pivotها). Liquidity Zones در این نسخه پیاده‌سازی نشده (مستند در
README به‌عنوان NOT IMPLEMENTED).
"""

from dataclasses import dataclass, field
from typing import List
import pandas as pd


@dataclass
class SwingPoint:
    index: int
    timestamp: str
    price: float
    kind: str   # "HIGH" یا "LOW"


@dataclass
class StructureReport:
    swings: List[SwingPoint] = field(default_factory=list)
    pattern: str = "UNKNOWN"          # e.g. HH_HL, LH_LL, MIXED
    last_structure_event: str = "NONE"  # BOS_BULLISH, BOS_BEARISH, CHOCH_BULLISH, CHOCH_BEARISH, NONE
    support_levels: List[float] = field(default_factory=list)
    resistance_levels: List[float] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def find_swing_points(df: pd.DataFrame, lookback=3) -> List[SwingPoint]:
    """Fractal-style swing detection: یک کندل swing high است اگر high آن از
    `lookback` کندل قبل و بعد بیشتر باشد (به همین ترتیب برای low)."""
    swings = []
    highs = df["high"].values
    lows = df["low"].values
    n = len(df)
    for i in range(lookback, n - lookback):
        window_high = highs[i - lookback:i + lookback + 1]
        window_low = lows[i - lookback:i + lookback + 1]
        if highs[i] == window_high.max() and (window_high == highs[i]).sum() == 1:
            swings.append(SwingPoint(index=i, timestamp=str(df.index[i]), price=float(highs[i]), kind="HIGH"))
        if lows[i] == window_low.min() and (window_low == lows[i]).sum() == 1:
            swings.append(SwingPoint(index=i, timestamp=str(df.index[i]), price=float(lows[i]), kind="LOW"))
    swings.sort(key=lambda s: s.index)
    return swings


def _classify_pattern(swings: List[SwingPoint]) -> str:
    highs = [s for s in swings if s.kind == "HIGH"]
    lows = [s for s in swings if s.kind == "LOW"]
    if len(highs) < 2 or len(lows) < 2:
        return "UNKNOWN"

    higher_highs = highs[-1].price > highs[-2].price
    higher_lows = lows[-1].price > lows[-2].price
    lower_highs = highs[-1].price < highs[-2].price
    lower_lows = lows[-1].price < lows[-2].price

    if higher_highs and higher_lows:
        return "HH_HL"       # ساختار صعودی سالم
    if lower_highs and lower_lows:
        return "LH_LL"       # ساختار نزولی سالم
    return "MIXED"


def _detect_structure_event(swings: List[SwingPoint], current_pattern: str, prev_pattern: str) -> str:
    if prev_pattern == "UNKNOWN":
        return "NONE"
    if prev_pattern == "LH_LL" and current_pattern == "HH_HL":
        return "CHOCH_BULLISH"
    if prev_pattern == "HH_HL" and current_pattern == "LH_LL":
        return "CHOCH_BEARISH"
    if prev_pattern == "HH_HL" and current_pattern == "HH_HL":
        return "BOS_BULLISH"
    if prev_pattern == "LH_LL" and current_pattern == "LH_LL":
        return "BOS_BEARISH"
    return "NONE"


def analyze_structure(df: pd.DataFrame, lookback=3) -> StructureReport:
    report = StructureReport()
    if df.empty or len(df) < (lookback * 2 + 5):
        report.notes.append("INSUFFICIENT_DATA_FOR_STRUCTURE")
        return report

    swings = find_swing_points(df, lookback=lookback)
    report.swings = swings[-12:]  # فقط آخرین‌ها را نگه می‌داریم برای گزارش

    if len(swings) >= 4:
        current_pattern = _classify_pattern(swings)
        prev_pattern = _classify_pattern(swings[:-2])  # یک مرحله قبل از آخرین swing
        report.pattern = current_pattern
        report.last_structure_event = _detect_structure_event(swings, current_pattern, prev_pattern)
    else:
        report.notes.append("NOT_ENOUGH_SWINGS")

    # Support/Resistance ساده: از swing lowها و highهای اخیر
    recent_lows = sorted([s.price for s in swings if s.kind == "LOW"])[-3:]
    recent_highs = sorted([s.price for s in swings if s.kind == "HIGH"], reverse=True)[-3:]
    report.support_levels = recent_lows
    report.resistance_levels = recent_highs

    report.notes.append("LIQUIDITY_ZONES_NOT_IMPLEMENTED")
    return report
