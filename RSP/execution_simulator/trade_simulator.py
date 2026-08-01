"""
RSP — execution_simulator/trade_simulator.py  (Phase 18: REALISTIC TRADE SIMULATOR)

شبیه‌سازی واقع‌گرایانه‌ی یک معامله‌ی تکی: کارمزد، اسلیپیج، و برخورد محافظه‌کارانه
وقتی SL و TP هر دو در یک کندل لمس می‌شوند (طبق تنظیمات: فرض می‌کنیم SL زودتر
خورده - محافظه‌کارانه‌ترین حالت ممکن).

این ماژول یک معامله را از نقطه‌ی ورود تا خروج، کندل‌به‌کندل به‌جلو می‌برد -
بدون نگاه به آینده (No Future Leakage) - و توسط backtest_engine روی
بازه‌های زمانی زیاد فراخوانی می‌شود.
"""

from dataclasses import dataclass
from typing import Optional
import pandas as pd

from RSP.config import settings


@dataclass
class TradeResult:
    action: str
    entry_price: float
    exit_price: Optional[float] = None
    stop_loss: float = 0.0
    take_profit: float = 0.0
    outcome: str = "OPEN"       # WIN | LOSS | OPEN | NO_FILL
    pnl_pct: float = 0.0
    bars_held: int = 0
    exit_reason: str = ""


def simulate_trade(action: str, entry_price: float, stop_loss: float, take_profit: float,
                    future_bars: pd.DataFrame, max_bars: int = 200) -> TradeResult:
    """
    future_bars: کندل‌های *بعد از* لحظه‌ی ورود (بدون هیچ داده‌ی قبل از ورود) - این
    قید همان چیزی است که از Future Leakage جلوگیری می‌کند: تابع فقط به بارهایی
    دسترسی دارد که از بیرون (backtest_engine) به‌عنوان "آینده‌ی نسبت به تصمیم"
    صراحتاً پاس داده شده‌اند، و منطق تصمیم‌گیری هرگز این بارها را ندیده است.
    """
    entry_price_with_slippage = entry_price * (1 + settings.SIMULATED_SLIPPAGE_PCT) if action == "BUY" \
        else entry_price * (1 - settings.SIMULATED_SLIPPAGE_PCT)

    result = TradeResult(action=action, entry_price=entry_price_with_slippage,
                          stop_loss=stop_loss, take_profit=take_profit)

    if future_bars is None or future_bars.empty:
        result.outcome = "NO_FILL"
        result.exit_reason = "NO_FUTURE_DATA"
        return result

    bars = future_bars.iloc[:max_bars]
    for i, (ts, bar) in enumerate(bars.iterrows(), start=1):
        high, low = bar["high"], bar["low"]
        hit_sl = (low <= stop_loss) if action == "BUY" else (high >= stop_loss)
        hit_tp = (high >= take_profit) if action == "BUY" else (low <= take_profit)

        if hit_sl and hit_tp:
            # هر دو در یک کندل - رویکرد محافظه‌کارانه: SL زودتر خورده فرض می‌شود
            exit_price = stop_loss
            outcome = "LOSS"
            reason = "SL_TP_SAME_CANDLE_CONSERVATIVE_SL_FIRST"
        elif hit_sl:
            exit_price, outcome, reason = stop_loss, "LOSS", "STOP_LOSS_HIT"
        elif hit_tp:
            exit_price, outcome, reason = take_profit, "WIN", "TAKE_PROFIT_HIT"
        else:
            continue

        exit_price_with_costs = exit_price * (1 - settings.SIMULATED_FEE_PCT - settings.SIMULATED_SLIPPAGE_PCT) \
            if action == "BUY" else exit_price * (1 + settings.SIMULATED_FEE_PCT + settings.SIMULATED_SLIPPAGE_PCT)

        pnl_pct = ((exit_price_with_costs - entry_price_with_slippage) / entry_price_with_slippage * 100) \
            if action == "BUY" else \
            ((entry_price_with_slippage - exit_price_with_costs) / entry_price_with_slippage * 100)

        result.exit_price = round(exit_price_with_costs, 6)
        result.outcome = outcome
        result.pnl_pct = round(pnl_pct, 4)
        result.bars_held = i
        result.exit_reason = reason
        return result

    result.outcome = "OPEN"
    result.exit_reason = "MAX_BARS_REACHED_WITHOUT_EXIT"
    result.bars_held = len(bars)
    return result
