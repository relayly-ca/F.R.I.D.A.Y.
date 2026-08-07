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

from datetime import datetime
from pathlib import Path
from typing import Any

from friday.models import Event, Sensitivity


class AppendOnlyViolation(Exception):
    """Raised on any attempt to modify or remove an existing episodic row.

    Exists so the invariant is testable. Spec section 7 says never edited, and a property
    nobody can write a test against is a hope.
    """


def init(path: Path | None = None) -> None:
    """Create the schema, the FTS5 external-content table and its triggers. Idempotent.

    Sets journal_mode=WAL. Ingestion writes while retrieval reads, and without WAL the reader
    blocks the writer at exactly the moments both matter.

    Raises:
        NotImplementedError: W3.
    """
    raise NotImplementedError("friday.memory.episodic.init is implemented in W3")


def append(event: Event) -> str:
    """Append one event. Returns its id.

    BLOCKS if memory is full. ADR-0007: when the bound is reached, consolidation must run
    before anything new can be saved, and this is the function that blocks on it.

    Do not "fix" a slow write here by queueing. A queue that grows while waiting is unbounded
    memory in a different file, and ADR-0007 rules it out by name.

    Raises:
        NotImplementedError: W3.
    """
    raise NotImplementedError(
        "friday.memory.episodic.append is implemented in W3. It BLOCKS at the bound "
        "(ADR-0007); that block is the forcing function, not a defect to work around."
    )


def search(query: str, limit: int = 30, sensitivity: Sensitivity | None = None) -> list[dict[str, Any]]:
    """FTS5 keyword search. The keyword half of spec section 7's parallel retrieval.

    `sensitivity` filters INSIDE the query, never after ranking. ADR-0008: filtering after
    ranking means the ranking was computed over rows the caller may not see, which leaks
    their existence through result counts and gaps.

    Raises:
        NotImplementedError: W3.
    """
    raise NotImplementedError("friday.memory.episodic.search is implemented in W3")


def compress(before: datetime) -> int:
    """Rewrite old rows into summary rows and archive the originals. Returns rows archived.

    The only operation permitted to reduce the live log, and it does not edit: originals go to
    `archive_dir` intact, so a bad compression is recoverable.

    Raises:
        NotImplementedError: W3.
    """
    raise NotImplementedError("friday.memory.episodic.compress is implemented in W3")


def live_count() -> int:
    """Rows in the live log, compared against `max_live_events` by the bound check.

    Raises:
        NotImplementedError: W3.
    """
    raise NotImplementedError("friday.memory.episodic.live_count is implemented in W3")
