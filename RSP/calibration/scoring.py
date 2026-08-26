#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP.calibration.scoring

Objective = OOS Net Profit, contextualized by Profit Factor, Expectancy,
Max Drawdown, Trade Count, Average R, Consistency across windows, and the
IS->OOS degradation gap — never Win Rate alone, per the brief.

Golden rule (hard gate, not a soft weight):
    IS up & OOS down                                   -> REJECT, always.
    OOS net profit up, DD controlled, PF up, Expectancy
    up, stable across multiple windows                 -> keep.
Anything else is judged case-by-case and reported, never silently kept.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import statistics

from RSP.backtest_engine.backtest_engine import BacktestSummary


# Composite weights — deliberately NO win-rate term. Net profit dominates;
# the rest are guardrails against "profit via one lucky fat trade" or
# "profit via reckless risk".
WEIGHTS = {"net": 0.40, "pf": 0.20, "dd": 0.15, "expectancy": 0.15, "consistency": 0.10}

MIN_TRADES_FOR_TRUST = 10          # below this, a result is a sanity-check flag, not a verdict
MAX_DD_HARD_CAP_PCT = 35.0         # a candidate whose OOS DD exceeds this is disqualified outright
MIN_TRADE_COUNT_RATIO_TO_BASELINE = 0.5  # candidate must keep at least half of baseline's OOS trade count
                                          # guards against "fewer trades -> apparently higher avg" games


@dataclass
class WindowScore:
    label: str
    trades: int
    net_return_pct: float
    profit_factor: float
    max_drawdown_pct: float
    win_rate: float
    expectancy_pct: float          # avg pnl% per trade
    avg_r: float                   # avg realized R multiple (pnl / risked distance), proxy via risk_reward*outcome
    reliable: bool

    @staticmethod
    def from_summary(label: str, summary: BacktestSummary) -> "WindowScore":
        trades = summary.total_trades
        avg_r = 0.0
        if trades:
            r_vals = []
            for t in summary.trades:
                # realized R: for a WIN, ~ +risk_reward; for a LOSS, ~ -1; approximate
                # via sign of outcome scaled by the plan's intended RR (matches how the
                # brief's "Average R" is normally read - risk multiples achieved, not raw %).
                if t.outcome == "WIN":
                    r_vals.append(t.risk_reward if t.risk_reward else 1.0)
                elif t.outcome == "LOSS":
                    r_vals.append(-1.0)
                else:
                    r_vals.append(0.0)
            avg_r = sum(r_vals) / len(r_vals)
        return WindowScore(
            label=label, trades=trades,
            net_return_pct=summary.net_return_pct,
            profit_factor=summary.profit_factor,
            max_drawdown_pct=summary.max_drawdown_pct,
            win_rate=summary.win_rate,
            expectancy_pct=summary.average_trade_pct,
            avg_r=round(avg_r, 3),
            reliable=trades >= MIN_TRADES_FOR_TRUST,
        )

    def composite_score(self) -> float:
        if self.trades == 0:
            return -999.0
        net_score = max(-50, min(50, self.net_return_pct)) + 50
        pf_score = 100.0 if self.profit_factor == float("inf") else min(100, self.profit_factor * 50)
        dd_score = max(0, 50 - self.max_drawdown_pct)
        exp_score = max(-50, min(50, self.expectancy_pct * 20)) + 50
        score = (net_score * (WEIGHTS["net"] / (WEIGHTS["net"] + WEIGHTS["pf"] + WEIGHTS["dd"] + WEIGHTS["expectancy"]))
                 + pf_score * (WEIGHTS["pf"] / (WEIGHTS["net"] + WEIGHTS["pf"] + WEIGHTS["dd"] + WEIGHTS["expectancy"]))
                 + dd_score * (WEIGHTS["dd"] / (WEIGHTS["net"] + WEIGHTS["pf"] + WEIGHTS["dd"] + WEIGHTS["expectancy"]))
                 + exp_score * (WEIGHTS["expectancy"] / (WEIGHTS["net"] + WEIGHTS["pf"] + WEIGHTS["dd"] + WEIGHTS["expectancy"])))
        if not self.reliable:
            score -= 15  # visible penalty, not a hard veto — still ranked, but flagged
        return round(score, 2)


@dataclass
class Verdict:
    accepted: bool
    reason: str
    hard_disqualified: bool = False


def consistency_score(oos_windows: List[WindowScore]) -> float:
    """0..100: how consistent net_return_pct is across OOS windows (low
    variance & mostly-same-sign = high consistency). This is the
    "Consistency" term in the objective and is what catches a change that
    only worked in one lucky window."""
    reliable = [w for w in oos_windows if w.trades > 0]
    if len(reliable) < 2:
        return 50.0  # neutral — not enough windows to judge
    rets = [w.net_return_pct for w in reliable]
    same_sign = sum(1 for r in rets if (r > 0) == (rets[0] > 0)) / len(rets)
    mean = statistics.mean(rets)
    std = statistics.pstdev(rets) if len(rets) > 1 else 0.0
    cov_penalty = min(1.0, std / (abs(mean) + 1e-6)) if mean != 0 else (1.0 if std > 0 else 0.0)
    return round(max(0.0, min(100.0, same_sign * 100 * (1 - 0.5 * cov_penalty))), 1)


def aggregate_oos(oos_windows: List[WindowScore]) -> WindowScore:
    reliable = [w for w in oos_windows if w.trades > 0]
    if not reliable:
        return WindowScore("OOS_AGG", 0, 0, 0, 0, 0, 0, 0, False)
    trades = sum(w.trades for w in reliable)
    net = sum(w.net_return_pct for w in reliable)
    pf_vals = [w.profit_factor for w in reliable if w.profit_factor not in (float("inf"),)]
    pf = statistics.mean(pf_vals) if pf_vals else float("inf")
    dd = max(w.max_drawdown_pct for w in reliable)
    wr = statistics.mean(w.win_rate for w in reliable)
    exp = statistics.mean(w.expectancy_pct for w in reliable)
    avg_r = statistics.mean(w.avg_r for w in reliable)
    return WindowScore("OOS_AGG", trades, round(net, 3), round(pf, 3), round(dd, 3),
                        round(wr, 2), round(exp, 4), round(avg_r, 3), trades >= MIN_TRADES_FOR_TRUST)


def golden_rule_gate(candidate_is: WindowScore, candidate_oos_windows: List[WindowScore],
                      baseline_oos_windows: List[WindowScore]) -> Verdict:
    """
    The one non-negotiable gate from the brief:
      IS up & OOS down  -> reject, always, no exceptions.
      OOS net up + DD controlled + PF up + Expectancy up + stable across
      windows -> keep.
    Everything else gets a specific, honest reason (not silently accepted).
    """
    cand_agg = aggregate_oos(candidate_oos_windows)
    base_agg = aggregate_oos(baseline_oos_windows)

    if cand_agg.trades == 0:
        return Verdict(False, "OOS trade count = 0 برای این candidate — قابل قضاوت نیست، رد می‌شود.", True)

    if cand_agg.max_drawdown_pct > MAX_DD_HARD_CAP_PCT:
        return Verdict(False, f"OOS Max Drawdown={cand_agg.max_drawdown_pct:.1f}% > سقف مجاز "
                               f"{MAX_DD_HARD_CAP_PCT}% — رد می‌شود (ریسک مصنوعی).", True)

    if base_agg.trades > 0 and cand_agg.trades < base_agg.trades * MIN_TRADE_COUNT_RATIO_TO_BASELINE:
        return Verdict(False, f"تعداد معاملات OOS ({cand_agg.trades}) کمتر از "
                               f"{MIN_TRADE_COUNT_RATIO_TO_BASELINE:.0%} baseline ({base_agg.trades}) است — "
                               f"شبهه‌ی 'سود ظاهری با کاهش شدید تعداد معاملات'، رد می‌شود.", True)

    is_score = candidate_is.composite_score()
    oos_score = cand_agg.composite_score()
    gap = is_score - oos_score

    # THE golden rule, applied literally.
    if is_score > 0 and oos_score < is_score and cand_agg.net_return_pct < candidate_is.net_return_pct \
            and gap > 15:
        return Verdict(False, f"IS score={is_score:.1f} بالا رفت ولی OOS score={oos_score:.1f} افت کرد "
                               f"(gap={gap:.1f}) — طبق قانون طلایی این یک شکست حساب می‌شود، نه بهبود.", False)

    if base_agg.trades == 0:
        # no baseline to compare against (e.g. calibrating from scratch) — judge on absolute terms
        ok = cand_agg.net_return_pct > 0 and cand_agg.profit_factor >= 1.0
        return Verdict(ok, "بدون baseline OOS برای مقایسه؛ قضاوت بر اساس OOS مطلق: "
                            f"Net={cand_agg.net_return_pct:+.2f}% PF={cand_agg.profit_factor:.2f}.")

    net_up = cand_agg.net_return_pct > base_agg.net_return_pct
    dd_controlled = cand_agg.max_drawdown_pct <= base_agg.max_drawdown_pct * 1.15  # allow small slack, not "reckless"
    pf_up = cand_agg.profit_factor >= base_agg.profit_factor * 0.97  # tolerate float noise
    exp_up = cand_agg.expectancy_pct >= base_agg.expectancy_pct * 0.97
    consistent = consistency_score(candidate_oos_windows) >= 40.0

    if net_up and dd_controlled and pf_up and exp_up and consistent:
        return Verdict(True, f"OOS Net {base_agg.net_return_pct:+.2f}%→{cand_agg.net_return_pct:+.2f}%, "
                              f"DD کنترل‌شده ({cand_agg.max_drawdown_pct:.1f}% vs {base_agg.max_drawdown_pct:.1f}%), "
                              f"PF {base_agg.profit_factor:.2f}→{cand_agg.profit_factor:.2f}, "
                              f"Expectancy {base_agg.expectancy_pct:+.3f}%→{cand_agg.expectancy_pct:+.3f}%, "
                              f"consistency={consistency_score(candidate_oos_windows):.0f}/100 — نگه‌داشتن ارزش دارد.")

    reasons = []
    if not net_up: reasons.append(f"OOS Net Profit بهبود نیافت ({base_agg.net_return_pct:+.2f}% -> {cand_agg.net_return_pct:+.2f}%)")
    if not dd_controlled: reasons.append(f"Max Drawdown بدتر شد ({base_agg.max_drawdown_pct:.1f}% -> {cand_agg.max_drawdown_pct:.1f}%)")
    if not pf_up: reasons.append(f"Profit Factor افت کرد ({base_agg.profit_factor:.2f} -> {cand_agg.profit_factor:.2f})")
    if not exp_up: reasons.append(f"Expectancy افت کرد ({base_agg.expectancy_pct:+.3f}% -> {cand_agg.expectancy_pct:+.3f}%)")
    if not consistent: reasons.append(f"ناپایدار بین پنجره‌ها (consistency={consistency_score(candidate_oos_windows):.0f}/100)")
    return Verdict(False, "؛ ".join(reasons) + " — رد می‌شود.")
