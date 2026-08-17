"""
RSP — Market Structure Engine v2.0
PATCH: Confirmed swings only (no future look-ahead)
"""

from dataclasses import dataclass, field
from typing import List, Optional
import numpy as np


@dataclass
class SwingPoint:
    type: str; index: int; price: float; confirmed: bool = True


@dataclass
class MarketStructure:
    swing_highs: List[SwingPoint]; swing_lows: List[SwingPoint]
    support_levels: List[float]; resistance_levels: List[float]
    structure_events: List[str]
    last_swing_high: Optional[float]
    last_swing_low: Optional[float]


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


def analyze_structure(df) -> MarketStructure:
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

    return MarketStructure(
        swing_highs=swing_highs, swing_lows=swing_lows,
        support_levels=support_levels, resistance_levels=resistance_levels,
        structure_events=events, last_swing_high=last_sh, last_swing_low=last_sl,
    )
