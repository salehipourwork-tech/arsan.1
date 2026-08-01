"""
RSP — backtest_engine/backtest_engine.py  (Phase 19: BACKTEST ENGINE)

موتور در زمان به‌جلو حرکت می‌کند: در هر گام i، فقط داده‌ی تا لحظه‌ی i را
می‌بیند (`df[:i+1]`) و تصمیم می‌گیرد. سپس با bars *بعد* از i (که تصمیم‌گیری
هرگز آن‌ها را ندیده) نتیجه شبیه‌سازی می‌شود. هیچ Future Leakage مجاز نیست -
این تضمین در ساختار کد وجود دارد نه فقط در نیت: تابع تصمیم‌گیری فقط
`known_bars_by_tf` (بارهای <= current_ts) را دریافت می‌کند.

محدودیت این نسخه (صادقانه اعلام می‌شود): برای هر گام، کل pipeline (اندیکاتور،
ساختار، ADX و...) از نو روی slice تا آن لحظه محاسبه می‌شود که کند اما دقیق
و بدون نشتی است. برای دیتاست‌های خیلی بزرگ باید بهینه شود (incremental
computation) - این بهینه‌سازی در این نسخه انجام نشده.

بعد از یک معامله باز، تا زمان بسته‌شدنش (بر اساس bars_held) گام بعدی از
آن نقطه ادامه می‌یابد تا از هم‌پوشانی معاملات جلوگیری شود (ساده‌سازی؛
معامله‌ی هم‌زمان پشتیبانی نمی‌شود - مستند در README).
"""

from dataclasses import dataclass, field
from typing import Dict, List
import pandas as pd

from RSP.regime_engine.regime_engine import determine_regime
from RSP.signal_engine.confluence import analyze_confluence
from RSP.multi_timeframe.mtf_brain import analyze_mtf
from RSP.signal_fusion.fusion_engine import fuse_signals
from RSP.contradiction_engine.contradiction_engine import detect_contradictions
from RSP.confidence_engine.confidence_engine import compute_confidence
from RSP.decision_engine.decision_brain import decide
from RSP.risk_engine.risk_engine import plan_risk
from RSP.risk_engine.trade_quality import evaluate_trade_quality
from RSP.strategy_lab.selector import select_strategy
from RSP.preprocessing.quality_engine import check_quality
from RSP.execution_simulator.trade_simulator import simulate_trade
from RSP.config import settings


@dataclass
class BacktestTradeLog:
    timestamp: str
    action: str
    regime: str
    confidence: float
    trade_quality: float
    risk_reward: float
    outcome: str
    pnl_pct: float
    bars_held: int
    exit_reason: str


@dataclass
class BacktestSummary:
    trades: List[BacktestTradeLog] = field(default_factory=list)
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    net_return_pct: float = 0.0
    profit_factor: float = 0.0
    max_drawdown_pct: float = 0.0
    average_trade_pct: float = 0.0


def _known_slice(df: pd.DataFrame, ts) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    return df[df.index <= ts]


def run_backtest(bars_by_tf: Dict[str, pd.DataFrame], base_tf: str = "15M",
                  min_history: int = 60, step_after_trade: bool = True) -> BacktestSummary:
    base_df = bars_by_tf.get(base_tf)
    summary = BacktestSummary()
    if base_df is None or base_df.empty or len(base_df) < min_history + 5:
        return summary

    equity_curve = [0.0]
    i = min_history
    n = len(base_df)

    while i < n - 1:
        current_ts = base_df.index[i]
        known = {tf: _known_slice(df, current_ts) for tf, df in bars_by_tf.items()}
        known_base = known[base_tf]

        quality = check_quality(known_base, base_tf)
        regime = determine_regime(known_base)
        confluence = analyze_confluence(known_base)
        mtf = analyze_mtf(known)
        fusion = fuse_signals(regime, confluence, mtf)
        contradiction = detect_contradictions(fusion, mtf)
        confidence = compute_confidence(fusion, mtf, contradiction, quality.quality_score, regime.perception.atr_pct)
        decision = decide(regime, fusion, mtf, contradiction, confidence, quality.quality_ok)

        if decision.action in ("BUY", "SELL"):
            selection = select_strategy(regime, fusion)
            risk_plan = plan_risk(decision.action, known_base, regime)
            tq = evaluate_trade_quality(confidence.confidence, quality.quality_score,
                                         risk_plan.risk_reward, selection.selected is not None)

            if risk_plan.valid and tq.passed:
                future_bars = base_df.iloc[i + 1:]
                trade_result = simulate_trade(decision.action, risk_plan.entry, risk_plan.stop_loss,
                                               risk_plan.take_profit, future_bars)
                if trade_result.outcome in ("WIN", "LOSS"):
                    summary.trades.append(BacktestTradeLog(
                        timestamp=str(current_ts), action=decision.action, regime=regime.regime,
                        confidence=confidence.confidence, trade_quality=tq.score,
                        risk_reward=risk_plan.risk_reward, outcome=trade_result.outcome,
                        pnl_pct=trade_result.pnl_pct, bars_held=trade_result.bars_held,
                        exit_reason=trade_result.exit_reason,
                    ))
                    equity_curve.append(equity_curve[-1] + trade_result.pnl_pct)
                    i += trade_result.bars_held if step_after_trade and trade_result.bars_held > 0 else 1
                    continue

        i += 1

    # ---- Aggregate metrics ----
    summary.total_trades = len(summary.trades)
    if summary.total_trades:
        summary.wins = sum(1 for t in summary.trades if t.outcome == "WIN")
        summary.losses = sum(1 for t in summary.trades if t.outcome == "LOSS")
        summary.win_rate = round(summary.wins / summary.total_trades * 100, 2)
        summary.net_return_pct = round(sum(t.pnl_pct for t in summary.trades), 3)
        summary.average_trade_pct = round(summary.net_return_pct / summary.total_trades, 4)

        gross_profit = sum(t.pnl_pct for t in summary.trades if t.pnl_pct > 0)
        gross_loss = abs(sum(t.pnl_pct for t in summary.trades if t.pnl_pct < 0))
        summary.profit_factor = round(gross_profit / gross_loss, 3) if gross_loss > 0 else float("inf")

        peak = equity_curve[0]
        max_dd = 0.0
        for v in equity_curve:
            peak = max(peak, v)
            max_dd = max(max_dd, peak - v)
        summary.max_drawdown_pct = round(max_dd, 3)

    return summary
