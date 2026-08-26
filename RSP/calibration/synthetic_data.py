#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP.calibration.synthetic_data

Offline OHLCV generator so the calibration system can be exercised
end-to-end in environments without exchange/CoinGecko network access
(exactly the sandbox limitation already documented in RSP/README.md).
Reuses the same generation approach as
RSP.robustness.stress_test._base_ohlcv, but concatenates several regimes
(bull / sideways / bear / high-vol / recovery) back to back into one long
series so a walk-forward protocol with multiple folds + a final holdout
actually has enough bars and enough regime variety to be meaningful as a
*mechanical* test of the calibration code — NOT a substitute for a real
run on live market data. run_calibration.py prints this distinction
explicitly whenever --synthetic is used.
"""

from typing import Dict
import numpy as np
import pandas as pd

from RSP.config import settings


def _segment(n, drift, vol, start_price, seed) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    returns = rng.normal(drift, vol, n)
    close = start_price * np.cumprod(1 + returns)
    open_ = np.roll(close, 1)
    open_[0] = start_price
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.002, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.002, n)))
    target_notional = max(settings.MIN_VOLUME_USD * 5.0, 1.0)
    volume_mean = target_notional / max(start_price, 1e-9)
    volume = np.abs(rng.normal(volume_mean, volume_mean * 0.25, n))
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})


REGIME_SEQUENCE = [
    ("bull", 0.0012, 0.006),
    ("sideways", 0.00005, 0.004),
    ("bear", -0.0013, 0.006),
    ("high_vol", 0.0002, 0.018),
    ("recovery", 0.0016, 0.007),
    ("sideways2", 0.0000, 0.0035),
]


def build_synthetic_universe(days: int = 90, seed: int = 7) -> Dict[str, pd.DataFrame]:
    bars_per_day_15m = 96
    total_bars = max(4000, days * bars_per_day_15m)  # calibration needs more bars than a
                                                       # single live --backtest run to fit
                                                       # IS+purge+OOS+holdout folds
    n_segments = len(REGIME_SEQUENCE)
    seg_len = total_bars // n_segments

    segments = []
    price = 100.0
    for i, (_name, drift, vol) in enumerate(REGIME_SEQUENCE):
        seg = _segment(seg_len, drift, vol, price, seed + i)
        segments.append(seg)
        price = float(seg["close"].iloc[-1])
    base_15m = pd.concat(segments, ignore_index=True)
    idx = pd.date_range("2026-01-01", periods=len(base_15m), freq="15min", tz="UTC")
    base_15m.index = idx

    bars_by_tf = {
        "15M": base_15m,
        "1H": base_15m.resample("1h").agg({"open": "first", "high": "max", "low": "min",
                                             "close": "last", "volume": "sum"}).dropna(),
        "4H": base_15m.resample("4h").agg({"open": "first", "high": "max", "low": "min",
                                             "close": "last", "volume": "sum"}).dropna(),
        "1D": base_15m.resample("1D").agg({"open": "first", "high": "max", "low": "min",
                                             "close": "last", "volume": "sum"}).dropna(),
    }
    return bars_by_tf
