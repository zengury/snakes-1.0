"""Auto-generated safety validation tests for Unitree G1 29-DOF.

Tests all validate_*() functions with boundary values to ensure
no out-of-range command can reach hardware.
"""
import pytest
from unitree_cli.client import (
    G1_JOINT_LIMITS, G1_NUM_MOTOR, G1_NAME_TO_IDX, G1_ARM_ACTIONS,
    SafetyError, resolve_joint, validate_joint_q, validate_kp, validate_kd,
    validate_arm_action,
)


class TestResolveJoint:
    def test_valid_index(self):
        for i in range(G1_NUM_MOTOR):
            assert resolve_joint(i) == i

    def test_invalid_index_negative(self):
        with pytest.raises(SafetyError):
            resolve_joint(-1)

    def test_invalid_index_overflow(self):
        with pytest.raises(SafetyError):
            resolve_joint(29)

    def test_valid_name(self):
        assert resolve_joint("LeftKnee") == 3
        assert resolve_joint("RightElbow") == 25
        assert resolve_joint("WaistYaw") == 12

    def test_case_insensitive(self):
        assert resolve_joint("leftknee") == 3
        assert resolve_joint("LEFTKNEE") == 3

    def test_invalid_name(self):
        with pytest.raises(SafetyError):
            resolve_joint("BogusJoint")

    def test_all_names_resolve(self):
        for name, idx in G1_NAME_TO_IDX.items():
            assert resolve_joint(name) == idx


class TestValidateJointQ:
    def test_within_range(self):
        for idx, (lo, hi) in G1_JOINT_LIMITS.items():
            mid = (lo + hi) / 2
            validate_joint_q(idx, mid)  # should not raise

    def test_at_lower_bound(self):
        for idx, (lo, _) in G1_JOINT_LIMITS.items():
            validate_joint_q(idx, lo)

    def test_at_upper_bound(self):
        for idx, (_, hi) in G1_JOINT_LIMITS.items():
            validate_joint_q(idx, hi)

    def test_below_lower_bound(self):
        for idx, (lo, _) in G1_JOINT_LIMITS.items():
            with pytest.raises(SafetyError):
                validate_joint_q(idx, lo - 0.01)

    def test_above_upper_bound(self):
        for idx, (_, hi) in G1_JOINT_LIMITS.items():
            with pytest.raises(SafetyError):
                validate_joint_q(idx, hi + 0.01)


class TestValidateKpKd:
    def test_kp_valid(self):
        validate_kp(0)
        validate_kp(60)
        validate_kp(500)

    def test_kp_invalid(self):
        with pytest.raises(SafetyError):
            validate_kp(-1)
        with pytest.raises(SafetyError):
            validate_kp(501)

    def test_kd_valid(self):
        validate_kd(0)
        validate_kd(1)
        validate_kd(50)

    def test_kd_invalid(self):
        with pytest.raises(SafetyError):
            validate_kd(-1)
        with pytest.raises(SafetyError):
            validate_kd(51)


class TestValidateArmAction:
    def test_valid_names(self):
        for name, action_id in G1_ARM_ACTIONS.items():
            assert validate_arm_action(name) == action_id

    def test_valid_integer(self):
        assert validate_arm_action("99") == 99
        assert validate_arm_action("17") == 17

    def test_invalid(self):
        with pytest.raises(SafetyError):
            validate_arm_action("nonexistent_action")


class TestJointCoverage:
    def test_29_joints_defined(self):
        assert G1_NUM_MOTOR == 29

    def test_all_joints_have_limits(self):
        for i in range(G1_NUM_MOTOR):
            assert i in G1_JOINT_LIMITS, f"joint {i} missing from G1_JOINT_LIMITS"

    def test_limits_are_sane(self):
        for idx, (lo, hi) in G1_JOINT_LIMITS.items():
            assert lo < hi, f"joint {idx}: lo={lo} >= hi={hi}"
            assert lo >= -3.15, f"joint {idx}: lo={lo} seems too low"
            assert hi <= 3.15, f"joint {idx}: hi={hi} seems too high"
