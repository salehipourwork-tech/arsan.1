"""
RSP — Backtest Engine v2.2
PATCH v2.0: < instead of <=, cooldown after TP, daily max trades, regime-only, volume filter
FIX v2.1: this file's calls into nearly every other module used the wrong
names/argument-shapes — none of it had ever run end-to-end. Reconciled
against the real signatures and against BacktestSummary's field names,
cross-validated by every other caller in the repo: net_return_pct /
average_trade_pct / fuzzy_diagnostics / run_backtest(bars_by_tf, base_tf=...,
min_history=..., coin_id=...).
NEW v2.2:
  - fuzzy_diagnostics now reports REAL per-bar gate-rejection stats
    (opportunity scores of every fuzzy candidate, not just the trades that
    were eventually recorded) — needed to actually see *why* a fuzzy run
    produces 0 trades instead of guessing.
  - Wires in the two previously-orphaned subsystems: the adaptive per-bar
    RSP.meta_controller (opt-in via settings.META_CONTROLLER_ENABLED) and
    the ATR-trailing-stop RSP.exit_manager (opt-in via
    settings.TRAILING_STOP_ENABLED). Both default OFF, so existing
    already-reported backtest numbers are unchanged unless explicitly
    enabled.
"""

import pandas as pd
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from collections import Counter
from ..config import settings
from ..decision_engine.decision_brain import make_decision
from ..risk_engine.risk_engine import plan_risk
from ..risk_engine.trade_quality import assess_trade_quality
from ..execution_simulator.trade_simulator import simulate_trade, simulate_trade_with_trailing
from ..regime_engine.regime_engine import detect_regime
from ..preprocessing.quality_engine import check_quality
from ..self_evaluation.self_evaluation import evaluate_trade
from ..self_evaluation.failure_analysis import analyze_failures
from ..fuzzy_integration_bridge import fuzzy_decision_bridge
from ..fuzzy_core.decision_controller import FuzzyDecisionController
from ..meta_controller.meta_controller import record_trade_result


@dataclass
class TradeRecord:
    entry_bar_idx: int; entry_timestamp: pd.Timestamp; action: str
    entry_price: float; stop_loss: float; take_profit: float
    risk_reward: float; position_size: float; exit_price: float
    exit_reason: str; pnl_pct: float; pnl_pct_gross: float
    bars_held: int; outcome: str; regime: str
    confidence: float; trade_quality: float; notes: List[str] = field(default_factory=list)
    evidence_snapshot: dict = field(default_factory=dict)
    meta_mode: str = ""  # NEW v2.2: which meta-controller mode produced this trade, if enabled


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

    quality = check_quality(base_df, base_tf)
    if not quality.quality_ok:
        return _empty_summary()

    trades: List[TradeRecord] = []
    equity = [1.0]
    peak = 1.0
    max_dd = 0.0
    cooldown_until: Dict[str, int] = {}
    daily_trade_count: Dict[str, int] = {}
    coin_label = coin_id or "unknown"

    fuzzy_controller = FuzzyDecisionController()
    # BUG FIX (this session): a second, unused RegimeRuleFilter() used to be
    # instantiated here (`regime_filter = RegimeRuleFilter()`), never called.
    # The real regime-based rule filtering already happens inside
    # FuzzyDecisionController itself (fuzzy_core/decision_controller.py owns
    # its own self.regime_filter); this was dead, misleading duplicate state.

    # NEW v2.2: real per-bar fuzzy gate diagnostics (only meaningful when
    # FUZZY_BACKTEST_ENABLED — left empty otherwise).
    fuzzy_candidates_seen = 0
    fuzzy_opportunity_scores: List[float] = []
    fuzzy_rejection_reasons: Counter = Counter()
    fuzzy_thresholds_used: List[float] = []

    for i in range(min_history, len(base_df)):
        ts = base_df.index[i]
        known = _known_slice(bars_by_tf, ts)  # FIX: uses < not <=
        known_base = known.get(base_tf)
        if known_base is None or known_base.empty:
            continue

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

        # FIX (this session): risk_plan/trade_quality used to be computed
        # AFTER the fuzzy gate, so fuzzy_controller.evaluate() below always
        # received trade_quality=None and _run_inference() had to fall back
        # to a synthetic risk_raw = 1 - volatility_raw (a deterministic
        # mirror of volatility_quality, carrying zero independent
        # information). Computing them here, before the fuzzy gate, lets
        # the fuzzy layer use the real, multi-factor TradeQualityReport
        # (risk:reward, data quality, regime quality, volume, setup —
        # see risk_engine/trade_quality.py) instead. The risk_plan validity
        # and MIN_ACCEPTABLE_RISK_REWARD checks that used to gate trade
        # entry right after this block are UNCHANGED and still applied
        # below, in the same place, with the same threshold.
        risk_plan = plan_risk(decision.action, known_base, regime)
        trade_quality = None
        if risk_plan.valid and risk_plan.risk_reward is not None:
            try:
                trade_quality = assess_trade_quality(risk_plan, quality, regime, decision.fusion)
            except Exception:
                trade_quality = None

        meta_mode = ""
        if settings.FUZZY_BACKTEST_ENABLED:
            fuzzy_candidates_seen += 1
            fuzzy_result = fuzzy_controller.evaluate(
                regime=regime, signals=decision.fusion, mtf=decision.mtf,
                trade_quality=trade_quality, history=None, coin=coin_label,
                contradiction=decision.contradiction,
            )
            if fuzzy_result is None:
                fuzzy_rejection_reasons["inference_returned_none"] += 1
                continue

            fuzzy_opportunity_scores.append(fuzzy_result.opportunity_score)
            meta_mode = getattr(fuzzy_result, "meta_mode", "") or ""

            method = getattr(settings, "OPPORTUNITY_SCORING_METHOD", "rules")
            threshold = getattr(settings, "FUZZY_OPPORTUNITY_THRESHOLD_BY_METHOD", {}).get(
                method, getattr(settings, "MIN_OPPORTUNITY_SCORE_FOR_TRADE",
                                settings.FUZZY_OPPORTUNITY_THRESHOLD))
            fuzzy_thresholds_used.append(threshold)

            if not fuzzy_result.can_trade:
                fuzzy_rejection_reasons["can_trade_false"] += 1
                continue

            # BUG FIX (this session, root cause of Meta-Adaptive's collapse
            # in the 2026-08-25 run - e.g. ETH: 0 trades, candidate opp
            # score avg=4.0 with max=77.4): when META_CONTROLLER_ENABLED,
            # fuzzy_result.opportunity_score is meta.final_confidence*100 -
            # a weighted-vote confidence over the Rules/AHP blend, already
            # gated by meta_controller's own internal logic (fuse_decisions'
            # TRADE_THRESHOLD=0.35, select_mode's PRESERVATION handling)
            # and already fully reflected in `can_trade` just above. That
            # score is on a fundamentally different scale from the static
            # single-method "rules"/"ahp" opportunity score that `threshold`
            # here is calibrated for (FUZZY_OPPORTUNITY_THRESHOLD_BY_METHOD),
            # so re-applying it a second time here isn't a safety margin -
            # it's a second, uncalibrated gate that rejected the large
            # majority of trades the meta-controller had already legitimately
            # approved. Only apply this static-scale check for the static
            # (non-meta) scoring path, where it's the intended (if partly
            # redundant with can_trade) safety check.
            if not meta_mode and fuzzy_result.opportunity_score < threshold:
                fuzzy_rejection_reasons["below_opportunity_threshold"] += 1
                continue

        entry_price = base_df["close"].iloc[i]

        if not risk_plan.valid or risk_plan.risk_reward is None:
            continue

        if risk_plan.risk_reward < settings.MIN_ACCEPTABLE_RISK_REWARD:
            continue

        if trade_quality is not None:
            decision.trade_quality = trade_quality.overall_score
        else:
            decision.trade_quality = decision.trade_quality or 0.0

        future_bars = _future_bars(base_df, i)

        # NEW v2.2: opt-in trailing-stop simulation via RSP/exit_manager.py.
        if getattr(settings, "TRAILING_STOP_ENABLED", False) and risk_plan.atr:
            sim = simulate_trade_with_trailing(decision.action, entry_price, risk_plan.atr, future_bars)
        else:
            sim = simulate_trade(decision.action, entry_price, risk_plan.stop_loss,
                                 risk_plan.take_profit, future_bars)

        if sim.outcome == "OPEN":
            continue

        trade = TradeRecord(
            entry_bar_idx=i, entry_timestamp=ts, action=decision.action,
            entry_price=entry_price, stop_loss=sim.stop_loss or risk_plan.stop_loss,
            take_profit=risk_plan.take_profit, risk_reward=risk_plan.risk_reward,
            position_size=risk_plan.position_size_pct, exit_price=sim.exit_price,
            exit_reason=sim.exit_reason, pnl_pct=sim.pnl_pct,
            pnl_pct_gross=sim.pnl_pct_gross, bars_held=sim.bars_held,
            outcome=sim.outcome, regime=regime_label,
            confidence=decision.confidence, trade_quality=decision.trade_quality,
            notes=risk_plan.notes, meta_mode=meta_mode,
            evidence_snapshot={
                "structure_event": regime.structure.last_structure_event if regime.structure else "NONE",
                "conflicting_evidence": len(decision.fusion.conflicting_evidence) if decision.fusion else 0,
                "data_quality_score": quality.quality_score,
            },
        )
        trades.append(trade)

        # NEW v2.2: feed the meta-controller's per-engine performance
        # tracker so its DEFENSIVE mode (an engine on a losing streak gets
        # downweighted) has real data. Since only one blended trade is
        # actually taken, both engines are credited/debited with the same
        # realized outcome — an approximation, but the only one possible
        # without running both engines' hypothetical trades in parallel.
        if settings.FUZZY_BACKTEST_ENABLED and getattr(settings, "META_CONTROLLER_ENABLED", False):
            record_trade_result(coin_label, "rules", sim.outcome, sim.pnl_pct)
            record_trade_result(coin_label, "ahp", sim.outcome, sim.pnl_pct)

        equity.append(equity[-1] * (1 + sim.pnl_pct / 100.0))
        if equity[-1] > peak:
            peak = equity[-1]
        dd = (peak - equity[-1]) / peak
        if dd > max_dd:
            max_dd = dd

        if sim.outcome == "LOSS" and sim.exit_reason in ("STOP_LOSS_HIT", "TRAILING_STOP_HIT"):
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

    fuzzy_diag = {}
    if settings.FUZZY_BACKTEST_ENABLED:
        executed_stats = fuzzy_decision_bridge.compare_with_fuzzy(trades)
        fuzzy_diag = {
            **executed_stats,
            # NEW v2.2: real gate-funnel numbers, not just the executed subset.
            "fuzzy_candidates_seen": fuzzy_candidates_seen,
            "fuzzy_rejection_reasons": dict(fuzzy_rejection_reasons),
            "candidate_opportunity_score_avg": round(sum(fuzzy_opportunity_scores) / len(fuzzy_opportunity_scores), 2)
                if fuzzy_opportunity_scores else None,
            "candidate_opportunity_score_min": round(min(fuzzy_opportunity_scores), 2) if fuzzy_opportunity_scores else None,
            "candidate_opportunity_score_max": round(max(fuzzy_opportunity_scores), 2) if fuzzy_opportunity_scores else None,
            "threshold_used_avg": round(sum(fuzzy_thresholds_used) / len(fuzzy_thresholds_used), 2)
                if fuzzy_thresholds_used else None,
        }
        # keep the pre-existing field names populated too (some callers read these directly)
        fuzzy_diag.setdefault("rejection_reasons", dict(fuzzy_rejection_reasons))
        if fuzzy_diag.get("opportunity_score_avg") is None:
            fuzzy_diag["opportunity_score_avg"] = fuzzy_diag["candidate_opportunity_score_avg"]
            fuzzy_diag["opportunity_score_min"] = fuzzy_diag["candidate_opportunity_score_min"]
            fuzzy_diag["opportunity_score_max"] = fuzzy_diag["candidate_opportunity_score_max"]

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
    return df.iloc[current_idx + 1: min(current_idx + 500, len(df))]


def _empty_summary() -> BacktestSummary:
    return BacktestSummary(0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, [],
                           "UNKNOWN", {}, {}, {})
