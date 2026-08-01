"""
RSP — risk_engine/trade_quality.py  (Phase 17: TRADE QUALITY ENGINE)

قبل از ورود، سیگنال را از چند زاویه‌ی مستقل ارزیابی می‌کند:
  Signal Quality   <- confidence + agreement
  Market Quality   <- تناسب رژیم با استراتژی انتخابی
  Risk Quality     <- risk_reward نسبت به حداقل قابل‌قبول
  Data Quality     <- از preprocessing
  Liquidity Quality <- در دسترس نیست با منبع فعلی -> UNKNOWN (خنثی، نه امتیازدهی جعلی)

اگر امتیاز نهایی کمتر از آستانه باشد: NO_TRADE.
"""

from dataclasses import dataclass, field
from typing import List, Optional

from RSP.config import settings


@dataclass
class TradeQualityReport:
    score: float = 0.0
    components: dict = field(default_factory=dict)
    passed: bool = False
    reasons: List[str] = field(default_factory=list)


def evaluate_trade_quality(confidence_score: float, data_quality_score: float,
                            risk_reward: Optional[float], strategy_match: bool) -> TradeQualityReport:
    report = TradeQualityReport()

    signal_quality = confidence_score  # از قبل 0..100

    market_quality = 90.0 if strategy_match else 40.0

    if risk_reward is None:
        risk_quality = 0.0
        report.reasons.append("Risk/Reward محاسبه نشده -> کیفیت ریسک صفر در نظر گرفته شد")
    else:
        risk_quality = min(100.0, max(0.0, (risk_reward / settings.TAKE_PROFIT_RR_TARGET) * 70))

    data_quality = data_quality_score

    liquidity_quality = None  # UNKNOWN - صادقانه در محاسبه شرکت داده نمی‌شود

    components = {
        "signal_quality": round(signal_quality, 1),
        "market_quality": round(market_quality, 1),
        "risk_quality": round(risk_quality, 1),
        "data_quality": round(data_quality, 1),
        "liquidity_quality": "DATA_MISSING",
    }
    report.components = components

    weights = {"signal_quality": 0.35, "market_quality": 0.20, "risk_quality": 0.25, "data_quality": 0.20}
    score = sum(components[k] * weights[k] for k in weights)
    report.score = round(score, 1)
    report.passed = report.score >= settings.MIN_TRADE_QUALITY_SCORE

    if not report.passed:
        report.reasons.append(f"Trade Quality Score={report.score} کمتر از آستانه {settings.MIN_TRADE_QUALITY_SCORE} -> NO_TRADE")

    return report
