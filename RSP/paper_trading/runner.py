#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP — paper_trading/runner.py

یک چرخه‌ی validation روی داده‌ی زنده (بدون synthetic، بدون سرمایه‌ی واقعی).
هر اجرا:
  1) پارامترهای baseline قفل‌شده را عیناً از گزارش کالیبراسیون اعمال می‌کند
     (بدون تغییر/تیون — locked_config.py این را تضمین می‌کند).
  2) داده‌ی زنده‌ی هر کوین را می‌گیرد (RSP.ingestion.data_universe — همان
     مسیر واقعی fetch، نه synthetic).
  3) دقیقاً همان pipeline تصمیم‌گیری RSP/main.py را اجرا می‌کند
     (quality → regime → confluence → mtf → fusion → contradiction →
     confidence → decision → risk_plan → trade_quality).
  4) هر تصمیم را با جزئیات کامل ثبت می‌کند — شامل NO_TRADE/WAIT.
  5) پوزیشن‌های کاغذی باز را با آخرین کندل چک می‌کند؛ اگر TP/SL خورده،
     می‌بندد و در closed_trades ثبت می‌کند. هیچ سفارشی به صرافی ارسال نمی‌شود.

طراحی عمداً idempotent-per-cycle است: این اسکریپت را با cron/Task Scheduler
هر ۱۵ دقیقه (هم‌زمان با بسته‌شدن کندل base_tf=15M) صدا بزنید. این خودش حلقه‌ی
بی‌نهایت اجرا نمی‌کند.
"""

import argparse
import sys
import traceback
from typing import Any, Dict, List, Optional

from RSP.config import settings
from RSP.ingestion.data_universe import build_data_universe
from RSP.preprocessing.quality_engine import check_quality
from RSP.regime_engine.regime_engine import determine_regime
from RSP.signal_engine.confluence import analyze_confluence
from RSP.multi_timeframe.mtf_brain import analyze_mtf
from RSP.signal_fusion.fusion_engine import fuse_signals
from RSP.contradiction_engine.contradiction_engine import detect_contradictions
from RSP.confidence_engine.confidence_engine import calculate_confidence
from RSP.decision_engine.decision_brain import decide
from RSP.risk_engine.risk_engine import plan_risk
from RSP.risk_engine.trade_quality import assess_trade_quality
from RSP.strategy_lab.selector import select_strategy

from RSP.paper_trading.locked_config import load_locked_baseline, apply_locked_baseline
from RSP.paper_trading import ledger


def _serialize_risk_plan(rp) -> Optional[Dict[str, Any]]:
    if rp is None:
        return None
    return {
        "action": rp.action, "entry": rp.entry, "stop_loss": rp.stop_loss,
        "take_profit": rp.take_profit, "risk_reward": rp.risk_reward,
        "position_size_pct": rp.position_size_pct, "valid": rp.valid,
        "reason": rp.reason, "atr": rp.atr, "notes": list(rp.notes or []),
    }


def _check_open_positions(coin: str, latest_close: float, latest_high: float,
                           latest_low: float, bar_ts: str) -> List[Dict[str, Any]]:
    """
    پوزیشن‌های باز را با آخرین کندل چک می‌کند. اگر SL یا TP لمس شده، پوزیشن
    بسته و در closed_trades ثبت می‌شود. منطق conservative: اگر هر دو در یک
    کندل لمس شدند و جهت مشخص نبود، SL برنده فرض می‌شود (محافظه‌کارانه‌تر از
    فرض‌کردن بهترین حالت برای خودمان).
    """
    positions = ledger.load_open_positions(coin)
    still_open = []
    closed_now = []
    for pos in positions:
        direction = pos["direction"]  # "LONG" | "SHORT"
        sl, tp = pos["stop_loss"], pos["take_profit"]
        hit_sl = hit_tp = False
        if direction == "LONG":
            hit_sl = latest_low <= sl
            hit_tp = latest_high >= tp
        else:
            hit_sl = latest_high >= sl
            hit_tp = latest_low <= tp

        if hit_sl and hit_tp:
            outcome, exit_price = "SL", sl  # محافظه‌کارانه
        elif hit_sl:
            outcome, exit_price = "SL", sl
        elif hit_tp:
            outcome, exit_price = "TP", tp
        else:
            still_open.append(pos)
            continue

        entry = pos["entry"]
        if direction == "LONG":
            pnl_pct = (exit_price - entry) / entry * 100.0
        else:
            pnl_pct = (entry - exit_price) / entry * 100.0

        trade = dict(pos)
        trade.update({
            "outcome": outcome, "exit_price": exit_price, "pnl_pct": pnl_pct,
            "closed_at_bar": bar_ts, "r_multiple": (
                pnl_pct / pos["risk_pct_at_entry"] if pos.get("risk_pct_at_entry") else None
            ),
        })
        ledger.append_closed_trade(coin, trade)
        closed_now.append(trade)

    ledger.save_open_positions(coin, still_open)
    return closed_now


def run_one_cycle(coin: str, locked_report_path: Optional[str] = None) -> Dict[str, Any]:
    locked = load_locked_baseline(coin, report_path=locked_report_path)
    restore = apply_locked_baseline(locked)
    try:
        universe = build_data_universe(coin, lookback_days=settings.DEFAULT_LOOKBACK_DAYS)
        base_df = universe.bars.get("15M")
        if base_df is None or base_df.empty:
            record = {
                "coin": coin, "action": "NO_TRADE",
                "why": ["ERROR: empty/missing live 15M data from ingestion"],
                "source_used": universe.source_used.get("15M"),
                "locked_report": locked.report_path,
            }
            ledger.append_decision(coin, record)
            return record

        source_used = universe.source_used.get("15M", "unknown")
        bar_ts = str(base_df.index[-1])

        # --- close any open paper positions against this latest candle first ---
        closed = _check_open_positions(
            coin, float(base_df["close"].iloc[-1]), float(base_df["high"].iloc[-1]),
            float(base_df["low"].iloc[-1]), bar_ts,
        )

        base_quality = check_quality(base_df, "15M")
        regime = determine_regime(base_df)
        confluence = analyze_confluence(base_df, regime)
        mtf = analyze_mtf(universe.bars)
        fusion = fuse_signals(regime, confluence, mtf)
        contradiction = detect_contradictions(fusion, mtf)
        confidence = calculate_confidence(fusion, mtf, base_quality, None, contradiction, regime)
        decision = decide(regime, fusion, mtf, contradiction, confidence,
                           base_quality.quality_ok if base_quality else False)

        selection = select_strategy(fusion, regime, mtf) if regime else None
        risk_plan = None
        trade_quality = None
        opened_position = None

        if decision.action in ("BUY", "SELL"):
            risk_plan = plan_risk(decision.action, base_df, regime)
            trade_quality = assess_trade_quality(risk_plan, base_quality, regime, confluence)
            quality_ok = trade_quality.overall_score >= settings.MIN_TRADE_QUALITY_SCORE
            if not (risk_plan.valid and quality_ok):
                decision.action = "NO_TRADE"
                decision.why.append(
                    f"Trade Quality/Risk Gate: risk_ok={risk_plan.valid}, quality_ok={quality_ok}"
                )
            elif risk_plan.entry and risk_plan.stop_loss:
                direction = "LONG" if decision.action == "BUY" else "SHORT"
                risk_pct = abs(risk_plan.entry - risk_plan.stop_loss) / risk_plan.entry * 100.0
                opened_position = {
                    "coin": coin, "direction": direction, "entry": risk_plan.entry,
                    "stop_loss": risk_plan.stop_loss, "take_profit": risk_plan.take_profit,
                    "risk_reward": risk_plan.risk_reward, "risk_pct_at_entry": risk_pct,
                    "opened_at_bar": bar_ts, "opened_at": ledger.now_iso(),
                    "regime_at_entry": regime.regime if regime else None,
                    "confidence_at_entry": confidence.confidence if confidence else None,
                    "strategy": selection,
                }
                positions = ledger.load_open_positions(coin)
                positions.append(opened_position)
                ledger.save_open_positions(coin, positions)

        record = {
            "coin": coin, "bar_ts": bar_ts, "source_used": source_used,
            "locked_report": locked.report_path, "winner_mode": locked.winner_mode,
            "action": decision.action, "why": list(decision.why),
            "missing_confirmation": list(decision.missing_confirmation),
            "regime": regime.regime if regime else None,
            "confidence": confidence.confidence if confidence else None,
            "confidence_components": confidence.components if confidence else None,
            "strategy_selected": selection,
            "risk_plan": _serialize_risk_plan(risk_plan),
            "trade_quality_score": trade_quality.overall_score if trade_quality else None,
            "data_quality_ok": base_quality.quality_ok if base_quality else None,
            "opened_paper_position": opened_position,
            "closed_paper_trades_this_cycle": closed,
        }
        ledger.append_decision(coin, record)
        return record
    except Exception as e:
        err_record = {
            "coin": coin, "action": "NO_TRADE",
            "why": [f"ERROR during validation cycle: {e}"],
            "traceback": traceback.format_exc(), "locked_report": locked.report_path,
        }
        ledger.append_decision(coin, err_record)
        return err_record
    finally:
        restore()  # پارامترها همیشه به حالت قبل از این چرخه برمی‌گردند


def main():
    ap = argparse.ArgumentParser(
        description="RSP paper-trading / live-data validation cycle. Read-only w.r.t. "
                    "calibrated parameters — never tunes anything."
    )
    ap.add_argument("--coins", nargs="+", default=["bitcoin"],
                     help="Coin ids to run this validation cycle for.")
    ap.add_argument("--report", default=None,
                     help="Path to a specific calibration report JSON. Defaults to the "
                          "latest bitcoin_*.json-style report for each coin.")
    args = ap.parse_args()

    exit_code = 0
    for coin in args.coins:
        try:
            record = run_one_cycle(coin, locked_report_path=args.report)
            print(f"[{coin}] action={record.get('action')} regime={record.get('regime')} "
                  f"confidence={record.get('confidence')} "
                  f"opened={'yes' if record.get('opened_paper_position') else 'no'} "
                  f"closed_this_cycle={len(record.get('closed_paper_trades_this_cycle') or [])}")
        except Exception as e:
            print(f"[{coin}] FATAL: {e}", file=sys.stderr)
            exit_code = 1
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
