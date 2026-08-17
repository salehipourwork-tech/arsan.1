"""
RSP — Strategy Selector v2.0
PATCH: Use regime strength (ADX) instead of fusion.net_score
"""

from typing import Optional
from ..config import settings


def select_strategy(fusion, regime, mtf) -> Optional[str]:
    if not regime:
        return None

    regime_label = regime.regime
    candidate_names = settings.REGIME_STRATEGY_COMPATIBILITY.get(regime_label, [])
    if not candidate_names:
        return None

    # FIX v2.0: Use direct regime strength instead of lagged fusion.net_score
    regime_strength = getattr(regime, 'adx', 20.0)

    if regime_strength >= 45 and "momentum" in candidate_names:
        preferred = "momentum"
    elif regime_strength >= 30 and "trend_following" in candidate_names:
        preferred = "trend_following"
    elif "pullback" in candidate_names:
        preferred = "pullback"
    elif "mean_reversion" in candidate_names:
        preferred = "mean_reversion"
    else:
        preferred = candidate_names[0]

    return preferred
