"""
RSP — multi_timeframe/mtf_brain.py  (Phase 6: MULTI-TIMEFRAME BRAIN)

1D  -> Context (زمینه‌ی کلی)
4H  -> Trend (جهت روند)
1H  -> تاییدکننده‌ی کمکی روند
15M -> Entry (نقطه‌ی ورود)

اگر تایم‌فریم‌ها هم‌جهت نباشند، به‌جای صدور کورکورانه‌ی BUY/SELL، نتیجه
باید "WAIT_FOR_CONFIRMATION" باشد.
"""

from dataclasses import dataclass, field
from typing import Dict, List
import pandas as pd

from RSP.regime_engine.perception import perceive_market


BULLISH_STATES = {"STRONG_UPTREND", "UPTREND", "WEAK_UPTREND", "RECOVERY", "BREAKOUT"}
BEARISH_STATES = {"STRONG_DOWNTREND", "DOWNTREND", "WEAK_DOWNTREND", "BREAKDOWN", "CRASH"}


@dataclass
class MTFReport:
    per_timeframe_bias: Dict[str, str] = field(default_factory=dict)   # tf -> BULLISH/BEARISH/NEUTRAL
    per_timeframe_state: Dict[str, str] = field(default_factory=dict)  # tf -> regime state
    context_bias: str = "NEUTRAL"     # از 1D
    trend_bias: str = "NEUTRAL"       # از 4H (+1H)
    entry_bias: str = "NEUTRAL"       # از 15M
    aligned: bool = False
    consensus_score: float = 0.0      # -1..+1
    summary: str = ""
    recommendation: str = "WAIT_FOR_CONFIRMATION"


def _bias_from_state(state: str) -> str:
    if state in BULLISH_STATES:
        return "BULLISH"
    if state in BEARISH_STATES:
        return "BEARISH"
    return "NEUTRAL"


def analyze_mtf(bars_by_tf: Dict[str, pd.DataFrame]) -> MTFReport:
    report = MTFReport()
    biases = {}
    for tf, df in bars_by_tf.items():
        if df is None or df.empty:
            report.per_timeframe_state[tf] = "UNKNOWN"
            report.per_timeframe_bias[tf] = "NEUTRAL"
            continue
        perception = perceive_market(df)
        report.per_timeframe_state[tf] = perception.state
        bias = _bias_from_state(perception.state)
        report.per_timeframe_bias[tf] = bias
        biases[tf] = bias

    report.context_bias = report.per_timeframe_bias.get("1D", "NEUTRAL")
    h4 = report.per_timeframe_bias.get("4H", "NEUTRAL")
    h1 = report.per_timeframe_bias.get("1H", "NEUTRAL")
    report.trend_bias = h4 if h4 != "NEUTRAL" else h1
    report.entry_bias = report.per_timeframe_bias.get("15M", "NEUTRAL")

    all_biases = [report.context_bias, report.trend_bias, report.entry_bias]
    n_bull = all_biases.count("BULLISH")
    n_bear = all_biases.count("BEARISH")

    # طبق مثال خود اسپک: "HIGHER TF BULLISH, MID TF NEUTRAL, LOWER TF BEARISH -> WAIT"
    # یعنی تضاد وقتی است که واقعاً یک تایم‌فریم *خلاف* بقیه باشد، نه وقتی یکی‌شان
    # صرفاً NEUTRAL است. NEUTRAL بودن تایم‌فریم بالا (که معمولاً کندتر واکنش نشان
    # می‌دهد) نباید به‌تنهایی هم‌جهتی تایم‌فریم‌های سریع‌تر را باطل کند.
    has_opposition = n_bull > 0 and n_bear > 0
    has_direction = (n_bull + n_bear) > 0
    report.aligned = has_direction and not has_opposition
    report.consensus_score = round((n_bull - n_bear) / 3.0, 3)

    report.summary = (f"1D={report.context_bias}, 4H/1H={report.trend_bias}, 15M={report.entry_bias}")

    if report.aligned and n_bull > n_bear:
        report.recommendation = "ALIGNED_BULLISH"
    elif report.aligned and n_bear > n_bull:
        report.recommendation = "ALIGNED_BEARISH"
    else:
        report.recommendation = "WAIT_FOR_CONFIRMATION"

    return report
