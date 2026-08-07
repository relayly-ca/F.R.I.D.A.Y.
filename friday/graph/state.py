"""Shared state, and the record of what a run has done. ADR-0012.

State is the third element of the graph vocabulary, after jobs and arrows: the shared record
of what the system knows so far, carried between nodes and mutated by them.

It is a pydantic model rather than a dict for the reason everything else here is: a node that
writes `stt.transcript` where the next node reads `transcript` fails at the boundary instead
of silently reading None, and a run that fails at the boundary is one you can diagnose from
a checkpoint.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RunStatus(str, Enum):
    """Where a run is.

    `SUSPENDED` is distinct from `FAILED` and from `WAITING` and the distinction matters:

      WAITING    parked at a human gate. Resumes when you answer.
      SUSPENDED  parked because something else took priority - a barge-in `new_task`
                 (ADR-0019), or a supervisor budget kill. Resumable, and nothing is waiting
                 on you. "Where were we" finds these.
      FAILED     will not resume. A node raised and the graph has no path forward.
    """

    PENDING = "pending"
    RUNNING = "running"
    WAITING = "waiting"
    SUSPENDED = "suspended"
    DONE = "done"
    FAILED = "failed"
    KILLED = "killed"


class NodeRecord(BaseModel):
    """One node execution, as it lands in the checkpoint.

    Kept per node rather than per run because the useful question after a failure is "which
    node, on what input, having spent what" - and a per-run total answers none of it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    node: str
    started_at: datetime
    ended_at: datetime | None = None
    tokens: int = 0
    agent: str | None = None
    error: str | None = None
    # ADR-0013. Set on a checker node to the node it checked, so "was this write checked, and
    # by a different agent" is answerable from the checkpoint rather than from the code.
    checked: str | None = None


class GraphState(BaseModel):
    """The shared record carried through a run.

    Not frozen - nodes mutate it, that is what state is for. Every mutation is captured by
    the checkpoint after the node returns, so the history is immutable even though the object
    is not.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    graph: str
    status: RunStatus = RunStatus.PENDING
    started_at: datetime
    updated_at: datetime

    # The node to enter on resume. This single field is what makes a budget kill cheap
    # (ADR-0012) and a barge-in `new_task` recoverable (ADR-0019).
    cursor: str | None = None

    history: list[NodeRecord] = Field(default_factory=list)
    data: dict[str, Any] = Field(default_factory=dict)

    # Aggregated from history. The supervisor reads these to enforce the per-task ceilings in
    # config/agents.yaml; they are NOT enforced here, because a budget the budgeted process
    # enforces on itself is a suggestion (spec section 9).
    tokens_spent: int = 0
    wall_clock_s: float = 0.0

    # Set when a barge-in or a kill suspended this run in favour of something else.
    suspended_for: str | None = None

    def spend(self, tokens: int) -> None:
        """Record token spend from a node.

        Raises:
            NotImplementedError: W5.
        """
        raise NotImplementedError(
            "friday.graph.state.GraphState.spend is implemented in W5. It appends to history "
            "and updates the aggregate; it does NOT enforce a ceiling - the supervisor does "
            "that, from outside, as a different user."
        )
