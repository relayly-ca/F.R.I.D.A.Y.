"""The seven axes, and the scorer that produces them. Spec section 4.

The split this module exists to enforce: score.py MAY call a model. policy.py may not.
The model produces seven numbers; Python turns them into an action. Injected text can move
a number, and it cannot move a rule.

The scorer runs on `fast` (the 4B router) with `tools: []`. Both matter:

  - `fast`, because the whole economic argument for this layer is that it rejects
    low-value signals BEFORE the expensive model is invoked. Scoring on `daily` would
    make triage cost more than skipping triage.
  - `tools: []`, because this is the one place ingested text reaches a model. Instructions
    hidden in an email have nothing to call. ADR-0006.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping

# Exactly these seven, in this order. Spec section 4. Adding or removing one is a schema
# change touching this module, config/scrutiny.yaml and the tests, and it needs an ADR.
AXES = (
    "urgency",
    "impact",
    "novelty",
    "risk",
    "confidence",
    "specificity",
    "conflict",
)


class ScoreError(Exception):
    """Raised when a model returns something that is not a valid score.

    Deliberately fatal rather than lenient. A scorer that silently substitutes defaults for
    a malformed response produces decisions that look principled and are not, and the
    threshold table cannot tell the difference.
    """


@dataclass(frozen=True)
class Score:
    """The seven axes for one signal.

    Six floats in 0.0-1.0 and one boolean. `conflict` is a boolean because a signal either
    contradicts something already recorded or it does not; a 0.4 conflict is not a thing.

    Frozen, because a decision must be reproducible from the score that produced it. If
    something mutated a Score after the fact, the correction ledger would record a score
    that never existed.
    """

    urgency: float
    impact: float
    novelty: float
    risk: float
    confidence: float
    specificity: float
    conflict: bool = False

    def __post_init__(self) -> None:
        for axis in AXES:
            value = getattr(self, axis)
            if axis == "conflict":
                if not isinstance(value, bool):
                    raise ScoreError(f"conflict must be a bool, got {type(value).__name__}")
                continue
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ScoreError(f"{axis} must be a number, got {type(value).__name__}")
            if not 0.0 <= float(value) <= 1.0:
                raise ScoreError(f"{axis} must be in 0.0-1.0, got {value}")

    def as_dict(self) -> dict[str, Any]:
        """The environment the rule table is evaluated against."""
        return asdict(self)


def score_signal(
    body: str,
    context: Mapping[str, Any] | None = None,
) -> Score:
    """Score one signal on the seven axes. The only place ingested text meets a model.

    Contract:
      - Runs the `scorer` agent from config/agents.yaml: `fast`, tools [], temperature 0,
        400 tokens.
      - `body` is UNTRUSTED and is wrapped and marked before it reaches the prompt. That
        tagging is mitigation, not a fix (spec section 9) - the boundary is the empty tool
        list, not the wrapping.
      - Returns a Score. Never returns, suggests, or names an action. If a future prompt
        change makes the model emit an action, that is a bug even if the action is right.
      - `novelty` requires a retrieval lookup against the vault: something already recorded
        is not new however good it is. That lookup is read-only and pre-computed by the
        caller, arriving here as `context`.

    Raises:
        ScoreError: the model returned a malformed or out-of-range score.

    Implemented in week 7. Spec section 6 puts Adaptive Scrutiny at week 7, after memory,
    voice and tools, because `novelty` is meaningless without a populated vault and
    `specificity` is hard to judge without the tool surface that would execute the action.
    """
    raise NotImplementedError("scrutiny.score.score_signal is implemented in week 7")


def parse_score(raw: str) -> Score:
    """Parse the model's JSON response into a Score.

    Strict. A missing axis, an extra axis, a value out of range or unparseable JSON all
    raise rather than being repaired. A repaired score is a guess wearing a number.

    Implemented in week 7.
    """
    raise NotImplementedError("scrutiny.score.parse_score is implemented in week 7")
