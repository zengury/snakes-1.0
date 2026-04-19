"""
Unitree G1 preset: reference TopicMapping set for the 29-DOF humanoid.

These topic names and fields correspond to Unitree's public DDS IDL for
the G1. Versioning note: Unitree has shipped topic-name changes between
SDK revisions. Treat this as a starting point and adjust per your SDK.

If your SDK uses different names (e.g., `rt/lf/lowstate` vs `rt/lowstate`),
either edit this file or build your own TopicMapping list — there is
nothing magic here.
"""
from __future__ import annotations

from ..adapter import AnomalyRule
from ..mapping import FieldMapping, TopicMapping


def low_state_mapping(min_interval_s: float = 0.02) -> TopicMapping:
    """Low-level joint state — 29 DOF motor positions, velocities, torques.

    Default rate limit: 50 Hz into reflex (every 20ms). The raw topic
    publishes at 500 Hz; reflex doesn't need that and the fast loop reads
    whatever's current anyway.
    """
    return TopicMapping(
        topic="rt/lowstate",
        min_interval_s=min_interval_s,
        fields=[
            FieldMapping(reflex_key="imu_quat_w", source_path="imu_state.quaternion.0"),
            FieldMapping(reflex_key="imu_quat_x", source_path="imu_state.quaternion.1"),
            FieldMapping(reflex_key="imu_quat_y", source_path="imu_state.quaternion.2"),
            FieldMapping(reflex_key="imu_quat_z", source_path="imu_state.quaternion.3"),
            FieldMapping(reflex_key="gyroscope_x", source_path="imu_state.gyroscope.0"),
            FieldMapping(reflex_key="gyroscope_y", source_path="imu_state.gyroscope.1"),
            FieldMapping(reflex_key="gyroscope_z", source_path="imu_state.gyroscope.2"),
            FieldMapping(reflex_key="accel_x", source_path="imu_state.accelerometer.0"),
            FieldMapping(reflex_key="accel_y", source_path="imu_state.accelerometer.1"),
            FieldMapping(reflex_key="accel_z", source_path="imu_state.accelerometer.2"),
            FieldMapping(reflex_key="imu_temp", source_path="imu_state.temperature"),
        ],
    )


def sport_mode_state_mapping(min_interval_s: float = 0.05) -> TopicMapping:
    """High-level body state — position, velocity, mode, gait.

    Default rate limit: 20 Hz. Typically this is all the fast loop's
    behavior controller needs to see from "where am I" data.
    """
    return TopicMapping(
        topic="rt/sportmodestate",
        min_interval_s=min_interval_s,
        fields=[
            FieldMapping(reflex_key="mode", source_path="mode"),
            FieldMapping(reflex_key="gait_type", source_path="gait_type"),
            FieldMapping(reflex_key="body_height", source_path="body_height"),
            FieldMapping(reflex_key="position_x", source_path="position.0"),
            FieldMapping(reflex_key="position_y", source_path="position.1"),
            FieldMapping(reflex_key="position_z", source_path="position.2"),
            FieldMapping(reflex_key="velocity_x", source_path="velocity.0"),
            FieldMapping(reflex_key="velocity_y", source_path="velocity.1"),
            FieldMapping(reflex_key="yaw_speed", source_path="yaw_speed"),
            FieldMapping(reflex_key="foot_force_lf", source_path="foot_force.0"),
            FieldMapping(reflex_key="foot_force_rf", source_path="foot_force.1"),
            FieldMapping(reflex_key="foot_force_lr", source_path="foot_force.2"),
            FieldMapping(reflex_key="foot_force_rr", source_path="foot_force.3"),
        ],
    )


def battery_mapping(min_interval_s: float = 1.0) -> TopicMapping:
    """Battery telemetry. Rate-limit to 1 Hz since it's slow-moving —
    EXCEPT for battery_pct which is flagged safety_critical so it always
    updates. Battery level is referenced by safety rules; stale battery
    data is worse than the bandwidth cost."""
    return TopicMapping(
        topic="rt/lowstate",
        min_interval_s=min_interval_s,
        fields=[
            FieldMapping(reflex_key="battery_pct",
                         source_path="bms_state.soc",
                         safety_critical=True),
            FieldMapping(reflex_key="battery_voltage",
                         source_path="bms_state.vol"),
            FieldMapping(reflex_key="battery_current",
                         source_path="bms_state.current"),
            FieldMapping(reflex_key="battery_temp_max",
                         source_path="bms_state.bq_ntc.0",
                         safety_critical=True),
        ],
    )


def default_g1_mappings() -> list[TopicMapping]:
    """Convenience: returns the three standard mappings for a quickstart."""
    return [
        low_state_mapping(),
        sport_mode_state_mapping(),
        battery_mapping(),
    ]


def default_g1_anomaly_rules() -> list[AnomalyRule]:
    """Structural anomaly rules that apply to any G1 deployment."""
    return [
        AnomalyRule(
            name="battery_critical",
            reflex_key="battery_pct",
            check=lambda v: v is not None and v < 5,
        ),
        AnomalyRule(
            name="imu_temperature_high",
            reflex_key="imu_temp",
            check=lambda v: v is not None and v > 70,
        ),
        AnomalyRule(
            name="foot_force_imbalance",
            reflex_key="foot_force_lf",
            # Simple heuristic — real implementation would compare all 4 feet.
            # Here we just flag wildly negative readings (sensor fault).
            check=lambda v: v is not None and v < -100,
        ),
    ]
