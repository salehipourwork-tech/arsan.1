#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSP — Regime-Aware Rule Filter (Profitability Fix v1)

هدف: رفع "رژیم-نابینایی" — ETH anomaly
- توی STRONG_UPTREND/STRONG_DOWNTREND: MR rules خاموش → فقط TF rules
- توی RANGE: TF rules خاموش → فقط MR rules
- بقیه: همه فعال
"""

from typing import List, Dict, Optional
from RSP.config import settings

# Mapping rule IDs to categories
RULE_CATEGORIES = {
    # Mean Reversion (MR) rules
    "R14": "MR", "R15": "MR", "R16": "MR",
    # Trend Following (TF) rules  
    "R17": "TF", "R18": "TF",
    # Add more as needed
}

class RegimeRuleFilter:
    """
    Filters active rules based on current market regime.

    Usage:
        filter = RegimeRuleFilter()
        active_rules = filter.get_active_rules("STRONG_UPTREND", all_rules)
    """

    def __init__(self):
        self.overrides = getattr(settings, "REGIME_RULE_OVERRIDES", {})

    def get_active_rules(self, regime: str, all_rules: List[str]) -> List[str]:
        """
        Return list of rules that should be active for this regime.

        Args:
            regime: Current regime label (e.g., "STRONG_UPTREND")
            all_rules: List of all available rule IDs

        Returns:
            Filtered list of active rule IDs
        """
        if regime not in self.overrides:
            return all_rules  # No override → all rules active

        override = self.overrides[regime]
        disabled = set(override.get("disable", []))
        enabled = set(override.get("enable", []))

        # Start with all rules, remove disabled, add enabled
        active = set(all_rules)
        active -= disabled
        active |= enabled

        return sorted(list(active))

    def should_use_rule(self, regime: str, rule_id: str) -> bool:
        """Check if a specific rule should be used in this regime."""
        active = self.get_active_rules(regime, list(RULE_CATEGORIES.keys()))
        return rule_id in active

    def get_regime_note(self, regime: str) -> str:
        """Get human-readable note for this regime's rule selection."""
        if regime in self.overrides:
            return self.overrides[regime].get("note", "")
        return "All rules active"

    def get_rule_category(self, rule_id: str) -> str:
        """Get category of a rule (MR, TF, etc.)."""
        return RULE_CATEGORIES.get(rule_id, "UNKNOWN")

    def explain_filtering(self, regime: str, all_rules: List[str]) -> Dict:
        """Return detailed explanation of what was filtered and why."""
        active = self.get_active_rules(regime, all_rules)
        disabled = [r for r in all_rules if r not in active]

        return {
            "regime": regime,
            "total_rules": len(all_rules),
            "active_rules": active,
            "active_count": len(active),
            "disabled_rules": disabled,
            "disabled_count": len(disabled),
            "note": self.get_regime_note(regime),
        }

# Convenience function for direct use in backtest_engine
def filter_rules_by_regime(regime: str, all_rules: List[str]) -> List[str]:
    """Static convenience function."""
    filter_obj = RegimeRuleFilter()
    return filter_obj.get_active_rules(regime, all_rules)
