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
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from pydantic import TypeAdapter

from friday.graph.state import GraphState, RunStatus

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

_adapter: TypeAdapter[GraphState] = TypeAdapter(GraphState)


def _default_db_path() -> Path:
    """The checkpoint database path from config, or a fallback if config is unavailable."""
    try:
        from friday.config import get
        cfg = get()
        return Path(cfg.friday.paths.db) / "checkpoints.db"
    except Exception:
        return Path("/srv/friday/db/checkpoints.db")


def _resolve(path: Path | None) -> Path:
    """Resolve the database path, creating the parent directory if needed."""
    p = path or _default_db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS checkpoints (
    run_id      TEXT PRIMARY KEY,
    graph       TEXT NOT NULL,
    status      TEXT NOT NULL,
    cursor      TEXT,
    started_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    suspended_for TEXT,
    state_json  TEXT NOT NULL,
    saved_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _connect(path: Path | None = None) -> sqlite3.Connection:
    db = _resolve(path)
    conn = sqlite3.connect(str(db))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA strict=True")
    return conn


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def init_db(path: Path | None = None) -> None:
    """Create the checkpoint schema. Idempotent."""
    conn = _connect(path)
    try:
        conn.executescript(_SCHEMA)
        conn.commit()
    finally:
        conn.close()


def save(state: GraphState, path: Path | None = None) -> None:
    """Persist a run's position and state. Called after EVERY node, not on completion.

    After every node is the whole point. Checkpointing at intervals, or on completion, leaves
    exactly the window where a kill loses work - and the kill is not a rare event here, it is
    a designed one.
    """
    conn = _connect(path)
    try:
        state_json = _adapter.dump_json(state)
        conn.execute(
            """
            INSERT INTO checkpoints (run_id, graph, status, cursor, started_at,
                                      updated_at, suspended_for, state_json, saved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(run_id) DO UPDATE SET
                graph = excluded.graph,
                status = excluded.status,
                cursor = excluded.cursor,
                updated_at = excluded.updated_at,
                suspended_for = excluded.suspended_for,
                state_json = excluded.state_json,
                saved_at = datetime('now')
            """,
            (
                state.run_id,
                state.graph,
                state.status.value,
                state.cursor,
                state.started_at.isoformat(),
                state.updated_at.isoformat(),
                state.suspended_for,
                state_json,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load(run_id: str, path: Path | None = None) -> GraphState:
    """Load a run's state.

    Raises:
        KeyError: no such run.
    """
    conn = _connect(path)
    try:
        row = conn.execute(
            "SELECT state_json FROM checkpoints WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"no checkpoint for run_id={run_id!r}")
        return _adapter.validate_json(row["state_json"])
    finally:
        conn.close()


def resumable(graph: str | None = None, path: Path | None = None) -> list[GraphState]:
    """Runs that can be resumed: WAITING, SUSPENDED, or KILLED.

    This is what answers "where were we" after a barge-in, and what the supervisor consults
    after a revert.
    """
    statuses = (
        RunStatus.WAITING.value,
        RunStatus.SUSPENDED.value,
        RunStatus.KILLED.value,
    )
    placeholders = ",".join("?" for _ in statuses)
    conn = _connect(path)
    try:
        if graph is not None:
            rows = conn.execute(
                f"SELECT state_json FROM checkpoints "
                f"WHERE status IN ({placeholders}) AND graph = ? "
                f"ORDER BY saved_at DESC",
                (*statuses, graph),
            ).fetchall()
        else:
            rows = conn.execute(
                f"SELECT state_json FROM checkpoints "
                f"WHERE status IN ({placeholders}) "
                f"ORDER BY saved_at DESC",
                statuses,
            ).fetchall()
        return [_adapter.validate_json(r["state_json"]) for r in rows]
    finally:
        conn.close()


def suspend(run_id: str, *, reason: str, status: RunStatus = RunStatus.SUSPENDED,
            path: Path | None = None) -> None:
    """Park a run at its current cursor, without discarding it.

    Used by the supervisor's budget kill and by barge-in's `new_task`. Distinct from a
    failure: a suspended run has a future.
    """
    conn = _connect(path)
    try:
        row = conn.execute(
            "SELECT state_json FROM checkpoints WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            raise KeyError(f"no checkpoint for run_id={run_id!r}")
        state = _adapter.validate_json(row["state_json"])
        state.status = status
        state.suspended_for = reason
        state.updated_at = state.updated_at  # trigger field presence
        save(state, path)
    finally:
        conn.close()
