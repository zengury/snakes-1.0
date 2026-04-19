"""
Safety gate: synchronous, structured, non-embedding.

Called on EVERY command before execution. Design principle: if the fast path
can't prove a command is safe by structural rule match, the answer is no.

The context_predicate DSL supports a small set of operators to keep rule
evaluation deterministic and auditable:

  {"all_true": [<predicate>, ...]}
  {"any_true": [<predicate>, ...]}
  {"fact": "name", "value": X}                  # exact match
  {"fact": "name", "below": X}                  # numeric <
  {"fact": "name", "above": X}                  # numeric >
  {"fact": "name", "range": [lo, hi]}           # inclusive
  {"fact": "name", "in": [a, b, ...]}           # membership

Predicates are evaluated against the `context` dict passed to `allows()`.
Missing facts evaluate to False (fail-closed).
"""
from __future__ import annotations

import fnmatch
from typing import Any

from ..protocols import Command, SafetyGate, SafetyRule


class RuleBasedSafetyGate:
    """Implements SafetyGate with a list of rules. Fail-closed on any error."""

    def __init__(self, rules: list[SafetyRule] | None = None):
        self._rules: list[SafetyRule] = list(rules or [])

    def add_rule(self, rule: SafetyRule) -> None:
        # If this rule supersedes another, drop the old one
        if rule.supersedes:
            self._rules = [r for r in self._rules if r.rule_id != rule.supersedes]
        self._rules.append(rule)

    def rules(self) -> list[SafetyRule]:
        return list(self._rules)

    def allows(self, command: Command, context: dict[str, Any]) -> bool:
        return self._find_match(command, context) is None

    def explain(self, command: Command, context: dict[str, Any]) -> str | None:
        match = self._find_match(command, context)
        if match is None:
            return None
        rule, reason = match
        return reason

    def triggered_rule(self, command: Command, context: dict[str, Any]) -> SafetyRule | None:
        match = self._find_match(command, context)
        if match is None:
            return None
        rule, _ = match
        return rule

    def _find_match(
        self, command: Command, context: dict[str, Any]
    ) -> tuple[SafetyRule, str] | None:
        """Single source of truth: find the first rule that blocks this command.

        Returns (rule, explanation) if blocked, None if allowed.
        """
        for rule in self._rules:
            # 1. Does the command match this rule's pattern?
            if not fnmatch.fnmatchcase(command.name, rule.forbidden_command_pattern):
                continue

            # 2. Is the rule's context predicate satisfied right now?
            try:
                triggered = _evaluate_predicate(rule.context_predicate, context)
            except Exception as e:
                # Fail-closed: if the rule evaluation itself errored, block.
                return rule, f"rule {rule.rule_id} evaluation error: {e}"

            if not triggered:
                continue

            # 3. If the rule has an `unless_params` escape, check it.
            if rule.unless_params and _params_match(rule.unless_params, command.params):
                continue

            return rule, (
                f"rule {rule.rule_id} ({rule.severity.value}): "
                f"{command.name} matches pattern {rule.forbidden_command_pattern!r} "
                f"under current context"
            )

        return None


# ---------------------------------------------------------------------------
# Predicate DSL evaluator
# ---------------------------------------------------------------------------


def _evaluate_predicate(pred: dict[str, Any], ctx: dict[str, Any]) -> bool:
    if "all_true" in pred:
        return all(_evaluate_predicate(p, ctx) for p in pred["all_true"])
    if "any_true" in pred:
        return any(_evaluate_predicate(p, ctx) for p in pred["any_true"])
    if "fact" in pred:
        fact_name = pred["fact"]
        if fact_name not in ctx:
            return False  # fail-closed
        actual = ctx[fact_name]
        if "value" in pred:
            return actual == pred["value"]
        if "below" in pred:
            return _numeric(actual) < _numeric(pred["below"])
        if "above" in pred:
            return _numeric(actual) > _numeric(pred["above"])
        if "range" in pred:
            lo, hi = pred["range"]
            return _numeric(lo) <= _numeric(actual) <= _numeric(hi)
        if "in" in pred:
            return actual in pred["in"]
        # Unknown leaf — fail-closed
        return False
    # Unknown node — fail-closed
    return False


def _numeric(x: Any) -> float:
    if isinstance(x, bool):
        # Guard: bool is subclass of int in Python, but we don't want True == 1
        # to silently pass a numeric check.
        raise TypeError(f"expected numeric, got bool {x}")
    return float(x)


def _params_match(required: dict[str, Any], actual: dict[str, Any]) -> bool:
    """All keys in `required` must match in `actual`. Extra keys in actual ok."""
    for k, v in required.items():
        if actual.get(k) != v:
            return False
    return True


# Protocol check
_: SafetyGate = RuleBasedSafetyGate()
