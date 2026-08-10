"""The ingest base: sources.db, the Source protocol, the untrusted wrap.

Spec section 9 and ADR-0006: everything ingested is untrusted input. The untrusted
wrap is applied HERE, in one place, so no source can forget it. The real boundary
is that ingested text reaches a model only through the scorer, which has tools: [].

The Event model lives in friday.models. This module owns:
  - the Source protocol: poll() -> Iterable[Event], nothing else
  - idempotent upsert into sources.db, keyed on (source, external_id)
  - the untrusted wrap applied on write, in one place
  - max_events_per_poll from config/sources.yaml

A re-poll after a crash upserts rather than duplicating, which is what makes every
ingest module safely re-runnable.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from friday.config import get
from friday.models import Event, wrap_untrusted

try:
    import structlog
    log = structlog.get_logger()
except ImportError:  # pragma: no cover
    import logging
    log = logging.getLogger("friday.ingest")


# --- The Source protocol -----------------------------------------------------

class Source(Protocol):
    """Every source implements this. poll() yields Events; nothing else."""

    def poll(self) -> Iterable[Event]: ...


# --- sources.db --------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    source      TEXT    NOT NULL,
    external_id TEXT    NOT NULL,
    occurred_at TEXT    NOT NULL,
    body        TEXT    NOT NULL,
    sensitivity TEXT    NOT NULL,
    untrusted   INTEGER NOT NULL DEFAULT 1,
    meta        TEXT    NOT NULL DEFAULT '{}',
    ingested_at TEXT    NOT NULL,
    consolidated INTEGER NOT NULL DEFAULT 0,
    indexed     INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (source, external_id)
);
CREATE INDEX IF NOT EXISTS idx_events_occurred ON events (occurred_at);
CREATE INDEX IF NOT EXISTS idx_events_source ON events (source);
CREATE INDEX IF NOT EXISTS idx_events_unconsolidated ON events (consolidated) WHERE consolidated = 0;
"""


def _db_path() -> Path:
    """The configured sources.db path. Falls back to a local dev path."""
    try:
        cfg = get()
        return Path(cfg.sources.defaults.sink)
    except Exception:
        return Path("db/sources.db")


def init_db(path: Path | None = None) -> None:
    """Create the sources.db schema. Idempotent."""
    db = path or _db_path()
    db.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(db)) as c:
        c.executescript(SCHEMA)
    log.info("ingest.init_db", db=str(db))


def upsert(event: Event) -> bool:
    """Write one event to sources.db. Idempotent on (source, external_id).

    The untrusted wrap is applied HERE, not by the source. A source that believes
    its input is trustworthy is a source that has not been attacked yet.

    Returns True if a new row was inserted, False if it was an update of an existing row.
    """
    db = _db_path()
    wrapped = wrap_untrusted(
        event.body,
        source=event.source,
        external_id=event.external_id,
        occurred_at=event.occurred_at,
    )
    now = (event.ingested_at or datetime.now(UTC)).isoformat()
    meta_json = json.dumps(event.meta, default=str)

    with sqlite3.connect(str(db)) as c:
        cur = c.execute(
            """INSERT INTO events (source, external_id, occurred_at, body, sensitivity,
                                  untrusted, meta, ingested_at, consolidated, indexed)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?, 0, 0)
               ON CONFLICT (source, external_id) DO UPDATE SET
                   body = excluded.body,
                   occurred_at = excluded.occurred_at,
                   sensitivity = excluded.sensitivity,
                   meta = excluded.meta
               RETURNING (changes() = 1)""",
            (event.source, event.external_id, event.occurred_at.isoformat(),
             wrapped, event.sensitivity.value, meta_json, now),
        )
        row = cur.fetchone()
        return row is not None and row[0] == 1


def unprocessed(limit: int = 100) -> list[dict[str, Any]]:
    """Rows that have landed but not been consolidated and indexed yet."""
    db = _db_path()
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            """SELECT source, external_id, occurred_at, body, sensitivity, meta
               FROM events WHERE consolidated = 0
               ORDER BY occurred_at ASC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def mark_consolidated(source: str, external_id: str) -> None:
    db = _db_path()
    with sqlite3.connect(str(db)) as c:
        c.execute(
            "UPDATE events SET consolidated = 1 WHERE source = ? AND external_id = ?",
            (source, external_id),
        )


def mark_indexed(source: str, external_id: str) -> None:
    db = _db_path()
    with sqlite3.connect(str(db)) as c:
        c.execute(
            "UPDATE events SET indexed = 1 WHERE source = ? AND external_id = ?",
            (source, external_id),
        )


def prune_older_than(days: int) -> int:
    """Prune rows older than `days` that are both consolidated and indexed."""
    db = _db_path()
    with sqlite3.connect(str(db)) as c:
        cur = c.execute(
            """DELETE FROM events
               WHERE consolidated = 1 AND indexed = 1
               AND occurred_at < datetime('now', ?)""",
            (f"-{days} days",),
        )
        return cur.rowcount


def poll_all() -> dict[str, int]:
    """Poll every enabled source and upsert. Returns per-source counts."""
    try:
        cfg = get()
    except Exception as exc:
        log.error("ingest.poll_all.config", error=str(exc))
        return {}

    counts: dict[str, int] = {}
    max_per_poll = cfg.sources.defaults.max_events_per_poll

    for name, spec in cfg.sources.sources.items():
        if not spec.enabled:
            continue
        try:
            # Import the source module dynamically
            module = _import_source(spec.module)
            source = module.create_source(name, spec)  # type: ignore[attr-defined]
            count = 0
            for event in source.poll():
                if count >= max_per_poll:
                    log.warning("ingest.poll_all.capped", source=name, cap=max_per_poll)
                    break
                upsert(event)
                count += 1
            counts[name] = count
            log.info("ingest.poll_all.done", source=name, events=count)
        except Exception as exc:
            log.error("ingest.poll_all.error", source=name, error=str(exc))
            counts[name] = -1

    return counts


def _import_source(module_path: str) -> Any:
    """Import a source module from its dotted path."""
    import importlib
    parts = module_path.rsplit(".", 1)
    if len(parts) == 2:
        mod = importlib.import_module(parts[0])
        return getattr(mod, parts[1]) if hasattr(mod, parts[1]) else mod
    return importlib.import_module(module_path)


# --- CLI entry: python -m friday.ingest.base ---------------------------------

def main() -> int:
    import sys

    if "--init-db" in sys.argv:
        init_db()
        print(f"sources.db initialised at {_db_path()}")
        return 0

    if "--once" in sys.argv:
        counts = poll_all()
        for name, count in sorted(counts.items()):
            status = f"{count} events" if count >= 0 else "FAILED"
            print(f"  {name:<20} {status}")
        return 0 if all(v >= 0 for v in counts.values()) else 1

    print("Usage: python -m friday.ingest.base [--init-db | --once]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
