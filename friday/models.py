"""Core domain types.

Two things in here carry real weight and the rest is plumbing.

**Sensitivity is a property of DATA, not of a request.** ADR-0008: routing resolves
sensitivity first, from a fixed table, before any capability consideration. That only works
if every row carries a class, which is why `Event.sensitivity` has no default. A source
without a class is a bug, and a default would turn that bug into a silent downgrade.

**Timestamps are timezone-aware or they are rejected.** Spec section 10 names temporal
reasoning as a place this breaks, and spec section 7 says to resolve dates in code. A naive
datetime is the exact shape of that failure: it looks correct, compares correctly against
other naive datetimes, and is wrong by a fixed offset that reads as a retrieval problem for
about two days.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Sensitivity(str, Enum):
    """The sensitivity class of a piece of data. Spec section 8, ADR-0008.

    Spec section 8: "Vault, health, messages and finances resolve to local aliases by
    config, not by preference." Those four are the named classes; `ANY` is everything else
    and is still explicit, because "unclassified" and "not sensitive" must not be the same
    value.
    """

    VAULT = "vault"
    HEALTH = "health"
    MESSAGES = "messages"
    FINANCES = "finances"
    ANY = "any"


class Routing(str, Enum):
    """Where a call is permitted to resolve. Distinct from Sensitivity, deliberately.

    `Sensitivity` classifies data; `Routing` constrains a call. `config/agents.yaml` uses
    this one on each agent, and `sensitivity_routing` is the map between them. Collapsing
    the two into one enum reads as a simplification and loses the direction of the mapping.
    """

    LOCAL_ONLY = "local_only"
    ANY = "any"


class Action(str, Enum):
    """The five actions, mirrored from scrutiny.policy for use outside that package.

    `scrutiny.policy.Action` is the authority. This exists so `friday.*` can name an action
    in a mode suppression list or a dispatch record without importing the scrutiny package,
    which keeps the dependency pointing one way.

    ADR-0002: exactly five, and `act` and `propagate` are distinct.
    """

    ACT = "act"
    ASK = "ask"
    WATCH = "watch"
    IGNORE = "ignore"
    PROPAGATE = "propagate"


class Mode(str, Enum):
    """Conversation modes. Spec section 6 week 6, implemented in W6."""

    ASSIST = "assist"
    BRAINSTORM = "brainstorm"
    FOCUS = "focus"
    AWAY = "away"


# --- Untrusted content -------------------------------------------------------
# Spec section 9: "Everything ingested gets wrapped and marked. Mitigation, not a fix -
# assume it can fail."
#
# ADR-0006 is the standard this is measured against, and this function does not meet it on
# its own, by design. It is a marker. The boundary that survives this failing is elsewhere:
# the scorer that reads this text has tools: [] (config/agents.yaml), the dispatch switch is
# a deterministic table rather than a model choosing, and consequential actions route
# through `ask` and a human.
#
# The test for anything proposed alongside this: does it still hold if the model does
# exactly what the injected text asked?

UNTRUSTED_OPEN = "<untrusted source={source!r} id={external_id!r} at={occurred_at}>"
UNTRUSTED_CLOSE = "</untrusted>"


def wrap_untrusted(body: str, *, source: str, external_id: str, occurred_at: datetime) -> str:
    """Wrap and mark ingested text.

    Applied on write, in exactly one place (`friday.ingest.base`), so that no source can
    forget it. Sources do not call this themselves; the base writer does.

    The delimiters are stripped from the body first. Without that, ingested text can close
    the wrapper and continue outside it, which turns the marker into a decoration that makes
    the content look MORE trustworthy than unmarked text would.
    """
    cleaned = body.replace("</untrusted>", "").replace("<untrusted", "")
    header = UNTRUSTED_OPEN.format(
        source=source, external_id=external_id, occurred_at=occurred_at.isoformat()
    )
    return f"{header}\n{cleaned}\n{UNTRUSTED_CLOSE}"


# --- Records -----------------------------------------------------------------


class _Strict(BaseModel):
    """Base for every record type. Unknown fields are an error, not an ignored key."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise ValueError(
            "naive datetime. Every timestamp in this system carries a timezone: spec "
            "section 7 injects the current date and time into every prompt, and spec "
            "section 10 says to resolve dates in code. A naive datetime is wrong by a "
            "fixed offset and reads as a retrieval problem."
        )
    return value


class Event(_Strict):
    """One signal from one source, as it lands in `sources.db`.

    `(source, external_id)` is the idempotency key. A re-poll after a crash upserts rather
    than duplicating, which is what makes every ingest module safely re-runnable.

    For a recurring calendar series, `external_id` MUST include the occurrence date. The
    series UID alone collapses every occurrence onto one row, and "what's my week look like"
    then returns one meeting. See docs/weeks/W2.md.
    """

    source: str
    external_id: str
    occurred_at: datetime
    body: str

    # No default. ADR-0008: a source without a class is a bug, and a default here would
    # quietly route health data through a rule written for calendar entries.
    sensitivity: Sensitivity

    # Defaults to True and is not a per-source decision. A source that believes its input is
    # trustworthy is a source that has not been attacked yet.
    untrusted: bool = True

    # Room, sender, thread, message-id, path. Anything a source wants to carry that is not
    # one of the fields above. Stored as JSON; queried with json_extract.
    meta: dict[str, Any] = Field(default_factory=dict)

    ingested_at: datetime | None = None

    @field_validator("occurred_at", "ingested_at")
    @classmethod
    def _aware(cls, v: datetime | None) -> datetime | None:
        return None if v is None else _require_aware(v)

    @field_validator("source", "external_id")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("source and external_id must be non-empty: they are the upsert key")
        return v

    def key(self) -> tuple[str, str]:
        return (self.source, self.external_id)


class Chunk(_Strict):
    """One retrievable unit, as it lands in Qdrant and FTS5.

    Provenance is not optional. Spec section 7: "Always carry source and timestamp so she
    can say 'you told me this in March, it may be stale.'" It is also how you find the
    source of a wrong answer, which is the use you will get more mileage out of.
    """

    chunk_id: str
    source: str
    external_id: str
    occurred_at: datetime
    sensitivity: Sensitivity
    text: str
    ordinal: int = 0
    meta: dict[str, Any] = Field(default_factory=dict)

    @field_validator("occurred_at")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        return _require_aware(v)


class Retrieved(_Strict):
    """A chunk that survived the pipeline, with the scores that got it there.

    Spec section 7's pipeline is expand, parallel keyword and vector, dedupe, rerank to
    top 8, recency boost. Each stage's score is kept rather than collapsed into one number,
    because `--explain` is the only tool that tells you which stage dropped the answer, and
    in week 4 it is the only thing that tells you which new source broke the eval.
    """

    chunk: Chunk
    keyword_rank: int | None = None
    vector_rank: int | None = None
    fused_score: float | None = None
    rerank_score: float | None = None
    final_score: float | None = None

    @property
    def age_days(self) -> float | None:
        """Days since `occurred_at`. Used for the recency boost and the staleness qualifier.

        Returns None rather than computing against `datetime.now()` here: this module does
        not read the clock, so a Retrieved is reproducible from a stored result. The caller
        passes the reference time in.
        """
        return None


class Decision(_Strict):
    """A scrutiny decision as it is persisted. Mirrors scrutiny.policy.Decision plus context.

    `rule` is never empty. ADR-0002: every decision names the rule that produced it, and a
    decision with no rule name is a bug rather than a fallback. The correction ledger, the
    accuracy report and the `floor`-rate health metric all key on it.
    """

    decision_id: str
    signal_id: str
    action: Action
    rule: str
    scores: dict[str, float | bool]
    decided_at: datetime

    @field_validator("rule")
    @classmethod
    def _named(cls, v: str) -> str:
        if not v.strip():
            raise ValueError(
                "empty rule name. ADR-0002: a decision with no rule is a bug, not a "
                "fallback. config/scrutiny.yaml ends in an explicit `floor` rule so that "
                "this cannot happen; if it did, the floor was deleted."
            )
        return v

    @field_validator("decided_at")
    @classmethod
    def _aware(cls, v: datetime) -> datetime:
        return _require_aware(v)
