"""Robot-specific presets. Currently: Unitree G1."""

from .unitree_g1 import (
    battery_mapping,
    default_g1_anomaly_rules,
    default_g1_mappings,
    low_state_mapping,
    sport_mode_state_mapping,
)

__all__ = [
    "battery_mapping",
    "default_g1_anomaly_rules",
    "default_g1_mappings",
    "low_state_mapping",
    "sport_mode_state_mapping",
]
