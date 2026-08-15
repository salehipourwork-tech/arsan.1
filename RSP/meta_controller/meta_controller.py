#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP — Meta-Controller (Phase 51: Adaptive Engine Selection)

معماری:
    MARKET DATA → Context Analyzer → Mode Selector → Decision Fusion → Final Decision

Modes:
    🟢 OPPORTUNITY   → Rules 85% + AHPv2 15%  (بازار شفاف و رونددار)
    🔵 DEFENSIVE     → Rules 20% + AHPv2 80%  (نوسان بالا / عدم قطعیت)
    🔴 PRESERVATION  → NO_TRADE 100%          (تضاد شدید / نوسان extreme)
"""

import os
import sys
import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from collections import deque

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from RSP.config import settings

META_HISTORY_MAXLEN = 100
META_ADAPTIVE_WINDOW = 20

VOLATILITY_DEFENSIVE_PCT = 75.0
VOLATILITY_PRESERVATION_PCT = 90.0
RULES_WIN_RATE_MIN = 0.30

MODE_WEIGHTS = {
    "OPPORTUNITY":   {"rules": 0.85, "ahp": 0.15, "no_trade": 0.00},
    "DEFENSIVE":     {"rules": 0.20, "ahp": 0.80, "no_trade": 0.00},
    "PRESERVATION":  {"rules": 0.00, "ahp": 0.00, "no_trade": 1.00},
}

@dataclass
class EngineDecision:
    engine: str
    direction: str
    confidence: float
    opportunity_score: float
    primary_reason: str = ""
    rejected: bool = False

@dataclass
class MarketContext:
    regime: str = "UNKNOWN"
    volatility_percentile: float = 50.0
    trend_clarity: float = 0.5
    contradiction_severity: float = 0.0
    market_stability: float = 0.5
    is_range_market: bool = False
    notes: List[str] = field(default_factory=list)

@dataclass
class MetaDecision:
    mode: str
    final_direction: str
    final_confidence: float
    rules_weight: float
    ahp_weight: float
    no_trade_weight: float
    engine_agreement: float
    primary_reason: str = ""
    mode_reason: str = ""
    fusion_notes: List[str] = field(default_factory=list)
    context: Optional[MarketContext] = None

@dataclass
class EnginePerformance:
    coin: str
    engine: str
    trades: deque = field(default_factory=lambda: deque(maxlen=META_HISTORY_MAXLEN))
    
    @property
    def recent_win_rate(self) -> float:
        recent = list(self.trades)[-META_ADAPTIVE_WINDOW:]
        if not recent:
            return 0.5
        wins = sum(1 for t in recent if t.get("outcome") == "WIN")
        return wins / len(recent)
    
    def record(self, outcome: str, pnl_pct: float = 0.0):
        self.trades.append({"outcome": outcome, "pnl": pnl_pct})

_performance_registry: Dict[str, Dict[str, EnginePerformance]] = {}

def get_performance(coin: str, engine: str) -> EnginePerformance:
    if coin not in _performance_registry:
        _performance_registry[coin] = {}
    if engine not in _performance_registry[coin]:
        _performance_registry[coin][engine] = EnginePerformance(coin=coin, engine=engine)
    return _performance_registry[coin][engine]

def record_trade_result(coin: str, engine: str, outcome: str, pnl_pct: float = 0.0):
    perf = get_performance(coin, engine)
    perf.record(outcome, pnl_pct)

def analyze_context(regime, atr_pct: float, atr_pct_series=None, adx_value=25.0,
                    contradiction_report=None, market_stability_score=0.5) -> MarketContext:
    ctx = MarketContext()
    ctx.regime = getattr(regime, "regime", "UNKNOWN") if regime else "UNKNOWN"
    ctx.market_stability = market_stability_score
    
    if atr_pct_series and len(atr_pct_series) >= 30:
        sorted_atr = sorted(atr_pct_series)
        count_below = sum(1 for a in sorted_atr if a < atr_pct)
        ctx.volatility_percentile = (count_below / len(sorted_atr)) * 100
    else:
        if atr_pct < 1.0: ctx.volatility_percentile = 30
        elif atr_pct < 2.5: ctx.volatility_percentile = 50
        elif atr_pct < 4.0: ctx.volatility_percentile = 70
        else: ctx.volatility_percentile = 85
    
    ctx.trend_clarity = min(1.0, adx_value / 50.0)
    ctx.is_range_market = ctx.regime == "RANGE"
    
    if contradiction_report:
        ctx.contradiction_severity = getattr(contradiction_report, "severity_score", 0.0)
    
    ctx.notes.append(f"regime={ctx.regime}, vol_pct={ctx.volatility_percentile:.0f}, "
                     f"trend_clarity={ctx.trend_clarity:.2f}")
    return ctx

def select_mode(ctx: MarketContext, rules_dec: EngineDecision, ahp_dec: EngineDecision, coin: str):
    notes = []
    
    if rules_dec.direction != ahp_dec.direction:
        if rules_dec.direction in ("LONG", "SHORT") and ahp_dec.direction in ("LONG", "SHORT"):
            notes.append("PRESERVATION: Engines disagree (LONG vs SHORT)")
            return "PRESERVATION", "engine_direction_conflict", notes
    
    if ctx.volatility_percentile >= VOLATILITY_PRESERVATION_PCT:
        notes.append(f"PRESERVATION: Volatility {ctx.volatility_percentile:.0f}th pct (extreme)")
        return "PRESERVATION", "extreme_volatility", notes
    
    if ctx.volatility_percentile >= VOLATILITY_DEFENSIVE_PCT:
        notes.append(f"DEFENSIVE: Volatility {ctx.volatility_percentile:.0f}th pct (high)")
        return "DEFENSIVE", "high_volatility", notes
    
    if ctx.contradiction_severity >= 0.5:
        notes.append(f"PRESERVATION: Contradiction {ctx.contradiction_severity:.2f}")
        return "PRESERVATION", "high_contradiction", notes
    
    if ctx.regime in ("UNKNOWN", "TRANSITION", "FAKE_BREAKOUT"):
        notes.append(f"DEFENSIVE: Regime is {ctx.regime}")
        return "DEFENSIVE", "uncertain_regime", notes
    
    rules_perf = get_performance(coin, "rules")
    if len(rules_perf.trades) >= 10:
        recent_wr = rules_perf.recent_win_rate
        if recent_wr < RULES_WIN_RATE_MIN:
            notes.append(f"DEFENSIVE: Rules WR {recent_wr:.1%} < {RULES_WIN_RATE_MIN:.1%}")
            return "DEFENSIVE", "rules_underperforming", notes
    
    if ctx.is_range_market and getattr(settings, "RANGE_REGIME_NO_TRADE", True):
        notes.append("PRESERVATION: RANGE no-trade")
        return "PRESERVATION", "range_no_trade", notes
    
    notes.append(f"OPPORTUNITY: regime={ctx.regime}, vol={ctx.volatility_percentile:.0f}th pct")
    return "OPPORTUNITY", "favorable_conditions", notes

def fuse_decisions(mode: str, rules_dec: EngineDecision, ahp_dec: EngineDecision, ctx: MarketContext) -> MetaDecision:
    weights = MODE_WEIGHTS[mode]
    meta = MetaDecision(
        mode=mode, rules_weight=weights["rules"], ahp_weight=weights["ahp"],
        no_trade_weight=weights["no_trade"], context=ctx, final_direction="NO_TRADE",
        final_confidence=0.0, engine_agreement=0.0,
    )
    
    dirs = [rules_dec.direction, ahp_dec.direction]
    if dirs[0] == dirs[1]: meta.engine_agreement = 1.0
    elif "NO_TRADE" in dirs or "HOLD" in dirs: meta.engine_agreement = 0.5
    else: meta.engine_agreement = 0.0
    
    if mode == "PRESERVATION":
        meta.final_direction = "NO_TRADE"
        meta.primary_reason = "Meta: preservation mode (risk off)"
        meta.fusion_notes.append("NO_TRADE: preservation elected")
        return meta
    
    votes = {"LONG": 0.0, "SHORT": 0.0, "HOLD": 0.0, "NO_TRADE": 0.0}
    if rules_dec.direction in votes:
        votes[rules_dec.direction] += weights["rules"] * rules_dec.confidence
    if ahp_dec.direction in votes:
        votes[ahp_dec.direction] += weights["ahp"] * ahp_dec.confidence
    if rules_dec.rejected and ahp_dec.rejected:
        votes["NO_TRADE"] += 0.3
    
    best_dir = max(votes, key=votes.get)
    best_score = votes[best_dir]
    
    TRADE_THRESHOLD = 0.35
    if best_dir in ("LONG", "SHORT") and best_score < TRADE_THRESHOLD:
        best_dir = "NO_TRADE"
        meta.fusion_notes.append(f"Score {best_score:.2f} below threshold {TRADE_THRESHOLD}")
    
    meta.final_direction = best_dir
    meta.final_confidence = min(1.0, best_score)
    
    reasons = []
    if rules_dec.direction == best_dir: reasons.append(f"Rules({weights['rules']:.0%})")
    if ahp_dec.direction == best_dir: reasons.append(f"AHP({weights['ahp']:.0%})")
    meta.primary_reason = f"Meta-{mode}: " + " + ".join(reasons) if reasons else "Consensus NO_TRADE"
    meta.fusion_notes.append(f"Votes: L={votes['LONG']:.2f} S={votes['SHORT']:.2f} H={votes['HOLD']:.2f} N={votes['NO_TRADE']:.2f}")
    meta.fusion_notes.append(f"Winner: {best_dir} score={best_score:.2f}")
    return meta

def run_meta_controller(coin: str, rules_decision: EngineDecision, ahp_decision: EngineDecision,
                        regime=None, atr_pct: float = 2.0, atr_pct_series=None, adx_value=25.0,
                        contradiction_report=None, market_stability_score=0.5) -> MetaDecision:
    ctx = analyze_context(regime, atr_pct, atr_pct_series, adx_value, contradiction_report, market_stability_score)
    mode, mode_reason, mode_notes = select_mode(ctx, rules_decision, ahp_decision, coin)
    meta = fuse_decisions(mode, rules_decision, ahp_decision, ctx)
    meta.mode_reason = mode_reason
    meta.fusion_notes.extend(mode_notes)
    return meta

def generate_meta_report(meta: MetaDecision, coin: str) -> str:
    lines = [
        "=" * 60, f"META-CONTROLLER — {coin.upper()}",
        f"Mode: {meta.mode} | Reason: {meta.mode_reason}",
        f"Final: {meta.final_direction} | Confidence: {meta.final_confidence:.2%}",
        f"Agreement: {meta.engine_agreement:.2%}",
        f"Weights: Rules={meta.rules_weight:.0%} AHP={meta.ahp_weight:.0%} NO_TRADE={meta.no_trade_weight:.0%}",
        "Context:",
        f"  Regime: {meta.context.regime if meta.context else 'N/A'}",
        f"  Vol%ile: {meta.context.volatility_percentile:.0f if meta.context else 'N/A'}",
        f"  TrendClarity: {meta.context.trend_clarity:.2f if meta.context else 'N/A'}",
        "Notes:",
    ]
    for note in meta.fusion_notes: lines.append(f"  • {note}")
    lines.append("=" * 60)
    return "\n".join(lines)

META_REGISTRY_PATH = os.path.join(os.path.dirname(__file__), "meta_registry.json")

def save_registry():
    data = {}
    for coin, engines in _performance_registry.items():
        data[coin] = {}
        for engine, perf in engines.items():
            data[coin][engine] = list(perf.trades)
    with open(META_REGISTRY_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def load_registry():
    global _performance_registry
    if not os.path.exists(META_REGISTRY_PATH): return
    try:
        with open(META_REGISTRY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        for coin, engines in data.items():
            _performance_registry[coin] = {}
            for engine, trades in engines.items():
                perf = EnginePerformance(coin=coin, engine=engine)
                perf.trades = deque(trades, maxlen=META_HISTORY_MAXLEN)
                _performance_registry[coin][engine] = perf
    except Exception: pass

try: load_registry()
except Exception: pass
