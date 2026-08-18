"""
RSP — Backtest Engine v2.1
PATCH v2.0: < instead of <=, cooldown after TP, daily max trades, regime-only, volume filter
FIX v2.1: this file's calls into nearly every other module used the wrong
names/argument-shapes (see inline FIX notes below) — none of it had ever
actually run end-to-end. Reconciled against the real signatures and against
BacktestSummary's field names, which are cross-validated by every other
caller in the repo (main.py, walk_forward.py, monte_carlo.py, versioning.py,
multi_coin_meta_test.py, ...): net_return_pct / average_trade_pct /
fuzzy_diagnostics / run_backtest(bars_by_tf, base_tf=..., min_history=...,
coin_id=...). Those external call sites were treated as the source of truth
over this file's own (unused-by-anyone-else) internals.
"""

import pandas as pd
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from ..config import settings
from ..decision_engine.decision_brain import make_decision
from ..risk_engine.risk_engine import plan_risk
from ..risk_engine.trade_quality import assess_trade_quality
from ..execution_simulator.trade_simulator import simulate_trade
from ..regime_engine.regime_engine import detect_regime
from ..preprocessing.quality_engine import check_quality
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
    # FIX v2.1: failure_analysis._classify_trade() can use this if present.
    evidence_snapshot: dict = field(default_factory=dict)


@dataclass
class BacktestSummary:
    total_trades: int; wins: int; losses: int; win_rate: float
    avg_pnl_pct: float; avg_win_pct: float; avg_loss_pct: float
    profit_factor: float; max_drawdown_pct: float; sharpe_ratio: float
    net_return_pct: float; average_trade_pct: float; trades: List[TradeRecord]
    dominant_regime: str; evaluation: dict; failure_analysis: dict
    fuzzy_diagnostics: dict


def run_backtest(bars_by_tf: Dict[str, pd.DataFrame], base_tf: str = "15M",
                 min_history: int = 200, coin_id: Optional[str] = None) -> BacktestSummary:
    base_df = bars_by_tf.get(base_tf)
    if base_df is None or base_df.empty or len(base_df) < min_history:
        return _empty_summary()

    # FIX v2.1: validate_data_quality() didn't exist (check_quality/
    # check_all_timeframes did) and QualityReport has .quality_ok, not
    # .is_valid.
    quality = check_quality(base_df, base_tf)
    if not quality.quality_ok:
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
        known_base = known.get(base_tf)
        if known_base is None or known_base.empty:
            continue

        # FIX v2.1: detect_regime() takes a single DataFrame (it's an alias
        # of determine_regime), not the whole {tf: df} dict.
        regime = detect_regime(known_base)
        regime_label = regime.regime if regime else "UNKNOWN"

        if settings.STRONG_REGIME_ONLY_MODE:
            if regime_label not in settings.ALLOWED_REGIMES_FOR_TRADING:
                continue

        if i < cooldown_until.get("BUY", 0) or i < cooldown_until.get("SELL", 0):
            continue

        day_key = ts.strftime("%Y-%m-%d")
        if daily_trade_count.get(day_key, 0) >= settings.DAILY_MAX_TRADES:
            continue

        # FIX v2.1: make_decision() didn't exist before — now built in
        # decision_brain.py; it internally runs confluence/mtf/fusion/
        # contradiction/confidence and attaches them to the Decision so we
        # don't have to (and can't safely) recompute them here.
        decision = make_decision(known, regime)
        if not decision or decision.action not in ("BUY", "SELL"):
            continue

        if settings.VOLUME_FILTER_ENABLED:
            vol_data = known.get(base_tf)
            if vol_data is not None and not vol_data.empty:
                latest_volume = vol_data["volume"].iloc[-1]
                latest_close = vol_data["close"].iloc[-1]
                if latest_volume * latest_close < settings.MIN_VOLUME_USD:
                    continue

        if settings.FUZZY_BACKTEST_ENABLED:
            # FIX v2.1: fuse_signals(known, regime) was called with the
            # wrong args/arity (and needlessly recomputed the fusion that
            # make_decision() already built). Reuse decision.fusion/mtf.
            fuzzy_result = fuzzy_controller.evaluate(
                regime=regime, signals=decision.fusion,
                mtf=decision.mtf, trade_quality=None, history=None,
            )
            if not fuzzy_result or not fuzzy_result.can_trade:
                continue
            method = getattr(settings, "OPPORTUNITY_SCORING_METHOD", "rules")
            threshold = getattr(settings, "FUZZY_OPPORTUNITY_THRESHOLD_BY_METHOD", {}).get(
                method, getattr(settings, "MIN_OPPORTUNITY_SCORE_FOR_TRADE",
                                settings.FUZZY_OPPORTUNITY_THRESHOLD))
            if fuzzy_result.opportunity_score < threshold:
                continue

        entry_price = base_df["close"].iloc[i]

        # FIX v2.1: calculate_risk_plan(...) didn't exist and regime.atr
        # doesn't exist either — the real function is plan_risk(action,
        # df_15m, regime); it computes its own ATR internally.
        risk_plan = plan_risk(decision.action, known_base, regime)
        if not risk_plan.valid or risk_plan.risk_reward is None:
            continue

        if risk_plan.risk_reward < settings.MIN_ACCEPTABLE_RISK_REWARD:
            continue

        confluence_for_quality = None
        try:
            trade_quality = assess_trade_quality(risk_plan, quality, regime, decision.fusion)
            decision.trade_quality = trade_quality.overall_score
        except Exception:
            decision.trade_quality = decision.trade_quality or 0.0

        # FIX v2.1: _future_bars() used to build a List[dict], but
        # simulate_trade() needs a real DataFrame (.iloc/.iterrows()).
        future_bars = _future_bars(base_df, i)
        sim = simulate_trade(decision.action, entry_price, risk_plan.stop_loss,
                             risk_plan.take_profit, future_bars)

        if sim.outcome == "OPEN":
            continue

        trade = TradeRecord(
            entry_bar_idx=i, entry_timestamp=ts, action=decision.action,
            entry_price=entry_price, stop_loss=risk_plan.stop_loss,
            take_profit=risk_plan.take_profit, risk_reward=risk_plan.risk_reward,
            # FIX v2.1: RiskPlan's field is position_size_pct, not position_size.
            position_size=risk_plan.position_size_pct, exit_price=sim.exit_price,
            exit_reason=sim.exit_reason, pnl_pct=sim.pnl_pct,
            pnl_pct_gross=sim.pnl_pct_gross, bars_held=sim.bars_held,
            outcome=sim.outcome, regime=regime_label,
            confidence=decision.confidence, trade_quality=decision.trade_quality,
            notes=risk_plan.notes,
            evidence_snapshot={
                "structure_event": regime.structure.last_structure_event if regime.structure else "NONE",
                "conflicting_evidence": len(decision.fusion.conflicting_evidence) if decision.fusion else 0,
                "data_quality_score": quality.quality_score,
            },
        )
        trades.append(trade)

        equity.append(equity[-1] * (1 + sim.pnl_pct / 100.0))
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
    win_rate = (wins / total_trades * 100) if total_trades > 0 else 0.0
    avg_pnl = sum(t.pnl_pct for t in trades) / total_trades if total_trades > 0 else 0.0
    avg_win = sum(t.pnl_pct for t in trades if t.outcome == "WIN") / wins if wins > 0 else 0.0
    avg_loss = sum(t.pnl_pct for t in trades if t.outcome == "LOSS") / losses if losses > 0 else 0.0
    profit_factor = abs(avg_win * wins / (avg_loss * losses)) if losses > 0 and avg_loss != 0 else float('inf')
    net_return = (equity[-1] - 1.0) * 100 if len(equity) > 1 else 0.0

    returns = [equity[i] / equity[i-1] - 1 for i in range(1, len(equity))]
    sharpe = 0.0
    if len(returns) > 1:
        mean_r = sum(returns) / len(returns)
        std_r = (sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)) ** 0.5
        sharpe = (mean_r / std_r) * (252 ** 0.5) if std_r > 0 else 0.0

    regimes = [t.regime for t in trades]
    dominant = max(set(regimes), key=regimes.count) if regimes else "UNKNOWN"

    evaluation = evaluate_trade(trades)
    failure = analyze_failures(trades, evaluation.get("results")) if total_trades else analyze_failures(trades)

    fuzzy_diag = fuzzy_decision_bridge.compare_with_fuzzy(trades) if settings.FUZZY_BACKTEST_ENABLED else {}

    return BacktestSummary(
        total_trades=total_trades, wins=wins, losses=losses, win_rate=win_rate,
        avg_pnl_pct=avg_pnl, avg_win_pct=avg_win, avg_loss_pct=avg_loss,
        profit_factor=profit_factor, max_drawdown_pct=max_dd * 100,
        sharpe_ratio=sharpe, net_return_pct=net_return, average_trade_pct=avg_pnl,
        trades=trades, dominant_regime=dominant, evaluation=evaluation,
        failure_analysis=_failure_report_to_dict(failure), fuzzy_diagnostics=fuzzy_diag,
    )


def _failure_report_to_dict(report) -> dict:
    if report is None:
        return {}
    return {
        "total_losses": report.total_losses,
        "category_counts": report.category_counts,
        "category_avg_pnl": report.category_avg_pnl,
        "dominant_failure_mode": report.dominant_failure_mode,
        "worst_regime": report.worst_regime,
        "notes": report.notes,
    }


def _known_slice(bars_by_tf: Dict[str, pd.DataFrame], ts) -> Dict[str, pd.DataFrame]:
    return {tf: df[df.index < ts].copy() for tf, df in bars_by_tf.items()}  # FIX: < not <=


def _future_bars(df: pd.DataFrame, current_idx: int) -> pd.DataFrame:
    # FIX v2.1: simulate_trade() needs a DataFrame (uses .iloc/.iterrows()),
    # not a list of dicts.
    return df.iloc[current_idx + 1: min(current_idx + 500, len(df))]


def _empty_summary() -> BacktestSummary:
    return BacktestSummary(0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, [],
                           "UNKNOWN", {}, {}, {})
