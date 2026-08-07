"""The threshold table and the dispatch switch. Spec section 4.

This module is PURE. It makes no model call, does no I/O, reads no clock and uses no
randomness. Given the same score and context it returns the same decision and the same
rule name, forever.

That purity is the security property, not a style preference. ADR-0006: assume
untrusted-content tagging fails. Injected text can move a score, because a model produced
the score. It cannot move a rule, because no model is involved here.

The table lives in config/scrutiny.yaml as data. Rules are evaluated top to bottom and the
FIRST match wins. Guards come before permissions, so no combination of high scores can
route around `high_risk_always_asks`.

Every decision carries the name of the rule that produced it. A decision without a rule
name is a bug, not a fallback, which is why the table ends in an explicit `floor` rule
rather than an implicit default.

Roughly 200 lines, as spec section 4 estimates. Keep it that way: this file being small
enough to read in one sitting is what makes the triage layer auditable.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

from scrutiny.score import Score


class Action(Enum):
    """The five actions. Spec section 4.

    `act` and `propagate` are distinct, and collapsing them is the mistake to avoid:
    `act` does the thing directly, `propagate` hands it to a bounded specialist with its
    own budget, tool allowlist and branch. A design with four actions has quietly removed
    one of those.
    """

    ACT = "act"
    ASK = "ask"
    WATCH = "watch"
    IGNORE = "ignore"
    PROPAGATE = "propagate"


@dataclass(frozen=True)
class Decision:
    """One decision, and the single rule that produced it.

    `rule` is never empty. Downstream code, the accuracy report and the correction ledger
    all key on it, and an unexplained correct answer cannot be audited.
    """

    action: Action
    rule: str
    why: str = ""

    def __str__(self) -> str:
        return f"{self.action.value} ({self.rule})"


class PolicyError(Exception):
    """Raised when the rule table is malformed or an expression cannot be evaluated.

    Never raised for "no rule matched": the table's explicit `floor` rule covers that. If
    this fires, config/scrutiny.yaml is wrong and the correct response is to fix it rather
    than to fall back to some default action.
    """


# --- Restricted expression evaluation ---------------------------------------
# `when:` expressions are DATA that ingested text can influence indirectly, through the
# scores they are evaluated against. They are therefore never passed to eval(). This is a
# whitelist-based AST walker: anything not explicitly permitted raises.

_ALLOWED_NODES = (
    ast.Expression,
    ast.BoolOp, ast.And, ast.Or,
    ast.UnaryOp, ast.Not,
    ast.Compare,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.Name, ast.Attribute, ast.Constant, ast.Load,
)

_LITERALS = {"true": True, "false": False, "none": None}

# Attribute access is permitted on exactly these two names and nowhere else.
#
# Without this restriction, `risk.__class__.__bases__` walks straight out of the sandbox:
# an axis is a float, and Python floats carry the whole object graph on their attributes.
# getattr() on arbitrary values is not a whitelist, it is a doorway. Only the two mapping
# namespaces are reachable, and only one level deep.
_ATTRIBUTE_NAMESPACES = frozenset({"thresholds", "context"})


def _resolve(node: ast.expr, env: Mapping[str, Any]) -> Any:
    """Resolve a Name, or a one-level Attribute on a permitted namespace."""
    if isinstance(node, ast.Name):
        key = node.id
        if key in env:
            return env[key]
        if key.lower() in _LITERALS:
            return _LITERALS[key.lower()]
        raise PolicyError(
            f"unknown name in rule expression: {key!r}. "
            "Names are the seven axes, `thresholds`, `context`, and true/false/none. "
            "A typo must fail here rather than silently evaluating False, because a "
            "silently-false guard is the worst failure this table can have."
        )

    if isinstance(node, ast.Attribute):
        if not isinstance(node.value, ast.Name):
            raise PolicyError(
                "attribute access is one level deep and only on `thresholds` or `context`"
            )
        namespace = node.value.id
        if namespace not in _ATTRIBUTE_NAMESPACES:
            raise PolicyError(
                f"attribute access on {namespace!r} is not permitted. "
                f"Only {sorted(_ATTRIBUTE_NAMESPACES)} are namespaces; every other name is "
                "a scalar, and reaching through a scalar's attributes escapes the sandbox."
            )
        if node.attr.startswith("__"):
            raise PolicyError(f"dunder attribute {node.attr!r} is never permitted")

        base = env.get(namespace)
        if not isinstance(base, Mapping):
            raise PolicyError(f"{namespace!r} is not a mapping in this environment")

        if namespace == "context":
            # Missing context keys are False rather than an error: a rule asking about
            # `context.speaker_verified` must still evaluate for a Matrix message, where
            # there is no speaker at all.
            return base.get(node.attr, False)

        # A missing threshold IS an error. Thresholds are declared in the same file as the
        # rules that read them, so a missing one is a typo, and a typo that evaluates to
        # False would disable a guard.
        if node.attr not in base:
            raise PolicyError(f"unknown threshold: thresholds.{node.attr}")
        return base[node.attr]

    raise PolicyError(f"unsupported node in rule expression: {type(node).__name__}")


def _eval(node: ast.expr, env: Mapping[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        return node.value

    if isinstance(node, (ast.Name, ast.Attribute)):
        return _resolve(node, env)

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not _eval(node.operand, env)

    if isinstance(node, ast.BoolOp):
        values = [_eval(v, env) for v in node.values]
        return all(values) if isinstance(node.op, ast.And) else any(values)

    if isinstance(node, ast.Compare):
        left = _eval(node.left, env)
        for op, comparator in zip(node.ops, node.comparators, strict=True):
            right = _eval(comparator, env)
            if isinstance(op, ast.Eq):
                ok = left == right
            elif isinstance(op, ast.NotEq):
                ok = left != right
            elif isinstance(op, ast.Lt):
                ok = left < right
            elif isinstance(op, ast.LtE):
                ok = left <= right
            elif isinstance(op, ast.Gt):
                ok = left > right
            elif isinstance(op, ast.GtE):
                ok = left >= right
            else:  # pragma: no cover - guarded by _ALLOWED_NODES
                raise PolicyError(f"unsupported comparison: {type(op).__name__}")
            if not ok:
                return False
            left = right
        return True

    raise PolicyError(f"unsupported node in rule expression: {type(node).__name__}")


def evaluate(expression: str, env: Mapping[str, Any]) -> bool:
    """Evaluate one `when:` expression against an environment. Never uses eval().

    Raises:
        PolicyError: the expression contains a construct outside the whitelist, or a name
            that is not an axis, a threshold or a context key.
    """
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as exc:
        raise PolicyError(f"cannot parse rule expression {expression!r}: {exc}") from exc

    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise PolicyError(
                f"disallowed construct {type(node).__name__} in rule expression "
                f"{expression!r}. The table is data; it may not call, subscript or assign."
            )

    return bool(_eval(tree.body, env))


# --- The dispatch switch ----------------------------------------------------


def decide(
    score: Score,
    context: Mapping[str, Any] | None = None,
    table: "RuleTable | None" = None,
) -> Decision:
    """Map a score plus context to one of five actions, deterministically.

    Args:
        score: The seven axes. Produced by scrutiny.score, which may call a model.
        context: Signal metadata the table can read as `context.*` — channel, source,
            speaker_verified, and so on. A missing key evaluates as False rather than
            raising, so one table serves every channel.
        table: Loaded rule table. Defaults to the process-wide table from
            config/scrutiny.yaml.

    Returns:
        A Decision carrying the action AND the name of the single rule that fired.

    Raises:
        PolicyError: the table is malformed, or no rule matched. The shipped table ends in
            an explicit `floor` rule, so "no rule matched" means someone deleted it.
    """
    table = table or load_table()
    env: dict[str, Any] = {
        **score.as_dict(),
        "thresholds": table.thresholds,
        "context": dict(context or {}),
    }

    for rule in table.rules:
        if evaluate(rule.when, env):
            return Decision(action=rule.action, rule=rule.name, why=rule.why)

    raise PolicyError(
        "no rule matched and the table has no `floor` rule. Every decision must name the "
        "rule that produced it; restore the explicit floor in config/scrutiny.yaml."
    )


# --- The table --------------------------------------------------------------


@dataclass(frozen=True)
class Rule:
    """One row of the threshold table."""

    name: str
    when: str
    action: Action
    why: str = ""


@dataclass(frozen=True)
class RuleTable:
    """The loaded table: thresholds plus ordered rules.

    Order is the design. Guards precede permissions so that no combination of scores can
    reach `act` without first failing every guard.
    """

    thresholds: Mapping[str, float]
    rules: tuple[Rule, ...]

    def rule(self, name: str) -> Rule:
        for r in self.rules:
            if r.name == name:
                return r
        raise PolicyError(f"no rule named {name!r}")


def load_table(path: str | None = None) -> RuleTable:
    """Load and validate config/scrutiny.yaml.

    Validation is not optional and is not deferred to first use:

    - every rule has a name, a `when` and an action that is one of the five
    - rule names are unique, since decisions are keyed on them
    - every `when` parses under the restricted grammar, so a typo fails at startup rather
      than at 3am on the one signal that reaches it
    - a `floor` rule exists, so no decision can ever lack a rule name

    Raises:
        PolicyError: on any of the above.

    Implemented in week 7 alongside the scorer. The parsing and validation above is the
    whole of it; there is no clever loading to write.
    """
    raise NotImplementedError(
        "scrutiny.policy.load_table is implemented in week 7. "
        "Pass an explicit RuleTable to decide() until then; the dispatch logic above is "
        "complete and tests/test_policy.py exercises it against a table built in-process."
    )
