"""
RSP — robustness/stress_test.py  (Phase 22: STRESS TEST)

دو رویکرد مکمل، هر دو صادقانه مستند:

1) performance_by_market_type(): از یک بک‌تست واقعی روی داده‌ی واقعی، هر
   معامله را بر اساس رژیمی که در لحظه‌ی ورود ثبت شده (BacktestTradeLog.regime)
   به یکی از دسته‌های Bull/Bear/Sideways/Crash/HighVol/LowVol/Breakout
   نگاشت می‌دهد و عملکرد را جداگانه گزارش می‌کند. این "واقعی" است چون از
   طبقه‌بندی واقعی Regime Engine روی داده‌ی واقعی می‌آید - نه شبیه‌سازی.

2) run_synthetic_scenarios(): برای تست *مهندسی* (نه ارزیابی بازار واقعی)،
   چند مسیر قیمت مصنوعی برچسب‌دار (Bull/Bear/Sideways/Crash/High-Vol/
   Low-Vol/False-Breakout/Sudden-Reversal) می‌سازد و موتور را رویشان اجرا
   می‌کند. این صرفاً برای این است که مطمئن شویم موتور در سناریوهای مختلف
   کرش نمی‌کند و رفتار منطقی نشان می‌دهد (مثلاً در Crash معامله نمی‌کند) -
   **معیار سنجش سودآوری واقعی بازار نیست** و این تفاوت در خروجی صریح
   اعلام می‌شود.
"""

from dataclasses import dataclass, field
from typing import Dict, List
import numpy as np
import pandas as pd

from RSP.backtest_engine.backtest_engine import BacktestSummary, run_backtest
from RSP.config import settings

REGIME_TO_MARKET_TYPE = {
    "STRONG_UPTREND": "BULL", "UPTREND": "BULL", "WEAK_UPTREND": "BULL",
    "STRONG_DOWNTREND": "BEAR", "DOWNTREND": "BEAR", "WEAK_DOWNTREND": "BEAR",
    "RANGE": "SIDEWAYS", "LOW_VOLATILITY": "SIDEWAYS",
    "CRASH": "CRASH",
    "HIGH_VOLATILITY": "HIGH_VOL",
    "BREAKOUT": "BREAKOUT", "FAKE_BREAKOUT": "FALSE_BREAKOUT",
    "RECOVERY": "SUDDEN_REVERSAL", "TRANSITION": "SUDDEN_REVERSAL",
    "BREAKDOWN": "BEAR",
    "UNKNOWN": "UNKNOWN",
}


@dataclass
class MarketTypePerformance:
    market_type: str
    trades: int
    win_rate: float
    net_return_pct: float
    average_trade_pct: float


@dataclass
class StressTestReport:
    by_market_type: List[MarketTypePerformance] = field(default_factory=list)
    weakest_market_type: str = ""
    notes: List[str] = field(default_factory=list)


def performance_by_market_type(summary: BacktestSummary) -> StressTestReport:
    report = StressTestReport()
    if not summary.trades:
        report.notes.append("هیچ معامله‌ای در بک‌تست ثبت نشده - گزارش قابل‌تولید نیست")
        return report

    buckets: Dict[str, list] = {}
    for t in summary.trades:
        mtype = REGIME_TO_MARKET_TYPE.get(t.regime, "UNKNOWN")
        buckets.setdefault(mtype, []).append(t)

    for mtype, trades in buckets.items():
        wins = sum(1 for t in trades if t.outcome == "WIN")
        net = sum(t.pnl_pct for t in trades)
        report.by_market_type.append(MarketTypePerformance(
            market_type=mtype, trades=len(trades),
            win_rate=round(wins / len(trades) * 100, 2),
            net_return_pct=round(net, 3),
            average_trade_pct=round(net / len(trades), 4),
        ))

    if report.by_market_type:
        worst = min(report.by_market_type, key=lambda x: x.average_trade_pct)
        report.weakest_market_type = worst.market_type

    covered = set(buckets.keys())
    missing = {"BULL", "BEAR", "SIDEWAYS", "CRASH", "HIGH_VOL", "BREAKOUT",
               "FALSE_BREAKOUT", "SUDDEN_REVERSAL"} - covered
    if missing:
        report.notes.append(f"در بازه‌ی داده‌ی این بک‌تست، هیچ معامله‌ای در شرایط "
                             f"{sorted(missing)} رخ نداد - نمی‌توان درباره‌ی عملکرد "
                             f"در آن شرایط نتیجه گرفت (نه خوب نه بد؛ صرفاً داده نیست).")
    return report


# ---------------------------------------------------------------------------
# Synthetic engineering scenarios (فقط برای اطمینان از رفتار موتور، نه سنجش سود)
# ---------------------------------------------------------------------------
def _base_ohlcv(n, freq, drift, vol, start_price=100.0, seed=None):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=n, freq=freq, tz="UTC")
    returns = rng.normal(drift, vol, n)
    close = start_price * np.cumprod(1 + returns)
    open_ = np.roll(close, 1)
    open_[0] = start_price
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.002, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.002, n)))
    # BUG FIX: volume used to be a fixed np.random.normal(1000, 250, n) unit
    # count regardless of start_price/MIN_VOLUME_USD. At start_price=100 that
    # is ~100k USD/bar notional, while backtest_engine's VOLUME_FILTER_ENABLED
    # gate (MIN_VOLUME_USD=1,000,000 by default) silently rejected every
    # single candidate trade in every scenario before it ever reached the
    # fuzzy/risk gates. run_synthetic_scenarios() therefore always returned
    # 0 trades for all 8 scenarios (BULL included) - the entire "engine
    # doesn't crash and behaves sensibly" self-test this module exists for
    # was never actually exercising a trade. Scale the synthetic volume so
    # its USD notional sits safely above the live threshold (with realistic
    # bar-to-bar variance, so the volume filter can still legitimately
    # reject a low-liquidity bar here and there).
    target_notional = max(settings.MIN_VOLUME_USD * 5.0, 1.0)
    volume_mean = target_notional / max(start_price, 1e-9)
    volume = np.abs(rng.normal(volume_mean, volume_mean * 0.25, n))
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume}, index=idx)


SYNTHETIC_SCENARIOS = {
    "BULL": dict(drift=0.0015, vol=0.006),
    "BEAR": dict(drift=-0.0015, vol=0.006),
    "SIDEWAYS": dict(drift=0.00005, vol=0.004),
    "HIGH_VOL": dict(drift=0.0, vol=0.02),
    "LOW_VOL": dict(drift=0.0002, vol=0.0015),
}


def _make_crash_scenario(n, freq, seed=None):
    rng = np.random.default_rng(seed)
    base = _base_ohlcv(n, freq, drift=0.0008, vol=0.005, seed=seed)
    crash_start = int(n * 0.6)
    crash_len = max(5, int(n * 0.1))
    factor = np.linspace(1.0, 0.55, crash_len)
    for col in ["open", "high", "low", "close"]:
        base.loc[base.index[crash_start:crash_start + crash_len], col] = \
            base[col].iloc[crash_start:crash_start + crash_len].values * factor
        base.loc[base.index[crash_start + crash_len:], col] = \
            base[col].iloc[crash_start + crash_len:].values * factor[-1]
    return base


def _make_false_breakout_scenario(n, freq, seed=None):
    base = _base_ohlcv(n, freq, drift=0.0001, vol=0.004, seed=seed)
    spike_idx = int(n * 0.5)
    spike_len = max(3, int(n * 0.03))
    base.loc[base.index[spike_idx:spike_idx + spike_len], "close"] *= 1.06
    base.loc[base.index[spike_idx:spike_idx + spike_len], "high"] *= 1.08
    # بازگشت سریع به رنج قبلی
    base.loc[base.index[spike_idx + spike_len:], "close"] = base["close"].iloc[spike_idx - 1]
    return base


def _make_sudden_reversal_scenario(n, freq, seed=None):
    half = n // 2
    down = _base_ohlcv(half, freq, drift=-0.0015, vol=0.006, seed=seed)
    up = _base_ohlcv(n - half, freq, drift=0.0018, vol=0.006,
                      start_price=float(down["close"].iloc[-1]), seed=(seed or 0) + 1)
    up.index = pd.date_range(down.index[-1] + pd.Timedelta(freq), periods=len(up), freq=freq, tz="UTC")
    return pd.concat([down, up])


def generate_scenario(kind: str, n: int = 1000, freq: str = "15min", seed: int = 1) -> pd.DataFrame:
    if kind == "CRASH":
        return _make_crash_scenario(n, freq, seed)
    if kind == "FALSE_BREAKOUT":
        return _make_false_breakout_scenario(n, freq, seed)
    if kind == "SUDDEN_REVERSAL":
        return _make_sudden_reversal_scenario(n, freq, seed)
    params = SYNTHETIC_SCENARIOS.get(kind)
    if not params:
        raise ValueError(f"Unknown synthetic scenario: {kind}")
    return _base_ohlcv(n, freq, **params, seed=seed)


def run_synthetic_scenarios(scenario_kinds=None, n=1200, seed=1) -> Dict[str, BacktestSummary]:
    """
    فقط برای تست مهندسی موتور - داده‌ی مصنوعی است، نه ارزیابی سودآوری واقعی.
    برای هر سناریو، تایم‌فریم‌های ۴گانه از resample همان مسیر مصنوعی ساخته
    می‌شوند (تا mtf_brain هم قابل اجرا باشد).
    """
    scenario_kinds = scenario_kinds or list(SYNTHETIC_SCENARIOS.keys()) + \
        ["CRASH", "FALSE_BREAKOUT", "SUDDEN_REVERSAL"]
    results = {}
    for kind in scenario_kinds:
        base_15m = generate_scenario(kind, n=n, freq="15min", seed=seed)
        bars_by_tf = {
            "15M": base_15m,
            "1H": base_15m.resample("1h").agg({"open": "first", "high": "max", "low": "min",
                                                 "close": "last", "volume": "sum"}).dropna(),
            "4H": base_15m.resample("4h").agg({"open": "first", "high": "max", "low": "min",
                                                 "close": "last", "volume": "sum"}).dropna(),
            "1D": base_15m.resample("1D").agg({"open": "first", "high": "max", "low": "min",
                                                 "close": "last", "volume": "sum"}).dropna(),
        }
        results[kind] = run_backtest(bars_by_tf, base_tf="15M", min_history=60)
    return results
