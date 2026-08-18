"""
RSP — regime_engine/regime_engine.py  (Phase 5: MARKET REGIME ENGINE)

رژیم بازار را از perception.py می‌گیرد و به لیست استراتژی‌های سازگار
(REGIME-AWARE STRATEGY SELECTION) نگاشت می‌دهد. تشخیص Breakout/Fake
Breakout/Breakdown/Recovery نیازمند ساختار بازار است، پس با
market_structure ترکیب می‌شود.
"""

from dataclasses import dataclass, field
from typing import List
import pandas as pd

from RSP.config import settings
from RSP.regime_engine.perception import perceive_market, PerceptionReport
from RSP.market_structure.structure_engine import analyze_structure, StructureReport


@dataclass
class RegimeReport:
    regime: str
    perception: PerceptionReport
    structure: StructureReport
    compatible_strategies: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


def determine_regime(df: pd.DataFrame) -> RegimeReport:
    perception = perceive_market(df)
    structure = analyze_structure(df)

    regime = perception.state

    # اصلاح رژیم با استفاده از رویدادهای ساختاری (BOS/CHoCH)
    if structure.last_structure_event == "BOS_BULLISH" and regime in ("RANGE", "TRANSITION"):
        regime = "BREAKOUT"
    elif structure.last_structure_event == "CHOCH_BEARISH" and regime in ("UPTREND", "WEAK_UPTREND"):
        regime = "TRANSITION"
    elif structure.last_structure_event == "CHOCH_BULLISH" and regime in ("DOWNTREND", "WEAK_DOWNTREND", "STRONG_DOWNTREND"):
        regime = "RECOVERY"
    elif structure.last_structure_event == "BOS_BEARISH" and regime == "STRONG_DOWNTREND" and perception.atr_pct > 5:
        regime = "CRASH"

    if regime not in settings.REGIME_LABELS:
        regime = "UNKNOWN"

    report = RegimeReport(
        regime=regime,
        perception=perception,
        structure=structure,
        compatible_strategies=settings.REGIME_STRATEGY_COMPATIBILITY.get(regime, []),
    )
    if not report.compatible_strategies:
        report.notes.append("هیچ استراتژی سازگاری برای این رژیم تعریف نشده -> احتیاط/WAIT")
    return report


# Backward-compat alias — backtest_engine.py imports this name.
detect_regime = determine_regime
