"""
RSP — Regime Rule Filter v2.0
NEW FILE: Wires REGIME_RULE_OVERRIDES to fuzzy rule evaluation
"""

from ..config import settings


class RegimeRuleFilter:
    """Filter fuzzy rules based on current regime."""

    def __init__(self):
        self.overrides = settings.REGIME_RULE_OVERRIDES

    def filter_rules(self, signals, regime_label: str):
        """Apply regime-specific rule overrides to signals."""
        if not hasattr(signals, 'rules'):
            return signals

        override = self.overrides.get(regime_label, {})
        disable = override.get("disable", [])
        enable = override.get("enable", [])

        filtered = signals
        if hasattr(signals, 'rules'):
            filtered_rules = []
            for rule in signals.rules:
                rule_id = getattr(rule, 'id', None)
                if rule_id in disable:
                    continue
                filtered_rules.append(rule)

            for rule_id in enable:
                if not any(getattr(r, 'id', None) == rule_id for r in filtered_rules):
                    from dataclasses import dataclass
                    @dataclass
                    class EnabledRule:
                        id: str
                        active: bool = True
                    filtered_rules.append(EnabledRule(id=rule_id))
            filtered.rules = filtered_rules

        return filtered

    def get_regime_note(self, regime_label: str) -> str:
        return self.overrides.get(regime_label, {}).get("note", "")
