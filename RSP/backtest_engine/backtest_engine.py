"""
RSP — backtest_engine/backtest_engine.py (Phase 19: BACKTEST ENGINE)

موتور در زمان به‌جلو حرکت می‌کند: در هر گام i، فقط داده‌ی تا لحظه‌ی i را
می‌بیند (`df[:i+1]`) و تصمیم می‌گیرد.

FIX v1: Integration of ExitManager, RegimeRuleFilter, A+ Filter, TRX Blacklist
"""

import re
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

# FIX v1: New imports
from RSP.exit_manager import ExitManager
from RSP.regime_rule_filter import RegimeRuleFilter

try:
    from RSP.fuzzy_integration_bridge import integrate_fuzzy_decision
    _FUZZY_AVAILABLE = True
except Exception:
    _FUZZY_AVAILABLE = False

_FUZZY_DIRECTION_TO_ACTION = {"LONG": "BUY", "SHORT": "SELL", "HOLD": "WAIT", "NO_TRADE": "NO_TRADE"}


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
    evidence_snapshot: dict = field(default_factory=dict)


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
    fuzzy_diagnostics: dict = field(default_factory=dict)


_GATE_NAME_RE = re.compile(r"GATE_REJECTED:\s*([A-Z_]+)")


def _gate_name(reason: str) -> str:
    m = _GATE_NAME_RE.match(reason or "")
    if m:
        return m.group(1)
    if "STABILITY_CHECK_FAILED" in (reason or ""):
        return "STABILITY_CHECK_FAILED"
    return "OTHER"


def _known_slice(df: pd.DataFrame, ts, max_bars: int = None) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    sliced = df[df.index <= ts]
    if max_bars is not None and len(sliced) > max_bars:
        sliced = sliced.iloc[-max_bars:]
    return sliced


def run_backtest(bars_by_tf: Dict[str, pd.DataFrame], base_tf: str = "15M",
                 min_history: int = 60, step_after_trade: bool = True,
                 coin_id: str = "") -> BacktestSummary:
    """
    FIX v1: Added coin_id param for TRX blacklist check
    """
    use_fuzzy = bool(settings.FUZZY_BACKTEST_ENABLED)
    base_df = bars_by_tf.get(base_tf)
    summary = BacktestSummary()

    # FIX v1: TRX Blacklist
    trx_blacklist = set(getattr(settings, "TRX_BLACKLIST", []))
    if coin_id and coin_id.lower() in trx_blacklist:
        print(f"[BLACKLIST] Skipping {coin_id}")
        return summary

    if base_df is None or base_df.empty or len(base_df) < min_history + 5:
        return summary

    equity_curve = [0.0]
    i = min_history
    n = len(base_df)
    cooldown_until = {"BUY": None, "SELL": None}

    fuzzy_scores: List[float] = []
    fuzzy_rejections: Dict[str, int] = {}
    rejected_trade_outcomes: Dict[str, Dict[str, int]] = {}
    fuzzy_overrides = 0
    fuzzy_steps = 0

    # FIX v1: Regime filter
    regime_filter = RegimeRuleFilter()

    while i < n - 1:
        current_ts = base_df.index[i]
        known = {tf: _known_slice(df, current_ts, max_bars=settings.MAX_WARMUP_BARS) for tf, df in bars_by_tf.items()}
        known_base = known[base_tf]

        quality = check_quality(known_base, base_tf)
        regime = determine_regime(known_base)
        confluence = analyze_confluence(known_base)
        mtf = analyze_mtf(known)
        fusion = fuse_signals(regime, confluence, mtf)
        contradiction = detect_contradictions(fusion, mtf)
        confidence = compute_confidence(fusion, mtf, contradiction, quality.quality_score, regime.perception.atr_pct)
        decision = decide(regime, fusion, mtf, contradiction, confidence, quality.quality_ok)

        fuzzy_explain = None

        if use_fuzzy and _FUZZY_AVAILABLE and decision.action in ("BUY", "SELL"):
            original_action = decision.action
            try:
                pre_risk_plan = plan_risk(original_action, known_base, regime)
                integrated = integrate_fuzzy_decision(
                    coin=coin_id, crisp_decision=decision, regime=regime,
                    confluence=confluence, mtf=mtf, structure=regime.structure if regime else None,
                    risk_plan=pre_risk_plan, atr_pct=regime.perception.atr_pct if regime else 2.0,
                    fusion=fusion, contradiction=contradiction, confidence=confidence,
                )
                if integrated.used_fuzzy:
                    fuzzy_steps += 1
                    if integrated.fuzzy_report is not None:
                        fr = integrated.fuzzy_report

                        # FIX v1 (2026-08-16): این بلاک قبلاً یک A+ Filter دومِ
                        # مستقل و flat (بدون آگاهی از method) بود که فارغ از
                        # نتیجه‌ی decision_controller.py دوباره score را با
                        # MIN_OPPORTUNITY_SCORE_FOR_TRADE مقایسه می‌کرد. چون آن
                        # آستانه ثابت بود (نه per-method)، همیشه سخت‌گیرتر از
                        # threshold واقعیِ داخلی عمل می‌کرد و فیکس per-method را
                        # دور می‌زد. حالا فقط از fr.rejected_trade (که خودش
                        # همه‌ی گیت‌ها + adaptive threshold + method-aware
                        # threshold را لحاظ کرده) استفاده می‌کنیم — یک منبع واحد
                        # حقیقت، به‌جای دو آستانه‌ی ناهماهنگ.
                        fuzzy_scores.append(fr.opportunity_score)
                        if fr.rejected_trade:
                            reason = f"GATE_REJECTED: {fr.primary_reason}" if fr.primary_reason \
                                else (fr.notes[-1] if fr.notes else "UNKNOWN")
                            fuzzy_rejections[reason] = fuzzy_rejections.get(reason, 0) + 1
                            if pre_risk_plan is not None and pre_risk_plan.valid:
                                shadow_future_bars = base_df.iloc[i + 1:]
                                shadow_result = simulate_trade(
                                    original_action, pre_risk_plan.entry,
                                    pre_risk_plan.stop_loss, pre_risk_plan.take_profit,
                                    shadow_future_bars,
                                )
                                if shadow_result.outcome in ("WIN", "LOSS"):
                                    gate = _gate_name(reason)
                                    bucket = rejected_trade_outcomes.setdefault(
                                        gate, {"wins": 0, "losses": 0})
                                    bucket["wins" if shadow_result.outcome == "WIN" else "losses"] += 1

                        fuzzy_explain = {
                            "rule_fired": fr.primary_reason,
                            "active_rules": fr.active_rules,
                            "opportunity_score": fr.opportunity_score,
                            "fuzzy_confidence": fr.confidence,
                            "risk_quality": fr.risk_quality,
                            "entry_quality": fr.entry_quality,
                            "volatility_quality": fr.volatility_quality,
                            "contradiction_severity": fr.contradiction_severity,
                            "rejected_trade": fr.rejected_trade,
                            "notes": fr.notes,
                        }
                        new_action = _FUZZY_DIRECTION_TO_ACTION.get(integrated.final_direction, decision.action)
                        if new_action != decision.action:
                            fuzzy_overrides += 1
                            decision.why.append(
                                f"FUZZY_OVERRIDE: crisp={decision.action} -> fuzzy={new_action}"
                            )
                            decision.action = new_action
                        confidence.confidence = int(integrated.final_confidence * 100)
            except Exception:
                pass

        if decision.action in ("BUY", "SELL"):
            until = cooldown_until.get(decision.action)
            if until is not None and i < until:
                i += 1
                continue

            selection = select_strategy(regime, fusion)
            risk_plan = plan_risk(decision.action, known_base, regime)
            tq = evaluate_trade_quality(confidence.confidence, quality.quality_score,
                                         risk_plan.risk_reward, selection.selected is not None)

            if risk_plan.valid and tq.passed:
                future_bars = base_df.iloc[i + 1:]
                trade_result = simulate_trade(decision.action, risk_plan.entry, risk_plan.stop_loss,
                                               risk_plan.take_profit, future_bars)
                if trade_result.outcome in ("WIN", "LOSS"):
                    evidence_snapshot = {
                        "net_score": fusion.net_score,
                        "bullish_evidence": fusion.bullish_evidence,
                        "bearish_evidence": fusion.bearish_evidence,
                        "conflicting_evidence": fusion.conflicting_evidence,
                        "mtf_summary": mtf.summary,
                        "mtf_aligned": mtf.aligned,
                        "structure_pattern": regime.structure.pattern,
                        "structure_event": regime.structure.last_structure_event,
                        "divergences": confluence.divergences,
                        "momentum_state": confluence.momentum_state,
                        "atr_pct": regime.perception.atr_pct,
                        "selected_strategy": selection.selected.name if selection.selected else None,
                        "data_quality_score": quality.quality_score,
                    }
                    if fuzzy_explain is not None:
                        evidence_snapshot["fuzzy"] = fuzzy_explain
                    summary.trades.append(BacktestTradeLog(
                        timestamp=str(current_ts), action=decision.action, regime=regime.regime,
                        confidence=confidence.confidence, trade_quality=tq.score,
                        risk_reward=risk_plan.risk_reward, outcome=trade_result.outcome,
                        pnl_pct=trade_result.pnl_pct, bars_held=trade_result.bars_held,
                        exit_reason=trade_result.exit_reason,
                        evidence_snapshot=evidence_snapshot,
                    ))
                    equity_curve.append(equity_curve[-1] + trade_result.pnl_pct)
                    closed_at = i + trade_result.bars_held
                    if trade_result.outcome == "LOSS" and trade_result.exit_reason == "STOP_LOSS_HIT":
                        cooldown_until[decision.action] = closed_at + settings.COOLDOWN_BARS_AFTER_STOP_LOSS
                    i += trade_result.bars_held if step_after_trade and trade_result.bars_held > 0 else 1
                    continue

        i += 1

    # Aggregate metrics
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

    if use_fuzzy:
        summary.fuzzy_diagnostics = {
            "fuzzy_steps": fuzzy_steps,
            "fuzzy_overrides": fuzzy_overrides,
            "opportunity_score_min": round(min(fuzzy_scores), 2) if fuzzy_scores else None,
            "opportunity_score_max": round(max(fuzzy_scores), 2) if fuzzy_scores else None,
            "opportunity_score_avg": round(sum(fuzzy_scores) / len(fuzzy_scores), 2) if fuzzy_scores else None,
            "current_threshold": (getattr(settings, "FUZZY_OPPORTUNITY_THRESHOLD_BY_METHOD", {})
                                   .get(getattr(settings, "OPPORTUNITY_SCORING_METHOD", "rules"),
                                        getattr(settings, "FUZZY_OPPORTUNITY_THRESHOLD", 50.0))),
            "rejection_reasons": fuzzy_rejections,
            "rejected_trade_outcomes": rejected_trade_outcomes,
        }

    return summary
