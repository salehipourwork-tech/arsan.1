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

try:
    from RSP.fuzzy_integration_bridge import integrate_fuzzy_decision
    _FUZZY_AVAILABLE = True
except Exception:
    _FUZZY_AVAILABLE = False

# fuzzy_report.decision uses LONG/SHORT/HOLD/NO_TRADE; Decision.action uses BUY/SELL/WAIT/NO_TRADE
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
    """
    از متن یک دلیل رد (مثلاً 'GATE_REJECTED: RISK_QUALITY_TOO_WEAK (μ_weak=0.96)')
    فقط نام Gate را استخراج می‌کند (مستقل از مقدار μ) تا در Failure Analysis
    بشود رد‌ها را بر اساس Gate گروه‌بندی کرد، نه بر اساس رشته‌ی کامل شامل عدد.
    """
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
                  min_history: int = 60, step_after_trade: bool = True) -> BacktestSummary:
    """
    توجه (Feature Flag): این تابع دیگر پارامتر use_fuzzy ندارد. تنها نقطه‌ی
    کنترل فعال/غیرفعال بودن لایه‌ی فازی پیشرفته، settings.FUZZY_BACKTEST_ENABLED
    است — هیچ فایل دیگری (از جمله همین فایل) اجازه‌ی override مستقل ندارد.
    وقتی False است: هیچ import و هیچ فراخوانی فازی رخ نمی‌دهد و رفتار دقیقاً
    برابر با نسخه‌ی Baseline (بدون فازی) است؛ Overhead عملاً صفر.
    """
    use_fuzzy = bool(settings.FUZZY_BACKTEST_ENABLED)
    base_df = bars_by_tf.get(base_tf)
    summary = BacktestSummary()
    if base_df is None or base_df.empty or len(base_df) < min_history + 5:
        return summary

    equity_curve = [0.0]
    i = min_history
    n = len(base_df)
    cooldown_until = {"BUY": None, "SELL": None}  # جهت -> اندیس کندلی که تا آن مسدود است

    fuzzy_scores: List[float] = []
    fuzzy_rejections: Dict[str, int] = {}
    # Task 1 سند کالیبراسیون (RSP_Fuzzy_Primary_Suspect_Calibration_Prompt):
    # Failure Analysis روی rejected trades -> برای هر معامله‌ی واقعی که فازی
    # رد کرده، gate_name -> {"wins": n, "losses": m} (شبیه‌سازی shadow، بدون
    # اثر روی equity/trade count).
    rejected_trade_outcomes: Dict[str, Dict[str, int]] = {}
    fuzzy_overrides = 0
    fuzzy_steps = 0

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
        # --- ROOT-CAUSE FIX (RSP_Fuzzy_Primary_Suspect_Calibration_Prompt) ---
        # قبلاً این بلوک روی *هر* کندل اجرا می‌شد (چه decision.action یک
        # کاندید واقعی BUY/SELL باشد چه WAIT/HOLD/NO_TRADE — که ~۹۸٪ کندل‌ها
        # همین حالت دوم بودند). چون run_fuzzy_decision با direction="NEUTRAL"
        # (یعنی وقتی crisp از قبل WAIT است) هرگز LONG/SHORT برنمی‌گرداند، خروجی
        # فازی روی این کندل‌ها هیچ‌وقت decision.action را به BUY/SELL تبدیل
        # نمی‌کرد و رفتار معاملاتی (trades/win_rate/net_return/PF/maxDD) کاملاً
        # بدون تغییر می‌ماند — اما سه اثر جانبی گمراه‌کننده داشت که دقیقاً همان
        # چیزی بود که در validation چندکوینه اشتباه‌برانگیز به نظر می‌رسید:
        #   1) fuzzy_rejection_reasons/fuzzy_steps/fuzzy_overrides روی جمعیتِ
        #      اشتباه (کندل‌های بدون سیگنال) جمع می‌شدند؛ در نتیجه Failure
        #      Analysis روی «rejected trades» واقعی که سند خواسته اساساً ممکن
        #      نبود (rejection_rate=98% گزارش می‌شد در حالی که هیچ معامله‌ی
        #      واقعی‌ای رد نشده بود).
        #   2) روی کندل‌های بدون سیگنال risk_plan=None است، پس _raw_risk_quality
        #      همیشه دقیقاً raw=0.10 (μ_weak≈۰.۹۶ ثابت) برمی‌گرداند — همین یک
        #      مقدار ثابت به‌تنهایی اکثریت رد‌های گزارش‌شده (RISK_QUALITY_TOO_WEAK)
        #      را در JSON خروجی می‌ساخت، بدون این‌که هیچ معامله‌ی واقعی رد شود.
        #   3) هزاران «fuzzy_overrides» گزارش‌شده در واقع فقط برچسب‌زنی دوباره‌ی
        #      WAIT -> NO_TRADE بود (هر دو یعنی «این کندل معامله نکن»)، نه یک
        #      override استراتژیک واقعی روی یک تصمیم معاملاتی.
        # پس این بلوک اکنون فقط وقتی اجرا می‌شود که crisp decision واقعاً یک
        # کاندید معامله (BUY/SELL) باشد؛ خروجی معاملاتی بایت‌به‌بایت یکسان
        # می‌ماند (چون خروجی فازی روی سایر کندل‌ها هرگز اثر نداشت)، فقط
        # دیاگ‌نوستیک‌ها اکنون روی جمعیت درست اندازه‌گیری می‌شوند.
        if use_fuzzy and _FUZZY_AVAILABLE and decision.action in ("BUY", "SELL"):
            original_action = decision.action
            try:
                pre_risk_plan = plan_risk(original_action, known_base, regime)
                integrated = integrate_fuzzy_decision(
                    coin="", crisp_decision=decision, regime=regime,
                    confluence=confluence, mtf=mtf, structure=regime.structure if regime else None,
                    risk_plan=pre_risk_plan, atr_pct=regime.perception.atr_pct if regime else 2.0,
                    fusion=fusion, contradiction=contradiction, confidence=confidence,
                )
                if integrated.used_fuzzy:
                    fuzzy_steps += 1
                    if integrated.fuzzy_report is not None:
                        fr = integrated.fuzzy_report
                        fuzzy_scores.append(fr.opportunity_score)
                        if fr.rejected_trade:
                            # نکته: قبلاً اینجا fr.notes[-1] خوانده می‌شد که می‌توانست بعداً
                            # توسط یادداشت‌های نامرتبط (مثلاً STABILITY_CHECK_FAILED که فقط
                            # یک flag است و هرگز rejected_trade را عوض نمی‌کند — نگاه کن به
                            # decision_controller.py) بازنویسی شود و Gate واقعیِ رد‌کننده را
                            # اشتباه گزارش کند. fr.primary_reason همیشه دقیقاً همان
                            # gate_reason خام _permission_gate است (بدون این ریسک)، پس
                            # منبع درست برای Failure Analysis (Task 2 سند) همین است.
                            reason = f"GATE_REJECTED: {fr.primary_reason}" if fr.primary_reason \
                                else (fr.notes[-1] if fr.notes else "UNKNOWN")
                            fuzzy_rejections[reason] = fuzzy_rejections.get(reason, 0) + 1
                            # --- Task 1: Failure Analysis روی rejected trades ---
                            # همین معامله‌ای که فازی رد کرده را (فقط برای
                            # دیاگ‌نوستیک — بدون اثر روی equity/trade count/
                            # cooldown) با همان risk_plan شبیه‌سازی می‌کنیم تا
                            # مشخص شود اگر واقعاً اجرا می‌شد WIN بود یا LOSS.
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
                        # Task 4 — Explainable Fuzzy AI: هر آنچه برای دیباگ یک تصمیم فازی لازم است
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
                pass  # honest fallback: keep the crisp decision if fuzzy fails on this bar

        if decision.action in ("BUY", "SELL"):
            until = cooldown_until.get(decision.action)
            if until is not None and i < until:
                # هنوز توی دوره‌ی خنک‌سازیِ همین جهت هستیم (بعد از STOP_LOSS_HIT اخیر) -> رد شو
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

    if use_fuzzy:
        summary.fuzzy_diagnostics = {
            "fuzzy_steps": fuzzy_steps,
            "fuzzy_overrides": fuzzy_overrides,
            "opportunity_score_min": round(min(fuzzy_scores), 2) if fuzzy_scores else None,
            "opportunity_score_max": round(max(fuzzy_scores), 2) if fuzzy_scores else None,
            "opportunity_score_avg": round(sum(fuzzy_scores) / len(fuzzy_scores), 2) if fuzzy_scores else None,
            "current_threshold": settings.FUZZY_OPPORTUNITY_THRESHOLD,
            "rejection_reasons": fuzzy_rejections,
            # Task 1-3 سند کالیبراسیون: نتیجه‌ی Failure Analysis روی rejected
            # trades واقعی، به تفکیک Gate — {"RISK_QUALITY_TOO_WEAK": {"wins": n, "losses": m}, ...}
            "rejected_trade_outcomes": rejected_trade_outcomes,
        }

    return summary
