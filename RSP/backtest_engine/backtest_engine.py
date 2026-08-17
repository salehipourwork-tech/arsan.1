"""
RSP — Backtest Engine v2.0
PATCH: < instead of <=, cooldown after TP, daily max trades, regime-only, volume filter
"""

import pandas as pd
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from ..config import settings
from ..decision_engine.decision_brain import make_decision
from ..risk_engine.risk_engine import calculate_risk_plan
from ..execution_simulator.trade_simulator import simulate_trade
from ..signal_fusion.fusion_engine import fuse_signals
from ..regime_engine.regime_engine import detect_regime
from ..preprocessing.quality_engine import validate_data_quality
from ..self_evaluation.self_evaluation import evaluate_trade
from ..self_evaluation.failure_analysis import analyze_failures
from ..fuzzy_integration_bridge import fuzzy_decision_bridge
from ..fuzzy_core.decision_controller import FuzzyDecisionController
from ..regime_rule_filter import RegimeRuleFilter


@dataclass
class TradeRecord:
    entry_bar_idx: int; entry_timestamp: pd.Timestamp; action: str
    entry_price: float; stop_loss: float; take_profit: float
    risk_reward: float; position_size: float; exit_price: float
    exit_reason: str; pnl_pct: float; pnl_pct_gross: float
    bars_held: int; outcome: str; regime: str
    confidence: float; trade_quality: float; notes: List[str] = field(default_factory=list)


@dataclass
class BacktestSummary:
    total_trades: int; wins: int; losses: int; win_rate: float
    avg_pnl_pct: float; avg_win_pct: float; avg_loss_pct: float
    profit_factor: float; max_drawdown_pct: float; sharpe_ratio: float
    total_return_pct: float; trades: List[TradeRecord]
    dominant_regime: str; evaluation: dict; failure_analysis: dict; fuzzy_compare: dict


def run_backtest(bars_by_tf: Dict[str, pd.DataFrame], min_history: int = 200) -> BacktestSummary:
    base_tf = "15M"
    base_df = bars_by_tf.get(base_tf)
    if base_df is None or base_df.empty or len(base_df) < min_history:
        return _empty_summary()

    quality = validate_data_quality(bars_by_tf)
    if not quality.is_valid:
        return _empty_summary()

    trades: List[TradeRecord] = []
    equity = [1.0]
    peak = 1.0
    max_dd = 0.0
    cooldown_until: Dict[str, int] = {}
    daily_trade_count: Dict[str, int] = {}

    fuzzy_controller = FuzzyDecisionController()
    regime_filter = RegimeRuleFilter()

    for i in range(min_history, len(base_df)):
        ts = base_df.index[i]
        known = _known_slice(bars_by_tf, ts)  # FIX: uses < not <=

        regime = detect_regime(known)
        regime_label = regime.regime if regime else "UNKNOWN"

        if settings.STRONG_REGIME_ONLY_MODE:
            if regime_label not in settings.ALLOWED_REGIMES_FOR_TRADING:
                continue

        if i < cooldown_until.get("BUY", 0) or i < cooldown_until.get("SELL", 0):
            continue

        day_key = ts.strftime("%Y-%m-%d")
        if daily_trade_count.get(day_key, 0) >= settings.DAILY_MAX_TRADES:
            continue

        decision = make_decision(known, regime)
        if not decision or decision.action == "HOLD":
            continue

        if settings.VOLUME_FILTER_ENABLED:
            vol_data = known.get("15M")
            if vol_data is not None and not vol_data.empty:
                latest_volume = vol_data["volume"].iloc[-1]
                latest_close = vol_data["close"].iloc[-1]
                if latest_volume * latest_close < settings.MIN_VOLUME_USD:
                    continue

        if settings.FUZZY_BACKTEST_ENABLED:
            fuzzy_result = fuzzy_controller.evaluate(
                regime=regime, signals=fuse_signals(known, regime),
                mtf=None, trade_quality=None, history=None,
            )
            if not fuzzy_result or not fuzzy_result.can_trade:
                continue
            if fuzzy_result.opportunity_score < settings.FUZZY_OPPORTUNITY_THRESHOLD:
                continue

        entry_price = base_df["close"].iloc[i]
        atr = regime.atr if regime else base_df["close"].iloc[i] * 0.02
        risk_plan = calculate_risk_plan(decision.action, entry_price, atr, regime, fuse_signals(known, regime))

        if risk_plan.risk_reward < settings.MIN_ACCEPTABLE_RISK_REWARD:
            continue

        future_bars = _future_bars(base_df, i)
        sim = simulate_trade(decision.action, entry_price, risk_plan.stop_loss,
                             risk_plan.take_profit, future_bars)

        if sim.outcome == "OPEN":
            continue

        trade = TradeRecord(
            entry_bar_idx=i, entry_timestamp=ts, action=decision.action,
            entry_price=entry_price, stop_loss=risk_plan.stop_loss,
            take_profit=risk_plan.take_profit, risk_reward=risk_plan.risk_reward,
            position_size=risk_plan.position_size, exit_price=sim.exit_price,
            exit_reason=sim.exit_reason, pnl_pct=sim.pnl_pct,
            pnl_pct_gross=sim.pnl_pct_gross, bars_held=sim.bars_held,
            outcome=sim.outcome, regime=regime_label,
            confidence=decision.confidence, trade_quality=decision.trade_quality,
            notes=risk_plan.notes,
        )
        trades.append(trade)

        equity.append(equity[-1] * (1 + sim.pnl_pct))
        if equity[-1] > peak:
            peak = equity[-1]
        dd = (peak - equity[-1]) / peak
        if dd > max_dd:
            max_dd = dd

        # FIX: Cooldown after BOTH SL and TP
        if sim.outcome == "LOSS" and sim.exit_reason == "STOP_LOSS_HIT":
            cooldown_until[decision.action] = i + settings.COOLDOWN_BARS_AFTER_STOP_LOSS
        elif sim.outcome == "WIN" and sim.exit_reason == "TAKE_PROFIT_HIT":
            cooldown_until[decision.action] = i + settings.COOLDOWN_BARS_AFTER_TAKE_PROFIT

        daily_trade_count[day_key] = daily_trade_count.get(day_key, 0) + 1

    total_trades = len(trades)
    wins = sum(1 for t in trades if t.outcome == "WIN")
    losses = total_trades - wins
    win_rate = wins / total_trades if total_trades > 0 else 0.0
    avg_pnl = sum(t.pnl_pct for t in trades) / total_trades if total_trades > 0 else 0.0
    avg_win = sum(t.pnl_pct for t in trades if t.outcome == "WIN") / wins if wins > 0 else 0.0
    avg_loss = sum(t.pnl_pct for t in trades if t.outcome == "LOSS") / losses if losses > 0 else 0.0
    profit_factor = abs(avg_win * wins / (avg_loss * losses)) if losses > 0 and avg_loss != 0 else float('inf')
    total_return = (equity[-1] - 1.0) * 100 if len(equity) > 1 else 0.0

    returns = [equity[i] / equity[i-1] - 1 for i in range(1, len(equity))]
    sharpe = 0.0
    if len(returns) > 1:
        mean_r = sum(returns) / len(returns)
        std_r = (sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)) ** 0.5
        sharpe = (mean_r / std_r) * (252 ** 0.5) if std_r > 0 else 0.0

    regimes = [t.regime for t in trades]
    dominant = max(set(regimes), key=regimes.count) if regimes else "UNKNOWN"

    return BacktestSummary(
        total_trades=total_trades, wins=wins, losses=losses, win_rate=win_rate,
        avg_pnl_pct=avg_pnl, avg_win_pct=avg_win, avg_loss_pct=avg_loss,
        profit_factor=profit_factor, max_drawdown_pct=max_dd,
        sharpe_ratio=sharpe, total_return_pct=total_return, trades=trades,
        dominant_regime=dominant, evaluation=evaluate_trade(trades),
        failure_analysis=analyze_failures(trades),
        fuzzy_compare=fuzzy_decision_bridge.compare_with_fuzzy(trades) if settings.FUZZY_BACKTEST_ENABLED else {},
    )


def _known_slice(bars_by_tf: Dict[str, pd.DataFrame], ts) -> Dict[str, pd.DataFrame]:
    return {tf: df[df.index < ts].copy() for tf, df in bars_by_tf.items()}  # FIX: < not <=


def _future_bars(df: pd.DataFrame, current_idx: int) -> List[dict]:
    return [{"open": df["open"].iloc[j], "high": df["high"].iloc[j],
             "low": df["low"].iloc[j], "close": df["close"].iloc[j],
             "volume": df["volume"].iloc[j]}
            for j in range(current_idx + 1, min(current_idx + 500, len(df)))]


def _empty_summary() -> BacktestSummary:
    return BacktestSummary(0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, [],
                           "UNKNOWN", {}, {}, {})
