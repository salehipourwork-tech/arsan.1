"""
RSP — fuzzy_core/__init__.py

Package initialization for the Adaptive Fuzzy Decision Engine.
All public APIs exported here for easy import.
"""

# Phase 27-28: Membership & Linguistic Variables
from .membership import (
    triangular, trapezoidal, gaussian, sigmoid,
    generalized_bell, s_shaped, z_shaped, pi_shaped,
    Term, LinguisticVariable,
    build_quality_variable,
    build_trend_quality_variable,
    build_momentum_quality_variable,
    build_entry_quality_variable,
    build_risk_quality_variable,
    build_volatility_quality_variable,
    build_market_stability_variable,
    build_signal_strength_variable,
    build_signal_confidence_variable,
    build_contradiction_severity_variable,
    build_opportunity_quality_variable,
    get_quality_variable,
    QUALITY_VARIABLE_REGISTRY,
)

# Phase 29-38: Quality Engines
from .quality_engines import (
    evaluate_trend_quality,
    evaluate_momentum_quality,
    evaluate_entry_quality,
    evaluate_risk_quality,
    evaluate_volatility_quality,
    evaluate_market_stability,
    evaluate_signal_strength,
    evaluate_signal_confidence,
    evaluate_contradiction_severity,
    evaluate_opportunity_quality,
)

# Phase 39-40: Rule Base
from .rule_base import (
    FuzzyRule,
    OPPORTUNITY_RULES,
    evaluate_rules,
    get_active_rules,
    get_rule_by_id,
)

# Phase 41: Conflict Resolution
from .conflict_resolution import (
    ConflictResolutionReport,
    detect_conflicts,
    resolve_conflicts,
)

# Phase 42-44: Inference, Aggregation, Defuzzification
from .inference import (
    FuzzyInferenceReport,
    run_fuzzy_inference,
    FuzzySignalReport,
    evaluate_signal_strength,
)

# Phase 45-50: Decision Controller
from .decision_controller import (
    FuzzyDecisionReport,
    DecisionHistory,
    run_fuzzy_decision,
    get_history,
)

# Reporting
from .reporting import (
    generate_fuzzy_report,
    generate_fuzzy_json,
)

__all__ = [
    # Membership
    "triangular", "trapezoidal", "gaussian", "sigmoid",
    "generalized_bell", "s_shaped", "z_shaped", "pi_shaped",
    "Term", "LinguisticVariable",
    "build_quality_variable",
    "get_quality_variable", "QUALITY_VARIABLE_REGISTRY",
    # Quality Engines
    "evaluate_trend_quality", "evaluate_momentum_quality",
    "evaluate_entry_quality", "evaluate_risk_quality",
    "evaluate_volatility_quality", "evaluate_market_stability",
    "evaluate_signal_strength", "evaluate_signal_confidence",
    "evaluate_contradiction_severity", "evaluate_opportunity_quality",
    # Rule Base
    "FuzzyRule", "OPPORTUNITY_RULES",
    "evaluate_rules", "get_active_rules", "get_rule_by_id",
    # Conflict Resolution
    "ConflictResolutionReport", "detect_conflicts", "resolve_conflicts",
    # Inference
    "FuzzyInferenceReport", "run_fuzzy_inference",
    "FuzzySignalReport",
    # Decision Controller
    "FuzzyDecisionReport", "DecisionHistory", "run_fuzzy_decision", "get_history",
    # Reporting
    "generate_fuzzy_report", "generate_fuzzy_json",
]
