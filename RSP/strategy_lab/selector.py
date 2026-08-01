"""
RSP — strategy_lab/selector.py  (Phase 15: STRATEGY SELECTOR)

بر اساس رژیم فعلی (از config.REGIME_STRATEGY_COMPATIBILITY) و کیفیت
شواهد فیوژن، بهترین استراتژی سازگار را انتخاب می‌کند. اگر هیچ استراتژی
سازگاری وجود نداشته باشد، None برمی‌گرداند (یعنی: صبر کن).
"""

from dataclasses import dataclass
from typing import Optional, List

from RSP.strategy_lab.strategies import STRATEGY_LIBRARY, Strategy
from RSP.regime_engine.regime_engine import RegimeReport
from RSP.signal_fusion.fusion_engine import FusionReport


@dataclass
class SelectionResult:
    selected: Optional[Strategy]
    candidates: List[str]
    reason: str


def select_strategy(regime: RegimeReport, fusion: FusionReport) -> SelectionResult:
    candidate_names = [name for name in regime.compatible_strategies if name in STRATEGY_LIBRARY]

    if not candidate_names:
        return SelectionResult(selected=None, candidates=[],
                                reason=f"هیچ استراتژی‌ای برای رژیم {regime.regime} تعریف نشده")

    # اگر چند استراتژی سازگارند، آن‌که با net_score بیشترین هم‌خوانی مفهومی دارد را ترجیح بده:
    # momentum/breakout برای net_score قوی، trend_following برای روند پایدار،
    # mean_reversion برای net_score نزدیک صفر با نوسان محدود
    strength = abs(fusion.net_score)
    if strength > 0.5 and "momentum" in candidate_names:
        preferred = "momentum"
    elif "trend_following" in candidate_names and strength > 0.3:
        preferred = "trend_following"
    elif "breakout" in candidate_names:
        preferred = "breakout"
    elif "mean_reversion" in candidate_names:
        preferred = "mean_reversion"
    else:
        preferred = candidate_names[0]

    return SelectionResult(
        selected=STRATEGY_LIBRARY[preferred],
        candidates=candidate_names,
        reason=f"رژیم={regime.regime}, net_score={fusion.net_score:+.2f} -> انتخاب {preferred}",
    )
