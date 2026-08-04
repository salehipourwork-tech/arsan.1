"""
RSP — phase_registry.py (COMPLETE: Phases 01-50)

این فایل کامل و مستقل است. شامل:
  - Phases 01-26: لایه‌های Data, Market Representation, Regime, MTF
  - Phases 27-50: لایه‌های Fuzzy Intelligence Core, Rule System, Decision Control

کافی است این فایل را در RSP/phase_registry.py کپی کنید.
"""
from dataclasses import dataclass
from typing import Dict, List

@dataclass
class PhaseRecord:
    phase_id: str
    name: str
    module: str
    status: str
    inputs: List[str]
    outputs: List[str]
    success_metric: str
    failure_mode: str

PHASE_REGISTRY: Dict[str, PhaseRecord] = {}

# =============================================================================
# LAYER 1 — DATA FOUNDATION (Phases 01-08)
# =============================================================================

PHASE_REGISTRY["PHASE_01"] = PhaseRecord(
    phase_id="PHASE_01",
    name="Data Universe",
    module="RSP.ingestion.data_universe",
    status="active",
    inputs=["config_universe"],
    outputs=["asset_universe_list"],
    success_metric="Universe populated with >=1 assets",
    failure_mode="Empty universe -> system halt",
)

PHASE_REGISTRY["PHASE_02"] = PhaseRecord(
    phase_id="PHASE_02",
    name="Data Ingestion",
    module="RSP.ingestion.multi_source_router",
    status="active",
    inputs=["asset_symbol", "timeframe"],
    outputs=["raw_ohlcv_df"],
    success_metric="Data fetched from at least 1 source",
    failure_mode="All sources fail -> empty df",
)

PHASE_REGISTRY["PHASE_03"] = PhaseRecord(
    phase_id="PHASE_03",
    name="Data Validation",
    module="RSP.preprocessing.quality_engine",
    status="active",
    inputs=["raw_ohlcv_df"],
    outputs=["validated_df", "validation_flags"],
    success_metric="No critical validation errors",
    failure_mode="Critical errors -> data rejected",
)

PHASE_REGISTRY["PHASE_04"] = PhaseRecord(
    phase_id="PHASE_04",
    name="Data Quality Scoring",
    module="RSP.preprocessing.quality_engine",
    status="active",
    inputs=["validated_df"],
    outputs=["quality_score", "quality_flags"],
    success_metric="Quality score >= threshold",
    failure_mode="Low quality -> warning or halt",
)

PHASE_REGISTRY["PHASE_05"] = PhaseRecord(
    phase_id="PHASE_05",
    name="Missing Data Handling",
    module="RSP.preprocessing.quality_engine",
    status="active",
    inputs=["validated_df", "quality_flags"],
    outputs=["imputed_df", "missing_report"],
    success_metric="Gaps filled or flagged",
    failure_mode="Excessive gaps -> data rejected",
)

PHASE_REGISTRY["PHASE_06"] = PhaseRecord(
    phase_id="PHASE_06",
    name="Outlier Detection",
    module="RSP.preprocessing.quality_engine",
    status="active",
    inputs=["ohlcv_df"],
    outputs=["outlier_flags", "cleaned_df"],
    success_metric="Outliers detected and handled",
    failure_mode="Missed outliers -> distorted indicators",
)

PHASE_REGISTRY["PHASE_07"] = PhaseRecord(
    phase_id="PHASE_07",
    name="Market Microstructure",
    module="RSP.preprocessing.quality_engine",
    status="active",
    inputs=["ohlcv_df"],
    outputs=["liquidity_flags", "spread_estimate"],
    success_metric="Microstructure analyzed",
    failure_mode="Missing data -> neutral flags",
)

PHASE_REGISTRY["PHASE_08"] = PhaseRecord(
    phase_id="PHASE_08",
    name="Data Timestamp Integrity",
    module="RSP.preprocessing.quality_engine",
    status="active",
    inputs=["ohlcv_df"],
    outputs=["timestamp_integrity_flag"],
    success_metric="Timestamps continuous and ordered",
    failure_mode="Gaps or duplicates -> flagged",
)

# =============================================================================
# LAYER 2 — MARKET REPRESENTATION (Phases 09-15)
# =============================================================================

PHASE_REGISTRY["PHASE_09"] = PhaseRecord(
    phase_id="PHASE_09",
    name="Feature Engineering",
    module="RSP.indicators.technical",
    status="active",
    inputs=["cleaned_ohlcv_df"],
    outputs=["feature_df", "indicator_values"],
    success_metric="All required features computed",
    failure_mode="Insufficient data -> NaN features",
)

PHASE_REGISTRY["PHASE_10"] = PhaseRecord(
    phase_id="PHASE_10",
    name="Volatility Engine",
    module="RSP.indicators.technical",
    status="active",
    inputs=["ohlcv_df", "atr_period"],
    outputs=["atr_pct", "volatility_regime"],
    success_metric="ATR computed and classified",
    failure_mode="Zero ATR -> fallback to default",
)

PHASE_REGISTRY["PHASE_11"] = PhaseRecord(
    phase_id="PHASE_11",
    name="Trend Structure Engine",
    module="RSP.indicators.technical",
    status="active",
    inputs=["ohlcv_df", "ema_periods", "sma_periods"],
    outputs=["trend_direction", "trend_strength"],
    success_metric="Trend detected with EMA/SMA",
    failure_mode="Flat market -> weak trend",
)

PHASE_REGISTRY["PHASE_12"] = PhaseRecord(
    phase_id="PHASE_12",
    name="Market Structure",
    module="RSP.market_structure.structure_engine",
    status="active",
    inputs=["ohlcv_df"],
    outputs=["swing_points", "bos_choch_events", "pattern"],
    success_metric="Structure events identified",
    failure_mode="No clear structure -> mixed pattern",
)

PHASE_REGISTRY["PHASE_13"] = PhaseRecord(
    phase_id="PHASE_13",
    name="Momentum Engine",
    module="RSP.indicators.technical",
    status="active",
    inputs=["ohlcv_df"],
    outputs=["rsi", "macd", "stoch_rsi", "momentum_state"],
    success_metric="Momentum indicators computed",
    failure_mode="Missing data -> neutral momentum",
)

PHASE_REGISTRY["PHASE_14"] = PhaseRecord(
    phase_id="PHASE_14",
    name="Volume Engine",
    module="RSP.indicators.technical",
    status="active",
    inputs=["ohlcv_df"],
    outputs=["volume_trend", "volume_anomaly_flags"],
    success_metric="Volume analyzed",
    failure_mode="Zero volume -> neutral",
)

PHASE_REGISTRY["PHASE_15"] = PhaseRecord(
    phase_id="PHASE_15",
    name="Support Resistance Engine",
    module="RSP.market_structure.structure_engine",
    status="active",
    inputs=["ohlcv_df"],
    outputs=["support_levels", "resistance_levels"],
    success_metric="Key levels identified",
    failure_mode="No clear levels -> empty list",
)

# =============================================================================
# LAYER 3 — REGIME INTELLIGENCE (Phases 16-20)
# =============================================================================

PHASE_REGISTRY["PHASE_16"] = PhaseRecord(
    phase_id="PHASE_16",
    name="Regime Detection",
    module="RSP.regime_engine.regime_engine",
    status="active",
    inputs=["perception_report"],
    outputs=["regime_label", "regime_strength"],
    success_metric="16 regimes correctly classified",
    failure_mode="Ambiguous -> UNKNOWN",
)

PHASE_REGISTRY["PHASE_17"] = PhaseRecord(
    phase_id="PHASE_17",
    name="Regime Strength",
    module="RSP.regime_engine.regime_engine",
    status="active",
    inputs=["regime_label", "indicator_values"],
    outputs=["regime_strength_score"],
    success_metric="Strength score 0..1 accurate",
    failure_mode="Missing indicators -> neutral",
)

PHASE_REGISTRY["PHASE_18"] = PhaseRecord(
    phase_id="PHASE_18",
    name="Regime Transition",
    module="RSP.regime_engine.regime_engine",
    status="active",
    inputs=["regime_history"],
    outputs=["transition_probability", "transition_direction"],
    success_metric="Transitions detected early",
    failure_mode="Sudden change -> late detection",
)

PHASE_REGISTRY["PHASE_19"] = PhaseRecord(
    phase_id="PHASE_19",
    name="Regime Stability",
    module="RSP.regime_engine.regime_engine",
    status="active",
    inputs=["regime_history"],
    outputs=["stability_score"],
    success_metric="Stable regimes score high",
    failure_mode="Choppy regime -> low stability",
)

PHASE_REGISTRY["PHASE_20"] = PhaseRecord(
    phase_id="PHASE_20",
    name="Regime Confidence",
    module="RSP.regime_engine.regime_engine",
    status="active",
    inputs=["regime_label", "data_quality"],
    outputs=["regime_confidence"],
    success_metric="Confidence reflects data quality",
    failure_mode="Low data quality -> low confidence",
)

# =============================================================================
# LAYER 4 — MULTI-TIMEFRAME INTELLIGENCE (Phases 21-26)
# =============================================================================

PHASE_REGISTRY["PHASE_21"] = PhaseRecord(
    phase_id="PHASE_21",
    name="Higher Timeframe Analysis",
    module="RSP.multi_timeframe.mtf_brain",
    status="active",
    inputs=["higher_tf_ohlcv"],
    outputs=["higher_tf_bias", "higher_tf_trend"],
    success_metric="HTF trend identified",
    failure_mode="Missing HTF data -> neutral",
)

PHASE_REGISTRY["PHASE_22"] = PhaseRecord(
    phase_id="PHASE_22",
    name="Mid Timeframe Analysis",
    module="RSP.multi_timeframe.mtf_brain",
    status="active",
    inputs=["mid_tf_ohlcv"],
    outputs=["mid_tf_bias", "mid_tf_trend"],
    success_metric="MTF trend identified",
    failure_mode="Missing MTF data -> neutral",
)

PHASE_REGISTRY["PHASE_23"] = PhaseRecord(
    phase_id="PHASE_23",
    name="Lower Timeframe Analysis",
    module="RSP.multi_timeframe.mtf_brain",
    status="active",
    inputs=["lower_tf_ohlcv"],
    outputs=["lower_tf_bias", "lower_tf_trend"],
    success_metric="LTF trend identified",
    failure_mode="Missing LTF data -> neutral",
)

PHASE_REGISTRY["PHASE_24"] = PhaseRecord(
    phase_id="PHASE_24",
    name="Multi-Timeframe Alignment",
    module="RSP.multi_timeframe.mtf_brain",
    status="active",
    inputs=["htf_bias", "mtf_bias", "ltf_bias"],
    outputs=["aligned_flag", "alignment_strength"],
    success_metric="All 3 TFs aligned -> strong",
    failure_mode="Disagreement -> unaligned",
)

PHASE_REGISTRY["PHASE_25"] = PhaseRecord(
    phase_id="PHASE_25",
    name="Multi-Timeframe Conflict",
    module="RSP.multi_timeframe.mtf_brain",
    status="active",
    inputs=["htf_bias", "mtf_bias", "ltf_bias"],
    outputs=["conflict_flag", "conflict_details"],
    success_metric="Conflicts detected and logged",
    failure_mode="Hidden conflict -> undetected",
)

PHASE_REGISTRY["PHASE_26"] = PhaseRecord(
    phase_id="PHASE_26",
    name="Timeframe Reliability Weighting",
    module="RSP.multi_timeframe.mtf_brain",
    status="active",
    inputs=["tf_reliability_scores"],
    outputs=["weighted_bias", "reliability_weights"],
    success_metric="Reliable TFs weighted higher",
    failure_mode="Equal weights -> no adaptation",
)

# =============================================================================
# LAYER 5 — FUZZY INTELLIGENCE CORE (Phases 27-38)
# =============================================================================

PHASE_REGISTRY["PHASE_27"] = PhaseRecord(
    phase_id="PHASE_27",
    name="Fuzzy Membership Engine",
    module="RSP.fuzzy_core.membership",
    status="active",
    inputs=["raw_feature_values", "domain_bounds"],
    outputs=["membership_degrees", "dominant_term"],
    success_metric="All 8 MF types produce valid [0,1] outputs",
    failure_mode="Invalid domain or NaN input -> fallback to zero membership",
)

PHASE_REGISTRY["PHASE_28"] = PhaseRecord(
    phase_id="PHASE_28",
    name="Fuzzy Linguistic Variables",
    module="RSP.fuzzy_core.membership",
    status="active",
    inputs=["membership_degrees"],
    outputs=["linguistic_labels", "term_degrees"],
    success_metric="5-term variables cover full [0,1] domain",
    failure_mode="Missing term -> fallback to nearest neighbor",
)

PHASE_REGISTRY["PHASE_29"] = PhaseRecord(
    phase_id="PHASE_29",
    name="Fuzzy Trend Quality",
    module="RSP.fuzzy_core.quality_engines",
    status="active",
    inputs=["RegimeReport", "ConfluenceReport"],
    outputs=["trend_quality_fuzzy"],
    success_metric="Strong regimes map to strong/very_strong, weak to weak/very_weak",
    failure_mode="Missing confluence data -> baseline from regime only",
)

PHASE_REGISTRY["PHASE_30"] = PhaseRecord(
    phase_id="PHASE_30",
    name="Fuzzy Momentum Quality",
    module="RSP.fuzzy_core.quality_engines",
    status="active",
    inputs=["ConfluenceReport"],
    outputs=["momentum_quality_fuzzy"],
    success_metric="Divergence penalizes, acceleration boosts",
    failure_mode="No momentum indicators -> neutral (moderate)",
)

PHASE_REGISTRY["PHASE_31"] = PhaseRecord(
    phase_id="PHASE_31",
    name="Fuzzy Entry Quality",
    module="RSP.fuzzy_core.quality_engines",
    status="active",
    inputs=["MTFReport", "StructureReport"],
    outputs=["entry_quality_fuzzy"],
    success_metric="Aligned MTF + confirming structure -> strong",
    failure_mode="Missing structure data -> MTF-only evaluation",
)

PHASE_REGISTRY["PHASE_32"] = PhaseRecord(
    phase_id="PHASE_32",
    name="Fuzzy Risk Quality",
    module="RSP.fuzzy_core.quality_engines",
    status="active",
    inputs=["RiskPlan", "atr_pct"],
    outputs=["risk_quality_fuzzy"],
    success_metric="RR >= 2.0 maps to strong/very_strong",
    failure_mode="Invalid risk plan -> very_weak",
)

PHASE_REGISTRY["PHASE_33"] = PhaseRecord(
    phase_id="PHASE_33",
    name="Fuzzy Volatility Quality",
    module="RSP.fuzzy_core.quality_engines",
    status="active",
    inputs=["atr_pct", "RegimeReport"],
    outputs=["volatility_quality_fuzzy"],
    success_metric="Low ATR -> excellent, high ATR -> poor",
    failure_mode="Missing ATR -> neutral",
)

PHASE_REGISTRY["PHASE_34"] = PhaseRecord(
    phase_id="PHASE_34",
    name="Fuzzy Market Stability",
    module="RSP.fuzzy_core.quality_engines",
    status="active",
    inputs=["RegimeReport", "StructureReport"],
    outputs=["market_stability_fuzzy"],
    success_metric="Range/low_vol -> strong, transition/crash -> weak",
    failure_mode="Missing structure -> regime-only",
)

PHASE_REGISTRY["PHASE_35"] = PhaseRecord(
    phase_id="PHASE_35",
    name="Fuzzy Signal Strength",
    module="RSP.fuzzy_core.quality_engines",
    status="active",
    inputs=["FusionReport"],
    outputs=["signal_strength_fuzzy"],
    success_metric="|net_score| maps correctly with exhaustion awareness",
    failure_mode="Missing fusion -> very_weak",
)

PHASE_REGISTRY["PHASE_36"] = PhaseRecord(
    phase_id="PHASE_36",
    name="Fuzzy Signal Confidence",
    module="RSP.fuzzy_core.quality_engines",
    status="active",
    inputs=["ConfidenceReport"],
    outputs=["signal_confidence_fuzzy"],
    success_metric="Confidence 0..100 linearly mapped to fuzzy terms",
    failure_mode="Missing confidence -> neutral",
)

PHASE_REGISTRY["PHASE_37"] = PhaseRecord(
    phase_id="PHASE_37",
    name="Fuzzy Contradiction Severity",
    module="RSP.fuzzy_core.quality_engines",
    status="active",
    inputs=["ContradictionReport"],
    outputs=["contradiction_severity_fuzzy"],
    success_metric="Severe contradiction -> severe, none -> none",
    failure_mode="Missing report -> none",
)

PHASE_REGISTRY["PHASE_38"] = PhaseRecord(
    phase_id="PHASE_38",
    name="Fuzzy Opportunity Quality",
    module="RSP.fuzzy_core.quality_engines",
    status="active",
    inputs=["all_quality_fuzzy_outputs"],
    outputs=["opportunity_quality_fuzzy"],
    success_metric="Heuristic aggregate reflects weighted combination",
    failure_mode="Missing any quality -> reduced weight for that component",
)

# =============================================================================
# LAYER 6 — FUZZY RULE SYSTEM (Phases 39-44)
# =============================================================================

PHASE_REGISTRY["PHASE_39"] = PhaseRecord(
    phase_id="PHASE_39",
    name="Fuzzy Rule Base",
    module="RSP.fuzzy_core.rule_base",
    status="active",
    inputs=["fuzzified_quality_variables"],
    outputs=["rule_firing_strengths", "active_rules"],
    success_metric="All 20 rules evaluate without error",
    failure_mode="Missing input variable -> zero firing for affected rules",
)

PHASE_REGISTRY["PHASE_40"] = PhaseRecord(
    phase_id="PHASE_40",
    name="Rule Weighting",
    module="RSP.fuzzy_core.rule_base",
    status="active",
    inputs=["FuzzyRule objects"],
    outputs=["weighted_firing_strengths"],
    success_metric="Weights correctly modulate rule influence",
    failure_mode="Invalid weight -> clamped to [0,1]",
)

PHASE_REGISTRY["PHASE_41"] = PhaseRecord(
    phase_id="PHASE_41",
    name="Rule Conflict Resolution",
    module="RSP.fuzzy_core.conflict_resolution",
    status="active",
    inputs=["rule_firing_strengths"],
    outputs=["resolved_score", "conflict_report"],
    success_metric="Conflicting rules produce single coherent score",
    failure_mode="No active rules -> zero score",
)

PHASE_REGISTRY["PHASE_42"] = PhaseRecord(
    phase_id="PHASE_42",
    name="Fuzzy Inference Engine",
    module="RSP.fuzzy_core.inference",
    status="active",
    inputs=["fuzzified_inputs", "rule_base", "method"],
    outputs=["defuzzified_score", "fuzzy_inference_report"],
    success_metric="Sugeno and Mamdani both produce valid [0,100] scores",
    failure_mode="Unknown method -> fallback to Sugeno",
)

PHASE_REGISTRY["PHASE_43"] = PhaseRecord(
    phase_id="PHASE_43",
    name="Fuzzy Aggregation",
    module="RSP.fuzzy_core.inference",
    status="active",
    inputs=["individual_rule_outputs", "firing_strengths"],
    outputs=["aggregated_fuzzy_set"],
    success_metric="Union (max) of clipped MFs correct",
    failure_mode="Sugeno mode skips aggregation",
)

PHASE_REGISTRY["PHASE_44"] = PhaseRecord(
    phase_id="PHASE_44",
    name="Defuzzification",
    module="RSP.fuzzy_core.inference",
    status="active",
    inputs=["aggregated_fuzzy_set"],
    outputs=["crisp_score"],
    success_metric="Centroid within [0,100], Sugeno within [0,100]",
    failure_mode="Zero area -> return 0",
)

# =============================================================================
# LAYER 7 — DECISION CONTROL (Phases 45-50)
# =============================================================================

PHASE_REGISTRY["PHASE_45"] = PhaseRecord(
    phase_id="PHASE_45",
    name="Signal Fusion (Fuzzy-Aware)",
    module="RSP.fuzzy_core.decision_controller",
    status="active",
    inputs=["fuzzy_inference_output", "direction"],
    outputs=["fused_decision_input"],
    success_metric="Fuzzy score correctly integrated with direction",
    failure_mode="Missing direction -> HOLD",
)

PHASE_REGISTRY["PHASE_46"] = PhaseRecord(
    phase_id="PHASE_46",
    name="Dynamic Confidence Calibration",
    module="RSP.fuzzy_core.decision_controller",
    status="active",
    inputs=["opportunity_score", "contradiction", "stability"],
    outputs=["calibrated_confidence"],
    success_metric="Confidence reflects real uncertainty",
    failure_mode="Calibration disabled -> raw score used",
)

PHASE_REGISTRY["PHASE_47"] = PhaseRecord(
    phase_id="PHASE_47",
    name="Adaptive Threshold Controller",
    module="RSP.fuzzy_core.decision_controller",
    status="active",
    inputs=["config thresholds", "market_regime"],
    outputs=["effective_threshold"],
    success_metric="Threshold loaded from config correctly",
    failure_mode="Missing config -> default 45.0",
)

PHASE_REGISTRY["PHASE_48"] = PhaseRecord(
    phase_id="PHASE_48",
    name="Decision Stability",
    module="RSP.fuzzy_core.decision_controller",
    status="active",
    inputs=["decision_history"],
    outputs=["stability_flag"],
    success_metric="3+ consistent decisions -> stable",
    failure_mode="History empty -> stable (permissive)",
)

PHASE_REGISTRY["PHASE_49"] = PhaseRecord(
    phase_id="PHASE_49",
    name="Decision Hysteresis",
    module="RSP.fuzzy_core.decision_controller",
    status="active",
    inputs=["new_decision", "last_trade_decision", "score_delta"],
    outputs=["hysteresis_block_flag"],
    success_metric="Rapid flip-flops prevented",
    failure_mode="No previous trade -> no hysteresis",
)

PHASE_REGISTRY["PHASE_50"] = PhaseRecord(
    phase_id="PHASE_50",
    name="Trade Permission Gate",
    module="RSP.fuzzy_core.decision_controller",
    status="active",
    inputs=["opportunity_score", "all_quality_fuzzy", "config gates"],
    outputs=["final_decision", "rejection_reason"],
    success_metric="Even strong signals rejected if gates fail",
    failure_mode="All gates disabled -> permissive",
)

print("Phase Registry Initialized with 50 Phases")
