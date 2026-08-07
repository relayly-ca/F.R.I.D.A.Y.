"""Checkpoint persistence. ADR-0012.

`pydantic_graph` types nodes, edges and state and does not persist them. This is the half
that makes a graph worth having in an always-on system: a run has a position on disk, so
being interrupted is cheap.

Three things depend on that and none of them work without it:

  - **The supervisor's budget kill** (spec section 9). A killed task that resumes at the node
    it died on is cheap to kill. One that restarts from nothing is expensive, and an
    expensive kill is one you avoid using - at which point the budget is decorative.
  - **Barge-in `new_task`** (ADR-0019). "Actually, what's the weather" suspends the current
    run rather than discarding it, which is what makes "where were we" work.
  - **`keep_branch_on_kill` and `revert_vault_on_kill`** (config/friday.toml). Both are about
    leaving nothing half-applied, and neither is coherent without a position to return to.

SQLite under `/srv/friday/db/`, covered by `make backup`.

Implemented in W5.
"""

from __future__ import annotations

from pathlib import Path

from friday.graph.state import GraphState, RunStatus


def init_db(path: Path | None = None) -> None:
    """Create the checkpoint schema. Idempotent.

    Raises:
        NotImplementedError: W5.
    """
    raise NotImplementedError("friday.graph.checkpoint.init_db is implemented in W5")


def save(state: GraphState) -> None:
    """Persist a run's position and state. Called after EVERY node, not on completion.

    After every node is the whole point. Checkpointing at intervals, or on completion, leaves
    exactly the window where a kill loses work - and the kill is not a rare event here, it is
    a designed one.

    Raises:
        NotImplementedError: W5.
    """
    raise NotImplementedError("friday.graph.checkpoint.save is implemented in W5")


def load(run_id: str) -> GraphState:
    """Load a run's state.

    Raises:
        KeyError: no such run.
        NotImplementedError: W5.
    """
    raise NotImplementedError("friday.graph.checkpoint.load is implemented in W5")


def resumable(graph: str | None = None) -> list[GraphState]:
    """Runs that can be resumed: WAITING, SUSPENDED, or KILLED.

    This is what answers "where were we" after a barge-in, and what the supervisor consults
    after a revert.

    Raises:
        NotImplementedError: W5.
    """
    raise NotImplementedError("friday.graph.checkpoint.resumable is implemented in W5")


def suspend(run_id: str, *, reason: str, status: RunStatus = RunStatus.SUSPENDED) -> None:
    """Park a run at its current cursor, without discarding it.

    Used by the supervisor's budget kill and by barge-in's `new_task`. Distinct from a
    failure: a suspended run has a future.

    Raises:
        NotImplementedError: W5.
    """
    raise NotImplementedError("friday.graph.checkpoint.suspend is implemented in W5")
