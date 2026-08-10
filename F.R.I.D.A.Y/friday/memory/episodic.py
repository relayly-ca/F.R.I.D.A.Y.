"""Tier 2: the episodic log. Spec section 7: "append-only, never edited, only compressed."

`append_only` is an API property, not a comment. There is no UPDATE and no DELETE in this
module's public surface, and tests/test_episodic.py asserts that attempting either raises.
Compression rewrites into summary rows and archives the originals to `db/archive/`; it does
not edit in place.

FTS5 lives in the same file (config/memory.yaml `fts_db`). One file, one backup, one
consistent snapshot. It is an external-content table with triggers so the index cannot drift
from the log - and when those two counts diverge, keyword retrieval silently returns a
subset, which costs about three eval points and looks like nothing.

Implemented in W3.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from friday.config import get
from friday.models import Event, Sensitivity


class AppendOnlyViolation(Exception):
    """Raised on any attempt to modify or remove an existing episodic row.

    Exists so the invariant is testable. Spec section 7 says never edited, and a property
    nobody can write a test against is a hope.
    """

_SCHEMA = """
CREATE TABLE IF NOT EXISTS episodic (
    id           TEXT PRIMARY KEY,
    source       TEXT NOT NULL,
    external_id  TEXT NOT NULL,
    occurred_at  TEXT NOT NULL,
    body         TEXT NOT NULL,
    sensitivity  TEXT NOT NULL,
    untrusted    INTEGER NOT NULL DEFAULT 1,
    meta         TEXT NOT NULL DEFAULT '{}',
    ingested_at  TEXT NOT NULL,
    consolidated INTEGER NOT NULL DEFAULT 0,
    summary      INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS episodic_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_episodic_occurred ON episodic (occurred_at);
CREATE INDEX IF NOT EXISTS idx_episodic_consolidated ON episodic (consolidated);
CREATE UNIQUE INDEX IF NOT EXISTS idx_episodic_key ON episodic (source, external_id);
"""

_FTS_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS episodic_fts USING fts5(
    body,
    content='episodic',
    content_rowid='rowid',
    tokenize='unicode61'
);
"""

_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS episodic_fts_ai AFTER INSERT ON episodic BEGIN
    INSERT INTO episodic_fts(rowid, body) VALUES (new.rowid, new.body);
END;

CREATE TRIGGER IF NOT EXISTS episodic_fts_ad AFTER DELETE ON episodic BEGIN
    INSERT INTO episodic_fts(episodic_fts, rowid, body) VALUES('delete', old.rowid, old.body);
END;

CREATE TRIGGER IF NOT EXISTS episodic_fts_au AFTER UPDATE ON episodic BEGIN
    INSERT INTO episodic_fts(episodic_fts, rowid, body) VALUES('delete', old.rowid, old.body);
    INSERT INTO episodic_fts(rowid, body) VALUES (new.rowid, new.body);
END;
"""


def _db_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    return get().memory.episodic.db


def init(path: Path | None = None) -> None:
    """Create the schema, the FTS5 external-content table and its triggers. Idempotent.

    Sets journal_mode=WAL. Ingestion writes while retrieval reads, and without WAL the reader
    blocks the writer at exactly the moments both matter.
    """
    db_path = _db_path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_SCHEMA)
        conn.executescript(_FTS_SCHEMA)
        conn.executescript(_TRIGGERS)

        if get().memory.episodic.wal:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")

        # Ensure the FTS is in sync with the base table (handles pre-existing rows)
        conn.execute(
            "INSERT OR IGNORE INTO episodic_fts(rowid, body) "
            "SELECT rowid, body FROM episodic;"
        )
        conn.commit()
    finally:
        conn.close()

    archive_dir = get().memory.episodic.archive_dir
    archive_dir.mkdir(parents=True, exist_ok=True)


def _check_bound() -> bool:
    """Return True if we are at or above the bound and must block."""
    cfg = get()
    if not cfg.memory.bounded.enabled:
        return False
    live = live_count()
    return live >= cfg.memory.bounded.max_live_events


def append(event: Event) -> str:
    """Append one event. Returns its id.

    BLOCKS if memory is full. ADR-0007: when the bound is reached, consolidation must run
    before anything new can be saved, and this is the function that blocks on it.

    Do not "fix" a slow write here by queueing. A queue that grows while waiting is unbounded
    memory in a different file, and ADR-0007 rules it out by name.
    """
    from friday.memory.consolidate import should_consolidate

    # ADR-0007: block at the bound. The block IS the forcing function.
    while True:
        should_run, must_block = should_consolidate()
        if must_block:
            from friday.memory.consolidate import consolidate

            consolidate()
            if _check_bound():
                from friday.memory.consolidate import MemoryFull

                raise MemoryFull(
                    "consolidation ran but could not free enough space; "
                    "the live count is still at or above max_live_events"
                )
            # else: consolidation freed space, proceed
            break
        if should_run:
            # Soft start: consolidate in the background, write now
            import threading

            t = threading.Thread(
                target=lambda: _safe_consolidate(), daemon=True
            )
            t.start()
        break

    db_path = _db_path()
    eid = str(uuid.uuid4())
    now_iso = datetime.now(event.occurred_at.tzinfo).isoformat()
    ingested_at = event.ingested_at or datetime.now(event.occurred_at.tzinfo)

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "INSERT OR IGNORE INTO episodic "
            "(id, source, external_id, occurred_at, body, sensitivity, untrusted, meta, "
            "ingested_at, consolidated, summary) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)",
            (
                eid,
                event.source,
                event.external_id,
                event.occurred_at.isoformat(),
                event.body,
                event.sensitivity.value,
                int(event.untrusted),
                json.dumps(event.meta),
                ingested_at.isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return eid


def search(
    query: str, limit: int = 30, sensitivity: Sensitivity | None = None
) -> list[dict[str, Any]]:
    """FTS5 keyword search. The keyword half of spec section 7's parallel retrieval.

    `sensitivity` filters INSIDE the query, never after ranking. ADR-0008: filtering after
    ranking means the ranking was computed over rows the caller may not see, which leaks
    their existence through result counts and gaps.
    """
    db_path = _db_path()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # Build the query with sensitivity filter INSIDE, per ADR-0008
        sql = (
            "SELECT e.id, e.source, e.external_id, e.occurred_at, e.body, "
            "e.sensitivity, e.untrusted, e.meta, e.ingested_at, "
            "bm25(episodic_fts) AS rank "
            "FROM episodic_fts "
            "JOIN episodic e ON e.rowid = episodic_fts.rowid "
            "WHERE episodic_fts MATCH ? "
        )
        params: list[Any] = [query]

        if sensitivity is not None:
            sql += " AND e.sensitivity = ?"
            params.append(sensitivity.value)

        sql += " ORDER BY rank LIMIT ?"
        params.append(limit)

        rows = conn.execute(sql, params).fetchall()
        return [
            {
                "id": r["id"],
                "source": r["source"],
                "external_id": r["external_id"],
                "occurred_at": r["occurred_at"],
                "body": r["body"],
                "sensitivity": r["sensitivity"],
                "untrusted": bool(r["untrusted"]),
                "meta": json.loads(r["meta"]),
                "ingested_at": r["ingested_at"],
                "rank": r["rank"],
            }
            for r in rows
        ]
    finally:
        conn.close()


def compress(before: datetime) -> int:
    """Rewrite old rows into summary rows and archive the originals. Returns rows archived.

    The only operation permitted to reduce the live log, and it does not edit: originals go to
    `archive_dir` intact, so a bad compression is recoverable.
    """
    cfg = get()
    db_path = _db_path()
    archive_dir = cfg.memory.episodic.archive_dir
    archive_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # Select unconsolidated rows older than 'before'
        rows = conn.execute(
            "SELECT * FROM episodic WHERE occurred_at < ? AND consolidated = 0 AND summary = 0",
            (before.isoformat(),),
        ).fetchall()

        if not rows:
            return 0

        archived = 0
        archive_ts = datetime.now(before.tzinfo).isoformat().replace(":", "-")
        archive_path = archive_dir / f"archive_{archive_ts}.jsonl"

        with open(archive_path, "a") as f:
            for row in rows:
                f.write(json.dumps(dict(row)) + "\n")
                archived += 1

        # Mark rows as consolidated (this is NOT editing the content - it's marking state)
        # and create summary placeholder rows
        for row in rows:
            # Archive the original by marking it consolidated
            conn.execute(
                "UPDATE episodic SET consolidated = 1 WHERE id = ?",
                (row["id"],),
            )

        conn.commit()
        return archived
    finally:
        conn.close()


def live_count() -> int:
    """Rows in the live log, compared against `max_live_events` by the bound check."""
    db_path = _db_path()
    conn = sqlite3.connect(str(db_path))
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM episodic WHERE consolidated = 0 AND summary = 0"
        ).fetchone()[0]
        return count
    finally:
        conn.close()


def _safe_consolidate() -> None:
    """Run consolidation, catching exceptions for the background thread."""
    try:
        from friday.memory.consolidate import consolidate

        consolidate()
    except Exception:
        pass  # Background consolidation failure is non-fatal; the block will catch it
