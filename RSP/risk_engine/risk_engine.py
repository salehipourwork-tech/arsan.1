"""
RSP — risk_engine/risk_engine.py (Phase 16: RISK ENGINE)

هدف: نه فقط پیدا کردن معامله، بلکه پیدا کردن معامله با ریسک کنترل‌شده.
Entry, Stop Loss, Take Profit, Risk/Reward, Position Size, Risk%, Max Exposure.

FIX v1: RR_TARGET=2.5 (was 2.0), SL_ATR_MULTIPLIER override support
"""

from dataclasses import dataclass, field
from typing import Optional

from RSP.config import settings
from RSP.regime_engine.regime_engine import RegimeReport
from RSP.indicators import technical as ta
import pandas as pd


@dataclass
class RiskPlan:
    action: str
    entry: Optional[float] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    risk_reward: Optional[float] = None
    position_size_pct: Optional[float] = None
    risk_percent: float = settings.MAX_RISK_PERCENT_PER_TRADE
    valid: bool = False
    reason: str = ""
    # NEW v2.1: exposes the ATR used to build this plan, so callers (the
    # trailing-stop simulator) don't have to recompute it from stop_loss
    # distance (which would be wrong once a structural_stop is chosen
    # instead of the raw ATR distance).
    atr: Optional[float] = None
    # FIX v2.1: backtest_engine.py reads risk_plan.notes into TradeRecord —
    # field never existed here.
    notes: list = field(default_factory=list)


def plan_risk(action: str, df_15m: pd.DataFrame, regime: RegimeReport) -> RiskPlan:
    if action not in ("BUY", "SELL"):
        return RiskPlan(action=action, valid=False, reason="ریسک فقط برای BUY/SELL محاسبه می‌شود")

    if df_15m is None or df_15m.empty or len(df_15m) < settings.ATR_PERIOD + 5:
        return RiskPlan(action=action, valid=False, reason="داده‌ی کافی برای محاسبه‌ی ATR/ریسک نیست")

    close = df_15m["close"]
    entry_price = float(close.iloc[-1])
    atr_series = ta.atr(df_15m["high"], df_15m["low"], close, settings.ATR_PERIOD)
    atr_val = ta.last(atr_series, None)
    if atr_val is None or atr_val <= 0:
        return RiskPlan(action=action, valid=False, reason="ATR قابل‌محاسبه نیست")

    structural_stop = None
    if action == "BUY" and regime.structure.support_levels:
        structural_stop = max(s for s in regime.structure.support_levels if s < entry_price) \
            if any(s < entry_price for s in regime.structure.support_levels) else None
    elif action == "SELL" and regime.structure.resistance_levels:
        structural_stop = min(r for r in regime.structure.resistance_levels if r > entry_price) \
            if any(r > entry_price for r in regime.structure.resistance_levels) else None

    # FIX v1: Use SL_ATR_MULTIPLIER from settings_patch if available
    sl_mult = getattr(settings, "SL_ATR_MULTIPLIER", settings.STOP_LOSS_ATR_MULTIPLIER)
    atr_stop_distance = sl_mult * atr_val

    if action == "BUY":
        atr_stop = entry_price - atr_stop_distance
        stop_loss = max(atr_stop, structural_stop) if structural_stop else atr_stop
        stop_loss = min(stop_loss, entry_price * 0.999)
        risk_per_unit = entry_price - stop_loss
        # FIX v1: RR_TARGET from settings_patch (default 2.5)
        rr_target = getattr(settings, "RR_TARGET", settings.TAKE_PROFIT_RR_TARGET)
        take_profit = entry_price + risk_per_unit * rr_target
    else:  # SELL
        atr_stop = entry_price + atr_stop_distance
        stop_loss = min(atr_stop, structural_stop) if structural_stop else atr_stop
        stop_loss = max(stop_loss, entry_price * 1.001)
        risk_per_unit = stop_loss - entry_price
        rr_target = getattr(settings, "RR_TARGET", settings.TAKE_PROFIT_RR_TARGET)
        take_profit = entry_price - risk_per_unit * rr_target

    if risk_per_unit <= 0:
        return RiskPlan(action=action, valid=False, reason="فاصله‌ی Stop Loss نامعتبر است")

    reward_per_unit = abs(take_profit - entry_price)
    rr = round(reward_per_unit / risk_per_unit, 2)

    risk_distance_pct = risk_per_unit / entry_price
    position_size_pct = round(min(100.0, settings.MAX_RISK_PERCENT_PER_TRADE / risk_distance_pct), 2) \
        if risk_distance_pct > 0 else 0.0

    # FIX v2.1: this always evaluated to settings.RR_TARGET (getattr's
    # default never triggers since RR_TARGET always exists as an
    # attribute), so settings.MIN_ACCEPTABLE_RISK_REWARD — the intended
    # true floor — was silently dead; a plan was only ever "valid" if its
    # rr matched the aspirational RR_TARGET almost exactly. Now uses the
    # real minimum floor, which is <= RR_TARGET, so this can only make
    # `valid` easier to satisfy, never harder.
    min_rr = getattr(settings, "MIN_ACCEPTABLE_RISK_REWARD", rr_target)
    plan = RiskPlan(
        action=action,
        entry=round(entry_price, 6),
        stop_loss=round(stop_loss, 6),
        take_profit=round(take_profit, 6),
        risk_reward=rr,
        position_size_pct=position_size_pct,
        risk_percent=settings.MAX_RISK_PERCENT_PER_TRADE,
        valid=rr >= min_rr,
        reason="OK" if rr >= min_rr else
               f"Risk/Reward={rr} کمتر از حداقل قابل‌قبول {min_rr}",
        atr=round(atr_val, 6),
    )
    return plan
