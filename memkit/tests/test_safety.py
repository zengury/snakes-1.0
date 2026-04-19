"""Tests for the safety gate — the most critical layer."""
import pytest

from memkit import Command, SafetyRule, Severity
from memkit.layers.safety import RuleBasedSafetyGate


def test_empty_gate_allows_everything():
    gate = RuleBasedSafetyGate()
    assert gate.allows(Command(name="arm.grasp"), {}) is True


def test_rule_blocks_matching_command():
    gate = RuleBasedSafetyGate([
        SafetyRule(
            rule_id="r1",
            severity=Severity.HARD_STOP,
            context_predicate={"fact": "human_in_envelope", "value": True},
            forbidden_command_pattern="locomotion.*",
        )
    ])
    ctx = {"human_in_envelope": True}
    assert gate.allows(Command(name="locomotion.walk"), ctx) is False
    assert gate.allows(Command(name="arm.grasp"), ctx) is True  # different pattern


def test_rule_inert_when_predicate_false():
    gate = RuleBasedSafetyGate([
        SafetyRule(
            rule_id="r1",
            severity=Severity.HARD_STOP,
            context_predicate={"fact": "human_in_envelope", "value": True},
            forbidden_command_pattern="locomotion.*",
        )
    ])
    ctx = {"human_in_envelope": False}
    assert gate.allows(Command(name="locomotion.walk"), ctx) is True


def test_missing_fact_fails_closed():
    """If the context doesn't have the fact the rule depends on, the rule
    predicate returns False — the rule is inert (not triggered)."""
    gate = RuleBasedSafetyGate([
        SafetyRule(
            rule_id="r1",
            severity=Severity.HARD_STOP,
            context_predicate={"fact": "human_in_envelope", "value": True},
            forbidden_command_pattern="locomotion.*",
        )
    ])
    # Empty context means human_in_envelope is missing -> predicate false -> rule inert
    assert gate.allows(Command(name="locomotion.walk"), {}) is True


def test_unless_params_escape():
    gate = RuleBasedSafetyGate([
        SafetyRule(
            rule_id="r_battery",
            severity=Severity.SOFT_STOP,
            context_predicate={"fact": "battery_pct", "below": 5},
            forbidden_command_pattern="locomotion.*",
            unless_params={"mode": "return_to_dock"},
        )
    ])
    ctx = {"battery_pct": 3}
    assert gate.allows(Command(name="locomotion.walk"), ctx) is False
    assert gate.allows(
        Command(name="locomotion.walk", params={"mode": "return_to_dock"}), ctx
    ) is True


def test_all_true_predicate():
    gate = RuleBasedSafetyGate([
        SafetyRule(
            rule_id="r1",
            severity=Severity.HARD_STOP,
            context_predicate={
                "all_true": [
                    {"fact": "a", "value": 1},
                    {"fact": "b", "value": 2},
                ]
            },
            forbidden_command_pattern="x",
        )
    ])
    assert gate.allows(Command(name="x"), {"a": 1, "b": 2}) is False
    assert gate.allows(Command(name="x"), {"a": 1, "b": 3}) is True


def test_any_true_predicate():
    gate = RuleBasedSafetyGate([
        SafetyRule(
            rule_id="r1",
            severity=Severity.HARD_STOP,
            context_predicate={
                "any_true": [
                    {"fact": "a", "value": 1},
                    {"fact": "b", "value": 2},
                ]
            },
            forbidden_command_pattern="x",
        )
    ])
    assert gate.allows(Command(name="x"), {"a": 1}) is False
    assert gate.allows(Command(name="x"), {"a": 0, "b": 2}) is False
    assert gate.allows(Command(name="x"), {"a": 0, "b": 0}) is True


def test_range_predicate():
    gate = RuleBasedSafetyGate([
        SafetyRule(
            rule_id="r1",
            severity=Severity.WARN,
            context_predicate={"fact": "temp", "range": [0, 40]},
            forbidden_command_pattern="heat.*",
        )
    ])
    assert gate.allows(Command(name="heat.on"), {"temp": 20}) is False
    assert gate.allows(Command(name="heat.on"), {"temp": 50}) is True


def test_supersede_removes_old_rule():
    gate = RuleBasedSafetyGate()
    gate.add_rule(SafetyRule(
        rule_id="r1", severity=Severity.WARN,
        context_predicate={"fact": "x", "value": True},
        forbidden_command_pattern="cmd",
    ))
    gate.add_rule(SafetyRule(
        rule_id="r2", severity=Severity.WARN,
        context_predicate={"fact": "y", "value": True},
        forbidden_command_pattern="cmd",
        supersedes="r1",
    ))
    ids = [r.rule_id for r in gate.rules()]
    assert "r1" not in ids
    assert "r2" in ids
