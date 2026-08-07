"""sources.db -> the episodic log, chunked and indexed.

sources.db is a landing zone with 30-day retention; the episodic log is the durable record.
Nothing is pruned from the landing zone until it is BOTH consolidated and indexed, whatever
its age (config/sources.yaml `retention`).

Chunking is 512 tokens with 64 overlap, and it chunks on STRUCTURE first - a calendar event,
a message, a note section - falling back to a token window only when a unit exceeds the
budget. A message split down the middle retrieves as two halves that each make less sense
than the whole, and bad chunk boundaries cause more eval failures than bad ranking does.

Implemented in W3.
"""

from __future__ import annotations

from datetime import datetime

from friday.models import Chunk, Event


def chunk_event(event: Event) -> list[Chunk]:
    """Split one event into retrievable chunks, carrying provenance onto each.

    Raises:
        NotImplementedError: W3.
    """
    raise NotImplementedError("friday.memory.ingest.chunk_event is implemented in W3")


def from_sources(since: datetime | None = None, dry_run: bool = False) -> int:
    """Move landing-zone rows into the episodic log, chunk, and index. Returns events moved.

    Goes through episodic.append, so it is subject to the bound and can block. That is
    correct: a backfill is exactly when the bound matters, and a backfill path that bypasses
    it is an unbounded write path wearing a different name (ADR-0007).

    Raises:
        NotImplementedError: W3.
    """
    raise NotImplementedError("friday.memory.ingest.from_sources is implemented in W3")
