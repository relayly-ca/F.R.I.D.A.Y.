"""The threshold table. Spec section 4.

These tests RUN TODAY and pass. `scrutiny.policy.decide` is pure, so it needs no model, no
database and no services — which is the whole point of the score/decide split and is worth
demonstrating rather than asserting.

    uv run pytest tests/test_policy.py -v

The table under test is built in-process from config/scrutiny.yaml's contents, so these
tests exercise the real rules and the real evaluator without depending on
`policy.load_table`, which lands in week 7 along with the scorer.

What is being protected:

  1. Seven axes, five actions. An earlier draft of this scaffold had five and four, with
     `act` missing entirely. ADR-0002 exists because of that.
  2. `act` and `propagate` are reachable and distinct. Specificity separates them.
  3. Guards fire before permissions. No combination of scores reaches `act` past a guard.
  4. Every decision names a rule. An unexplained correct answer cannot be audited.
  5. `decide` is deterministic. If this fails, something in policy.py reads a clock, a
     database, a random source or a model, and it is no longer a rule table.
  6. The expression evaluator refuses anything that is not a comparison. The table is data
     that ingested text influences indirectly; it must never become code.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scrutiny.policy import Action, PolicyError, Rule, RuleTable, decide, evaluate
from scrutiny.score import AXES, Score, ScoreError

CONFIG = Path(__file__).resolve().parents[1] / "config" / "scrutiny.yaml"


@pytest.fixture(scope="module")
def table() -> RuleTable:
    """The real table from config/scrutiny.yaml.

    Built here rather than via policy.load_table so these tests pass before week 7. When
    load_table lands it must produce exactly this, and test_load_table_matches_fixture
    below becomes the check.
    """
    raw = yaml.safe_load(CONFIG.read_text())
    return RuleTable(
        thresholds=raw["thresholds"],
        rules=tuple(
            Rule(name=r["name"], when=r["when"], action=Action(r["action"]), why=r.get("why", ""))
            for r in raw["rules"]
        ),
    )


def score(**overrides: float | bool) -> Score:
    """A neutral score. Tests override only the axes under test.

    Keeping the baseline in one place means a test that passes for the wrong reason — a
    default that happens to trip the rule — shows up as a missing override.
    """
    base: dict[str, float | bool] = {
        "urgency": 0.5,
        "impact": 0.5,
        "novelty": 0.5,
        "risk": 0.1,
        "confidence": 0.8,
        "specificity": 0.5,
        "conflict": False,
    }
    base.update(overrides)
    return Score(**base)  # type: ignore[arg-type]


def assert_decided(decision: object, expected: Action, rule: str | None = None) -> None:
    """Assert the action, that a rule is named, and optionally which rule."""
    assert decision.action is expected, (  # type: ignore[attr-defined]
        f"expected {expected}, got {decision.action} from rule {decision.rule!r}"  # type: ignore[attr-defined]
    )
    assert decision.rule, "decision carries no rule name; an unexplained decision is a bug"  # type: ignore[attr-defined]
    if rule is not None:
        assert decision.rule == rule  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# The shape of the thing. Spec section 4.
# ---------------------------------------------------------------------------
def test_seven_axes() -> None:
    """Exactly seven axes, exactly these, in this order."""
    assert AXES == (
        "urgency", "impact", "novelty", "risk", "confidence", "specificity", "conflict",
    )
    assert len(AXES) == 7


def test_five_actions() -> None:
    """Exactly five actions. `act` is one of them.

    The earlier draft had four and was missing `act`, which meant nothing could ever be
    done directly — everything either asked or went to a specialist.
    """
    assert {a.value for a in Action} == {"act", "ask", "watch", "ignore", "propagate"}
    assert len(Action) == 5


def test_config_declares_the_same_seven_axes() -> None:
    """config/scrutiny.yaml and scrutiny.score do not drift apart."""
    raw = yaml.safe_load(CONFIG.read_text())
    assert tuple(raw["axes"].keys()) == AXES


def test_every_rule_has_a_name_and_a_reason(table: RuleTable) -> None:
    """A rule you cannot explain is a rule you cannot correct."""
    for rule in table.rules:
        assert rule.name
        assert rule.when
        assert rule.why.strip(), f"rule {rule.name} has no `why`"
    names = [r.name for r in table.rules]
    assert len(names) == len(set(names)), "rule names must be unique; decisions key on them"


def test_table_ends_in_an_explicit_floor(table: RuleTable) -> None:
    """The last rule matches everything, so no decision can lack a rule name."""
    last = table.rules[-1]
    assert last.name == "floor"
    assert last.when.strip() == "true"


# ---------------------------------------------------------------------------
# Guards. These fire first and cannot be overridden.
# ---------------------------------------------------------------------------
def test_high_risk_always_asks(table: RuleTable) -> None:
    """Risk dominates every other axis.

    Everything else here argues for acting: novel, high impact, urgent, maximally
    confident, perfectly specific. It still asks. Confidence is not authorisation, and
    this is the rule that makes bounded autonomy real.
    """
    s = score(risk=0.9, novelty=0.9, impact=0.95, urgency=0.9, confidence=0.98, specificity=0.95)
    assert_decided(decide(s, {"kind": "send_message"}, table), Action.ASK, "high_risk_always_asks")


def test_conflict_asks(table: RuleTable) -> None:
    """A contradiction is a human's call.

    She can know there is a conflict; she cannot know which side is true. Resolving it
    silently overwrites a true memory with a false one and the vault cannot notice.
    """
    s = score(conflict=True, confidence=0.95, specificity=0.9, impact=0.8)
    assert_decided(decide(s, {"kind": "fact"}, table), Action.ASK, "conflict_asks")


def test_unverified_voice_asks(table: RuleTable) -> None:
    """Spec section 9: Resemblyzer gate on every voice command.

    An unverified speaker may be answered; nothing consequential happens without you.
    """
    s = score(confidence=0.95, specificity=0.95, impact=0.8, risk=0.1)
    ctx = {"channel": "voice", "speaker_verified": False}
    assert_decided(decide(s, ctx, table), Action.ASK, "unverified_speaker_asks")


def test_verified_voice_is_not_blocked_by_the_speaker_guard(table: RuleTable) -> None:
    """The gate is not a blanket refusal of the voice channel."""
    s = score(confidence=0.95, specificity=0.95, impact=0.8, risk=0.1)
    ctx = {"channel": "voice", "speaker_verified": True}
    assert_decided(decide(s, ctx, table), Action.ACT, "determined_and_safe_acts")


def test_missing_context_key_does_not_raise(table: RuleTable) -> None:
    """A Matrix message has no speaker at all; one table serves every channel."""
    s = score(confidence=0.95, specificity=0.95, impact=0.8)
    assert_decided(decide(s, {"kind": "message"}, table), Action.ACT)


def test_low_confidence_watches(table: RuleTable) -> None:
    """Uncertainty goes to `watch`, not to `ask`.

    Interrupting you every time the scorer is unsure trains you to approve reflexively,
    which is worse than not asking.
    """
    s = score(confidence=0.2, impact=0.8, novelty=0.8, specificity=0.9)
    assert_decided(decide(s, {"kind": "idea"}, table), Action.WATCH, "low_confidence_watches")


# ---------------------------------------------------------------------------
# Floors. Cheap rejections before anything expensive.
# ---------------------------------------------------------------------------
def test_already_known_is_ignored(table: RuleTable) -> None:
    """A good idea already in the vault is not news.

    Without this the same idea is re-proposed every time it is mentioned, and the inbox
    becomes something you stop reading.
    """
    s = score(novelty=0.05, impact=0.85, confidence=0.9)
    assert_decided(decide(s, {"kind": "idea"}, table), Action.IGNORE, "already_known")


def test_low_impact_and_not_urgent_is_ignored(table: RuleTable) -> None:
    """Novel is not the same as worth knowing.

    Most of what a microphone and a mail spool observe is new and does not matter.
    """
    s = score(impact=0.1, urgency=0.1, novelty=0.9, confidence=0.9)
    assert_decided(decide(s, {"kind": "observation"}, table), Action.IGNORE, "below_threshold")


def test_low_impact_but_urgent_is_not_ignored(table: RuleTable) -> None:
    """Urgency rescues a low-impact signal from the floor. Both halves of the rule matter."""
    s = score(impact=0.1, urgency=0.9, novelty=0.9, confidence=0.9, specificity=0.2)
    assert decide(s, {"kind": "observation"}, table).action is not Action.IGNORE


# ---------------------------------------------------------------------------
# Permissions. The two that do something.
# ---------------------------------------------------------------------------
def test_determined_and_safe_acts(table: RuleTable) -> None:
    """Everything known: what to do, that it matters, that being wrong is cheap.

    The narrowest rule in the table and it should stay that way.
    """
    s = score(confidence=0.9, specificity=0.9, risk=0.1, impact=0.7, novelty=0.7)
    assert_decided(decide(s, {"kind": "request"}, table), Action.ACT, "determined_and_safe_acts")


def test_important_but_undetermined_propagates(table: RuleTable) -> None:
    """The goal is clear and the path is not: hand it to a bounded specialist.

    Specificity is the axis that separates this from `act`. Same confidence, same risk,
    same impact as the test above; only specificity differs, and the action changes.
    """
    s = score(confidence=0.9, specificity=0.2, risk=0.1, impact=0.8, urgency=0.3, novelty=0.7)
    assert_decided(
        decide(s, {"kind": "idea"}, table), Action.PROPAGATE, "important_but_undetermined_propagates"
    )


def test_specificity_is_what_separates_act_from_propagate(table: RuleTable) -> None:
    """Stated directly, because collapsing these two is the mistake ADR-0002 exists for."""
    common = {"confidence": 0.9, "risk": 0.1, "impact": 0.8, "urgency": 0.3, "novelty": 0.7}
    assert decide(score(**common, specificity=0.9), {}, table).action is Action.ACT  # type: ignore[arg-type]
    assert decide(score(**common, specificity=0.2), {}, table).action is Action.PROPAGATE  # type: ignore[arg-type]


def test_urgent_and_undetermined_asks(table: RuleTable) -> None:
    """Urgent and unclear is the worst thing to hand a specialist.

    The budget expires before the ambiguity resolves. Ask; you will resolve it in ten
    seconds.
    """
    s = score(urgency=0.9, specificity=0.2, confidence=0.9, impact=0.4, risk=0.1)
    assert_decided(decide(s, {"kind": "message"}, table), Action.ASK, "urgent_and_undetermined_asks")


def test_partially_determined_watches(table: RuleTable) -> None:
    """Worth something; not clear enough to act on, not important enough for a specialist."""
    s = score(confidence=0.9, specificity=0.5, impact=0.4, urgency=0.3, risk=0.1)
    assert_decided(decide(s, {"kind": "idea"}, table), Action.WATCH, "partially_determined_watches")


# ---------------------------------------------------------------------------
# Properties of the table as a whole.
# ---------------------------------------------------------------------------
def test_all_five_actions_are_reachable(table: RuleTable) -> None:
    """Every action is produced by some score.

    An unreachable action means a dead branch, and a dead branch in a rule table is
    usually a rule that was meant to fire and does not.
    """
    produced = {
        decide(score(risk=0.9), {}, table).action,
        decide(score(confidence=0.2), {}, table).action,
        decide(score(novelty=0.05), {}, table).action,
        decide(score(confidence=0.9, specificity=0.9, impact=0.7), {}, table).action,
        decide(score(confidence=0.9, specificity=0.2, impact=0.8, urgency=0.3), {}, table).action,
    }
    assert produced == {Action.ASK, Action.WATCH, Action.IGNORE, Action.ACT, Action.PROPAGATE}


def test_guards_precede_permissions(table: RuleTable) -> None:
    """Rule ORDER is the design, not an accident of authorship.

    Each guard must appear before every permission, so no combination of scores can route
    around it.
    """
    order = [r.name for r in table.rules]
    guards = ["high_risk_always_asks", "conflict_asks", "unverified_speaker_asks",
              "low_confidence_watches"]
    permissions = ["determined_and_safe_acts", "important_but_undetermined_propagates"]
    for g in guards:
        for p in permissions:
            assert order.index(g) < order.index(p), f"{g} must be evaluated before {p}"


@pytest.mark.parametrize(
    "s",
    [
        score(risk=0.9),
        score(confidence=0.2),
        score(novelty=0.05),
        score(confidence=0.9, specificity=0.9, impact=0.7),
        score(confidence=0.9, specificity=0.2, impact=0.8, urgency=0.3),
        score(conflict=True),
    ],
)
def test_decide_is_deterministic(s: Score, table: RuleTable) -> None:
    """Same score, same context, same decision and same rule. Every time.

    If this fails, something in policy.py is reading a clock, a random source, a database
    or a model. Any of those means it is not a rule table.
    """
    first = decide(s, {"kind": "x"}, table)
    for _ in range(50):
        again = decide(s, {"kind": "x"}, table)
        assert again.action is first.action
        assert again.rule == first.rule


def test_no_rule_matched_raises_rather_than_defaulting(table: RuleTable) -> None:
    """Strip the floor and decide() refuses instead of inventing an action.

    A silent default would produce decisions with no rule name, which the whole audit
    trail depends on.
    """
    headless = RuleTable(thresholds=table.thresholds, rules=table.rules[:-1])
    # Chosen to clear every guard and floor and to match no permission: specificity high
    # enough to fall past partially_determined_watches, confidence too low for either
    # permission rule. In the shipped table this lands on `floor`.
    unmatched = score(
        urgency=0.5, impact=0.5, novelty=0.5, risk=0.1, confidence=0.6, specificity=0.9
    )
    assert decide(unmatched, {}, table).rule == "floor"
    with pytest.raises(PolicyError):
        decide(unmatched, {}, headless)


# ---------------------------------------------------------------------------
# The expression evaluator. The table is data; it must never become code.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "expr",
    [
        "__import__('os').system('id')",
        "open('/etc/passwd').read()",
        "risk.__class__.__bases__",
        "[x for x in (1, 2)]",
        "risk if impact else urgency",
        "{'a': 1}",
        "risk + 1 > 0",
    ],
)
def test_evaluator_refuses_anything_that_is_not_a_comparison(expr: str) -> None:
    """Calls, subscripts, comprehensions, arithmetic and literals-as-containers all raise.

    Rule expressions are influenced, indirectly, by text an attacker wrote. eval() is
    never used and the whitelist is deliberately narrow.
    """
    with pytest.raises(PolicyError):
        evaluate(expr, {"risk": 0.5, "impact": 0.5, "urgency": 0.5})


def test_evaluator_rejects_unknown_names() -> None:
    """A typo in a threshold name fails loudly rather than evaluating as False.

    Silently false would disable a rule, and a disabled guard is the worst failure this
    table can have.
    """
    with pytest.raises(PolicyError):
        evaluate("rsik >= 0.6", {"risk": 0.9})


def test_evaluator_handles_the_real_expressions(table: RuleTable) -> None:
    """Every `when` in the shipped table parses and evaluates.

    A typo in config/scrutiny.yaml must surface here, not at 3am on the one signal that
    reaches that rule.
    """
    env = {**score().as_dict(), "thresholds": table.thresholds, "context": {}}
    for rule in table.rules:
        assert isinstance(evaluate(rule.when, env), bool), f"rule {rule.name} did not evaluate"


# ---------------------------------------------------------------------------
# Score validation.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("axis", [a for a in AXES if a != "conflict"])
def test_axes_must_be_in_range(axis: str) -> None:
    """Out of range raises rather than being clamped. A clamped score is a guess."""
    with pytest.raises(ScoreError):
        score(**{axis: 1.5})  # type: ignore[arg-type]


def test_conflict_must_be_a_bool() -> None:
    """A signal either contradicts something recorded or it does not. 0.4 is not a thing."""
    with pytest.raises(ScoreError):
        Score(0.5, 0.5, 0.5, 0.1, 0.8, 0.5, conflict=0.4)  # type: ignore[arg-type]


def test_score_is_frozen() -> None:
    """A decision must be reproducible from the score that produced it."""
    s = score()
    with pytest.raises(Exception):
        s.risk = 0.9  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Week 7.
# ---------------------------------------------------------------------------
def test_load_table_matches_fixture(table: RuleTable) -> None:
    """When load_table lands it must produce exactly the fixture these tests use.

    Week 7: load_table is implemented. This test verifies it produces the same table
    as the in-process fixture used by the rest of the suite.
    """
    from scrutiny.policy import load_table

    loaded = load_table(str(CONFIG))
    assert [r.name for r in loaded.rules] == [r.name for r in table.rules]
    assert loaded.thresholds == table.thresholds
