"""
RSP — Market Structure Engine v2.1
PATCH: Confirmed swings only (no future look-ahead)
FIX v2.1: renamed to StructureReport + added last_structure_event (BOS/CHoCH)
and pattern (HH_HL / LH_LL), which regime_engine.py and fusion_engine.py
require but were never computed in v2.0.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import numpy as np


@dataclass
class SwingPoint:
    type: str; index: int; price: float; confirmed: bool = True


@dataclass
class StructureReport:
    swing_highs: List[SwingPoint]; swing_lows: List[SwingPoint]
    support_levels: List[float]; resistance_levels: List[float]
    structure_events: List[str]
    last_swing_high: Optional[float]
    last_swing_low: Optional[float]
    pattern: str = "UNKNOWN"
    last_structure_event: str = "NONE"


# Backward-compat alias (in case anything else in the repo still imports
# the old v2.0 name).
MarketStructure = StructureReport


def _classify_pattern(recent_highs: list, recent_lows: list) -> str:
    """HH_HL = higher-highs/higher-lows (uptrend structure),
    LH_LL = lower-highs/lower-lows (downtrend structure)."""
    if len(recent_highs) >= 2 and len(recent_lows) >= 2:
        higher_high = recent_highs[-1] > recent_highs[-2]
        higher_low = recent_lows[-1] > recent_lows[-2]
        lower_high = recent_highs[-1] < recent_highs[-2]
        lower_low = recent_lows[-1] < recent_lows[-2]
        if higher_high and higher_low:
            return "HH_HL"
        if lower_high and lower_low:
            return "LH_LL"
        return "MIXED"
    return "UNKNOWN"


def _classify_structure_event(pattern: str, last_close: float,
                               last_sh: Optional[float], last_sl: Optional[float]) -> str:
    """
    BOS (Break of Structure) = price breaks the last swing in the direction
    the trend was already moving (continuation).
    CHoCH (Change of Character) = price breaks the last swing against the
    established trend (first sign of reversal).
    """
    if last_sh is not None and last_close > last_sh:
        return "BOS_BULLISH" if pattern == "HH_HL" else "CHOCH_BULLISH"
    if last_sl is not None and last_close < last_sl:
        return "BOS_BEARISH" if pattern == "LH_LL" else "CHOCH_BEARISH"
    return "NONE"


def detect_swing_points(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, lookback: int = 3) -> tuple:
    n = len(highs)
    swing_highs = []
    swing_lows = []

    # FIX v2.0: Only confirmed swings (i + lookback < n guarantees confirmation)
    for i in range(lookback, n - lookback):
        window_high = highs[i - lookback:i + lookback + 1]
        window_low = lows[i - lookback:i + lookback + 1]

        if highs[i] == np.max(window_high):
            swing_highs.append(SwingPoint("high", i, highs[i], True))
        if lows[i] == np.min(window_low):
            swing_lows.append(SwingPoint("low", i, lows[i], True))

    return swing_highs, swing_lows


def analyze_structure(df) -> StructureReport:
    highs = df["high"].values
    lows = df["low"].values
    closes = df["close"].values

    swing_highs, swing_lows = detect_swing_points(highs, lows, closes, lookback=3)

    # FIX v2.0: Only use confirmed recent swings
    recent_highs = [s.price for s in swing_highs[-5:] if s.confirmed]
    recent_lows = [s.price for s in swing_lows[-5:] if s.confirmed]

    support_levels = sorted(recent_lows)[-3:] if recent_lows else []
    resistance_levels = sorted(recent_highs)[:3] if recent_highs else []

    events = []
    last_sh = recent_highs[-1] if recent_highs else None
    last_sl = recent_lows[-1] if recent_lows else None

    if len(recent_highs) >= 2 and recent_highs[-1] > recent_highs[-2]: events.append("HIGHER_HIGH")
    if len(recent_lows) >= 2 and recent_lows[-1] > recent_lows[-2]: events.append("HIGHER_LOW")
    if len(recent_highs) >= 2 and recent_highs[-1] < recent_highs[-2]: events.append("LOWER_HIGH")
    if len(recent_lows) >= 2 and recent_lows[-1] < recent_lows[-2]: events.append("LOWER_LOW")

    pattern = _classify_pattern(recent_highs, recent_lows)
    last_close = closes[-1] if len(closes) else None
    last_structure_event = _classify_structure_event(pattern, last_close, last_sh, last_sl)

    return StructureReport(
        swing_highs=swing_highs, swing_lows=swing_lows,
        support_levels=support_levels, resistance_levels=resistance_levels,
        structure_events=events, last_swing_high=last_sh, last_swing_low=last_sl,
        pattern=pattern, last_structure_event=last_structure_event,
    )
