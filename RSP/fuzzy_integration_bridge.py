"""
RSP — fuzzy_integration_bridge.py

این فایل تمام مراحل اتصال موتور فازی به پایپ‌لاین موجود را پیاده‌سازی می‌کند.
کافی است این فایل را در RSP/fuzzy_integration_bridge.py کپی کنید
و سپس ۳ خط کد را به main.py اضافه کنید.
"""
from typing import Optional, Dict, Any
from dataclasses import dataclass, field

from RSP.config import settings
from RSP.fuzzy_core import (
    run_fuzzy_decision,
    generate_fuzzy_report,
    generate_fuzzy_json,
    FuzzyDecisionReport,
)

# For type hints (import existing classes without circular dependency issues)
try:
    from RSP.regime_engine.regime_engine import RegimeReport
    from RSP.signal_engine.confluence import ConfluenceReport
    from RSP.multi_timeframe.mtf_brain import MTFReport
    from RSP.market_structure.structure_engine import StructureReport
    from RSP.risk_engine.risk_engine import RiskPlan
    from RSP.signal_fusion.fusion_engine import FusionReport
    from RSP.contradiction_engine.contradiction_engine import ContradictionReport
    from RSP.confidence_engine.confidence_engine import ConfidenceReport
    from RSP.decision_engine.decision_brain import Decision as DecisionReport
except ImportError:
    RegimeReport = Any
    ConfluenceReport = Any
    MTFReport = Any
    StructureReport = Any
    RiskPlan = Any
    FusionReport = Any
    ContradictionReport = Any
    ConfidenceReport = Any
    DecisionReport = Any


@dataclass
class IntegratedDecision:
    """خروجی یکپارچه: crisp + fuzzy + comparison"""
    final_direction: str = "NO_TRADE"
    final_confidence: float = 0.0
    final_reason: str = ""
    fuzzy_enabled: bool = False
    crisp_decision: Optional[DecisionReport] = None
    fuzzy_report: Optional[FuzzyDecisionReport] = None
    fuzzy_text_report: str = ""
    fuzzy_json_report: Optional[Dict] = None
    comparison_notes: list = field(default_factory=list)
    used_fuzzy: bool = False


# Decision.action از واژگان BUY/SELL/WAIT/HOLD/NO_TRADE استفاده می‌کند (نه .direction که
# اصلاً وجود ندارد). این نگاشت، action را به واژگان مورد نیاز موتور فازی تبدیل می‌کند.
_ACTION_TO_FUZZY_DIRECTION = {"BUY": "BULLISH", "SELL": "BEARISH"}   # ورودی run_fuzzy_decision
_ACTION_TO_FUZZY_VOCAB = {"BUY": "LONG", "SELL": "SHORT", "HOLD": "HOLD",
                           "WAIT": "NO_TRADE", "NO_TRADE": "NO_TRADE"}


def _crisp_action(crisp_decision) -> str:
    return getattr(crisp_decision, "action", "NO_TRADE")


def integrate_fuzzy_decision(
    coin: str,
    crisp_decision: DecisionReport,
    regime: RegimeReport,
    confluence: ConfluenceReport,
    mtf: MTFReport,
    structure: StructureReport,
    risk_plan: Optional[RiskPlan],
    atr_pct: float,
    fusion: FusionReport,
    contradiction: ContradictionReport,
    confidence: ConfidenceReport,
) -> IntegratedDecision:
    """
    این تابع مراحل ۱ تا ۴ فایل راهنما را اجرا می‌کند:
      1. اجرای موتور فازی
      2. انتخاب بین crisp و fuzzy
      3. جمع‌آوری داده مقایسه‌ای
      4. تولید گزارش

    ورودی: تمام گزارش‌های موجود + تصمیم crisp
    خروجی: IntegratedDecision یکپارچه
    """
    result = IntegratedDecision()
    result.crisp_decision = crisp_decision
    result.fuzzy_enabled = settings.FUZZY_BACKTEST_ENABLED

    # --- Step 1: Run Fuzzy Engine (if enabled) ---
    fuzzy_report: Optional[FuzzyDecisionReport] = None
    if settings.FUZZY_BACKTEST_ENABLED:
        try:
            fuzzy_report = run_fuzzy_decision(
                coin=coin,
                regime=regime,
                confluence=confluence,
                mtf=mtf,
                structure=structure,
                risk_plan=risk_plan,
                atr_pct=atr_pct,
                fusion=fusion,
                contradiction=contradiction,
                confidence=confidence,
                direction=_ACTION_TO_FUZZY_DIRECTION.get(_crisp_action(crisp_decision), "NEUTRAL"),
            )
        except Exception as e:
            # If fuzzy fails, log and fall back to crisp
            result.comparison_notes.append(f"FUZZY_ENGINE_ERROR: {str(e)}")
            result.fuzzy_enabled = False

    result.fuzzy_report = fuzzy_report

    # --- Step 2: Choose Final Decision ---
    if settings.FUZZY_BACKTEST_ENABLED and fuzzy_report is not None:
        # Use fuzzy decision
        result.final_direction = fuzzy_report.decision
        result.final_confidence = fuzzy_report.confidence
        result.final_reason = fuzzy_report.primary_reason
        result.used_fuzzy = True

        # Generate reports
        result.fuzzy_text_report = generate_fuzzy_report(fuzzy_report, coin)
        result.fuzzy_json_report = generate_fuzzy_json(fuzzy_report)

        # Comparison notes
        crisp_dir = _ACTION_TO_FUZZY_VOCAB.get(_crisp_action(crisp_decision), "NO_TRADE")
        crisp_conf = (crisp_decision.confidence / 100.0) if hasattr(crisp_decision, "confidence") else 0.0

        if crisp_dir != fuzzy_report.decision:
            result.comparison_notes.append(
                f"FUZZY_OVERRIDE: crisp={crisp_dir} -> fuzzy={fuzzy_report.decision} "
                f"(score={fuzzy_report.opportunity_score:.1f})"
            )
        else:
            result.comparison_notes.append(
                f"FUZZY_AGREE: both={fuzzy_report.decision} "
                f"(fuzzy_score={fuzzy_report.opportunity_score:.1f}, crisp_conf={crisp_conf:.2f})"
            )

        # Log if trade was rejected by fuzzy gate
        if fuzzy_report.rejected_trade and crisp_dir in ("LONG", "SHORT"):
            result.comparison_notes.append(
                f"FUZZY_REJECTED_CRISP: crisp wanted {crisp_dir} but fuzzy said NO_TRADE"
            )

    else:
        # Fallback to crisp
        result.final_direction = _ACTION_TO_FUZZY_VOCAB.get(_crisp_action(crisp_decision), "NO_TRADE")
        result.final_confidence = (crisp_decision.confidence / 100.0) if hasattr(crisp_decision, "confidence") else 0.0
        result.final_reason = crisp_decision.reason if hasattr(crisp_decision, "reason") else ""
        result.used_fuzzy = False
        result.comparison_notes.append("FUZZY_DISABLED: using crisp decision")

    return result


# ---------------------------------------------------------------------------
# Helper for backtest comparison collection
# ---------------------------------------------------------------------------

def create_comparison_record(
    timestamp: str,
    integrated: IntegratedDecision,
    price: float,
) -> Dict[str, Any]:
    """
    برای جمع‌آوری داده مقایسه‌ای در بک‌تست.
    این dict را در لیست comparison_results ذخیره کن.
    """
    return {
        "timestamp": timestamp,
        "price": price,
        "crisp_direction": _ACTION_TO_FUZZY_VOCAB.get(_crisp_action(integrated.crisp_decision), None) if integrated.crisp_decision else None,
        "crisp_confidence": (integrated.crisp_decision.confidence / 100.0) if integrated.crisp_decision and hasattr(integrated.crisp_decision, "confidence") else None,
        "fuzzy_direction": integrated.fuzzy_report.decision if integrated.fuzzy_report else None,
        "fuzzy_confidence": integrated.fuzzy_report.confidence if integrated.fuzzy_report else None,
        "fuzzy_opportunity_score": integrated.fuzzy_report.opportunity_score if integrated.fuzzy_report else None,
        "fuzzy_rejected": integrated.fuzzy_report.rejected_trade if integrated.fuzzy_report else None,
        "final_direction": integrated.final_direction,
        "used_fuzzy": integrated.used_fuzzy,
        "comparison_notes": integrated.comparison_notes,
        "fuzzy_json": integrated.fuzzy_json_report,
    }


# ---------------------------------------------------------------------------
# Helper for report text generation
# ---------------------------------------------------------------------------

def append_fuzzy_to_report(existing_report_text: str, integrated: IntegratedDecision) -> str:
    """
    افزودن بخش فازی به گزارش نهایی متنی.
    """
    if not integrated.fuzzy_text_report:
        return existing_report_text

    separator = "\n" + "=" * 60 + "\n"
    fuzzy_section = separator
    fuzzy_section += "FUZZY DECISION LAYER (Phases 27-50)\n"
    fuzzy_section += "=" * 60 + "\n"
    fuzzy_section += integrated.fuzzy_text_report
    fuzzy_section += "\n"

    # Add comparison summary
    if integrated.comparison_notes:
        fuzzy_section += "\nCOMPARISON NOTES:\n"
        for note in integrated.comparison_notes:
            fuzzy_section += f"  • {note}\n"

    return existing_report_text + fuzzy_section
