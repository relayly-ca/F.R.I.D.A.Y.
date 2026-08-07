"""The correction ledger. Spec section 10.

"Scrutiny false positives. She'll flag your complaining as a brainstorm. Log every
correction from day one - that's your fine-tuning set."

What a correction records, and why each field is needed:

    decision_id      which decision
    rule             WHICH RULE fired. The useful signal. An aggregate agreement rate is
                     nearly useless; one rule being wrong 40% of the time is the finding,
                     and it hides inside a healthy total.
    scores           the seven axes as scored. Distinguishes a bad rule from a bad score:
                     if the scores were right and the action was wrong, fix the table; if
                     the scores were wrong, fix the prompt.
    action_taken     what she did
    action_wanted    what you wanted
    note             optional, from you

Recording only `action_wanted` teaches nothing. That is the whole reason this module
exists as more than an UPDATE statement.
"""

from __future__ import annotations

from typing import Any, Mapping

from scrutiny.policy import Action
from scrutiny.score import Score


class CorrectionError(Exception):
    """Raised on a failed correction write: unknown decision id, already corrected."""


def record_correction(
    decision_id: str,
    action_wanted: Action,
    note: str | None = None,
) -> str:
    """Record a human override against a decision. Returns the correction id.

    Looks up the decision to capture the rule and the scores alongside the override, so a
    correction is self-contained: readable months later without joining against a table
    that may have been pruned.

    Correcting an already-corrected decision raises rather than recording a second row, so
    a double-click in the UI does not skew the accuracy report.

    Implemented in week 7.
    """
    raise NotImplementedError("scrutiny.corrections.record_correction is implemented in week 7")


def accuracy_by_rule(days: int = 30) -> list[Mapping[str, Any]]:
    """Per-rule agreement rate over a window. One row per rule that fired.

    Reports review volume next to agreement rate. A period with no corrections means
    either good triage or an inbox nobody read, and those must not look the same.

    Watch the `floor` rule specifically: a climbing floor rate means signals are falling
    through every rule in the table, which is a gap rather than a tuning problem.

    Implemented in week 7.
    """
    raise NotImplementedError("scrutiny.corrections.accuracy_by_rule is implemented in week 7")


def export_finetune_set(path: str) -> int:
    """Export the corrections as a training set. Returns the number of examples.

    Spec section 10 calls this out explicitly: the corrections ARE the fine-tuning set.
    Each example is the signal, the seven scores, the rule that fired, and the action you
    wanted.

    Implemented after week 8, once there is enough volume for it to mean anything.
    """
    raise NotImplementedError("scrutiny.corrections.export_finetune_set is implemented after week 8")


def init_db(path: str | None = None) -> None:
    """Create the corrections schema. Idempotent.

    Schema:
        decisions(id, ts, signal_id, rule, action, scores_json, context_json)
        corrections(id, decision_id, ts, rule, action_taken, action_wanted, scores_json, note)

    Decisions are written by the daemon on every signal, not only on corrected ones: the
    denominator of the agreement rate is every decision, and a ledger of only the mistakes
    cannot compute it.

    Implemented in week 7.
    """
    raise NotImplementedError("scrutiny.corrections.init_db is implemented in week 7")
