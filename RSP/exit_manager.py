#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP — Exit Manager (Profitability Fix v1)

هدف: RR=2.5 واقعی با Dynamic ATR-based SL/TP.
مشکل قبلی: TP زودتر از موعد hit می‌شد یا SL/TP در یک کندل اشتباه handle می‌شد.
"""

import numpy as np
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

@dataclass
class ExitLevels:
    entry_price: float
    stop_loss: float
    take_profit: float
    direction: str  # "LONG" or "SHORT"
    rr: float
    atr_at_entry: float

class ExitManager:
    """
    Enforces RR=2.5 with dynamic ATR-based exits.

    Rules:
    1. SL = entry ± (1.5 × ATR)
    2. TP = entry ± (3.75 × ATR) = 2.5 × SL distance
    3. Same-candle exit: PROPORTIONAL (not SL_FIRST)
    4. Trailing stop: activate at +1.0 ATR profit, trail at 1.0 ATR
    """

    def __init__(self, sl_atr_mult: float = 1.5, tp_atr_mult: float = 3.75,
                 trailing_activate_atr: float = 1.0, trailing_atr: float = 1.0):
        self.sl_atr_mult = sl_atr_mult
        self.tp_atr_mult = tp_atr_mult
        self.trailing_activate_atr = trailing_activate_atr
        self.trailing_atr = trailing_atr

    def calculate_exits(self, entry_price: float, atr: float, direction: str) -> ExitLevels:
        """Calculate SL and TP based on ATR and direction."""
        if direction == "LONG":
            sl = entry_price - (atr * self.sl_atr_mult)
            tp = entry_price + (atr * self.tp_atr_mult)
        elif direction == "SHORT":
            sl = entry_price + (atr * self.sl_atr_mult)
            tp = entry_price - (atr * self.tp_atr_mult)
        else:
            raise ValueError(f"Invalid direction: {direction}")

        rr = self.tp_atr_mult / self.sl_atr_mult
        return ExitLevels(
            entry_price=entry_price,
            stop_loss=sl,
            take_profit=tp,
            direction=direction,
            rr=rr,
            atr_at_entry=atr
        )

    def check_exit(self, exit_levels: ExitLevels, candle: Dict) -> Tuple[Optional[str], float]:
        """
        Check if SL or TP was hit in this candle.

        Returns: (outcome, exit_price)
        outcome: "TP", "SL", or None

        Same-candle logic (PROPORTIONAL):
        - If both SL and TP are within [low, high], determine which was hit first
          based on the proportion of the candle range.
        - For LONG: if open is closer to SL → SL hit first; if closer to TP → TP hit first.
        """
        direction = exit_levels.direction
        low, high = candle["low"], candle["high"]

        if direction == "LONG":
            sl_hit = low <= exit_levels.stop_loss
            tp_hit = high >= exit_levels.take_profit

            if sl_hit and tp_hit:
                # PROPORTIONAL: which is closer to open?
                open_p = candle["open"]
                dist_to_sl = abs(open_p - exit_levels.stop_loss)
                dist_to_tp = abs(open_p - exit_levels.take_profit)
                if dist_to_tp < dist_to_sl:
                    return "TP", exit_levels.take_profit
                else:
                    return "SL", exit_levels.stop_loss
            elif tp_hit:
                return "TP", exit_levels.take_profit
            elif sl_hit:
                return "SL", exit_levels.stop_loss

        elif direction == "SHORT":
            sl_hit = high >= exit_levels.stop_loss
            tp_hit = low <= exit_levels.take_profit

            if sl_hit and tp_hit:
                open_p = candle["open"]
                dist_to_sl = abs(open_p - exit_levels.stop_loss)
                dist_to_tp = abs(open_p - exit_levels.take_profit)
                if dist_to_tp < dist_to_sl:
                    return "TP", exit_levels.take_profit
                else:
                    return "SL", exit_levels.stop_loss
            elif tp_hit:
                return "TP", exit_levels.take_profit
            elif sl_hit:
                return "SL", exit_levels.stop_loss

        return None, 0.0

    def update_trailing_stop(self, exit_levels: ExitLevels, current_price: float) -> Optional[float]:
        """
        Update trailing stop if profit >= 1.0 ATR.
        Returns new SL or None if no change.
        """
        if exit_levels.direction == "LONG":
            profit_atr = (current_price - exit_levels.entry_price) / exit_levels.atr_at_entry
            if profit_atr >= self.trailing_activate_atr:
                new_sl = current_price - (exit_levels.atr_at_entry * self.trailing_atr)
                if new_sl > exit_levels.stop_loss:
                    return new_sl
        elif exit_levels.direction == "SHORT":
            profit_atr = (exit_levels.entry_price - current_price) / exit_levels.atr_at_entry
            if profit_atr >= self.trailing_activate_atr:
                new_sl = current_price + (exit_levels.atr_at_entry * self.trailing_atr)
                if new_sl < exit_levels.stop_loss:
                    return new_sl
        return None

    def get_trade_summary(self, exit_levels: ExitLevels, exit_price: float, bars_held: int) -> Dict:
        """Get trade summary with proper P&L calculation."""
        if exit_levels.direction == "LONG":
            pnl_pct = (exit_price - exit_levels.entry_price) / exit_levels.entry_price * 100
        else:
            pnl_pct = (exit_levels.entry_price - exit_price) / exit_levels.entry_price * 100

        return {
            "direction": exit_levels.direction,
            "entry": exit_levels.entry_price,
            "sl": exit_levels.stop_loss,
            "tp": exit_levels.take_profit,
            "exit": exit_price,
            "pnl_pct": pnl_pct,
            "bars_held": bars_held,
            "rr_target": exit_levels.rr,
            "atr_at_entry": exit_levels.atr_at_entry,
        }
