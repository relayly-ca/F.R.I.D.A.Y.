"""Adaptive Scrutiny. Spec section 4: the decision layer no other project ships.

Every incoming signal - a message, a calendar change, an observed pattern, the end of a
brainstorm session - is scored on seven axes and dispatched to one of five actions.

    score.py        may call a model. Produces seven numbers, never an action.
    policy.py       may not. Pure rule table, first match wins, names the rule.
    corrections.py  the ledger. Spec section 10: log every correction from day one.
    daemon.py       the long-running process that wires the three together.

Why the split (ADR-0002, ADR-0006): scoring rejects low-value signals before the expensive
model is invoked, which is what makes the system usable rather than annoying. And a
deterministic table between model output and consequential action means prompt injection
can move a score but cannot pick an action.

Implemented rather than taken as a dependency. OpenAGI ships the pattern under PolyForm
Noncommercial, which is source-available and not open source; ADR-0003 records the
decision to write the ~200 lines instead and keep the stack license-clean.

Configuration: config/scrutiny.yaml. Built in week 7.
"""

from scrutiny.policy import Action, Decision, PolicyError, decide
from scrutiny.score import AXES, Score, ScoreError

__all__ = [
    "AXES",
    "Action",
    "Decision",
    "PolicyError",
    "Score",
    "ScoreError",
    "decide",
]
