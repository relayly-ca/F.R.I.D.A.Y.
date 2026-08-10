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

import logging
import re
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

from friday.config import get
from friday.models import Chunk, Event, Sensitivity, wrap_untrusted

logger = logging.getLogger(__name__)

# Approximate tokens per word: ~0.75 words per token, or ~1.33 tokens per word
_WORDS_PER_TOKEN = 0.75


def _token_count(text: str) -> int:
    """Rough token estimate. Not exact, but consistent for chunking decisions."""
    return max(1, int(len(text.split()) / _WORDS_PER_TOKEN))


def _chunk_tokens() -> int:
    return get().memory.index.chunk_tokens


def _chunk_overlap() -> int:
    return get().memory.index.chunk_overlap_tokens


def _split_by_structure(text: str) -> list[str]:
    """Split text on structural boundaries first.

    Structure boundaries, in order of preference:
    - Paragraph breaks (double newline)
    - Section headers (lines starting with # or ##)
    - Single newlines for messages

    Each structural unit becomes a candidate chunk.
    """
    # Try paragraph splits first
    paragraphs = re.split(r"\n\s*\n", text)
    if len(paragraphs) > 1:
        return [p.strip() for p in paragraphs if p.strip()]

    # Try section headers
    sections = re.split(r"\n(?=#{1,3}\s)", text)
    if len(sections) > 1:
        return [s.strip() for s in sections if s.strip()]

    # Try single newlines (for messages, logs)
    lines = text.split("\n")
    if len(lines) > 1:
        return [l.strip() for l in lines if l.strip()]

    return [text]


def _token_window_chunks(text: str, chunk_size: int, overlap: int) -> list[str]:
    """Split text into overlapping token windows.

    Only used when a structural unit exceeds the chunk budget.
    """
    words = text.split()
    if not words:
        return []

    words_per_chunk = int(chunk_size * _WORDS_PER_TOKEN)
    overlap_words = int(overlap * _WORDS_PER_TOKEN)

    if words_per_chunk <= 0:
        words_per_chunk = 1
    if overlap_words >= words_per_chunk:
        overlap_words = words_per_chunk // 2

    chunks = []
    start = 0
    while start < len(words):
        end = min(start + words_per_chunk, len(words))
        chunk_text = " ".join(words[start:end])
        chunks.append(chunk_text)
        if end >= len(words):
            break
        start = end - overlap_words
        if start <= 0:
            start = end  # avoid infinite loop

    return chunks


def chunk_event(event: Event) -> list[Chunk]:
    """Split one event into retrievable chunks, carrying provenance onto each.
    """
    chunk_size = _chunk_tokens()
    overlap = _chunk_overlap()

    # Start with structure-first splitting
    units = _split_by_structure(event.body)

    # For each unit, check if it fits in the budget; if not, window it
    all_chunks: list[str] = []
    for unit in units:
        if _token_count(unit) <= chunk_size:
            all_chunks.append(unit)
        else:
            all_chunks.extend(_token_window_chunks(unit, chunk_size, overlap))

    if not all_chunks:
        all_chunks = [event.body]

    # Build Chunk objects with provenance
    chunks: list[Chunk] = []
    for ordinal, text in enumerate(all_chunks):
        chunk = Chunk(
            chunk_id=str(uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{event.source}:{event.external_id}:{ordinal}",
            )),
            source=event.source,
            external_id=event.external_id,
            occurred_at=event.occurred_at,
            sensitivity=event.sensitivity,
            text=text,
            ordinal=ordinal,
            meta=event.meta,
        )
        chunks.append(chunk)

    return chunks


def from_sources(since: datetime | None = None, dry_run: bool = False) -> int:
    """Move landing-zone rows into the episodic log, chunk, and index. Returns events moved.

    Goes through episodic.append, so it is subject to the bound and can block. That is
    correct: a backfill is exactly when the bound matters, and a backfill path that bypasses
    it is an unbounded write path wearing a different name (ADR-0007).
    """
    from friday.memory import episodic, index

    cfg = get()
    sources_db = cfg.sources.defaults.sink

    if not Path(sources_db).exists():
        logger.warning("sources.db not found at %s; nothing to ingest", sources_db)
        return 0

    if since is None:
        since = datetime(1970, 1, 1, tzinfo=since.tzinfo if since else None)

    conn = sqlite3.connect(str(sources_db))
    conn.row_factory = sqlite3.Row
    try:
        # Find rows in the landing zone that haven't been moved yet
        # The landing zone uses the same Event schema
        rows = conn.execute(
            "SELECT * FROM events WHERE occurred_at >= ? ORDER BY occurred_at ASC",
            (since.isoformat() if since else "1970-01-01T00:00:00",),
        ).fetchall()
    except sqlite3.OperationalError:
        # Table doesn't exist yet
        logger.warning("events table not found in sources.db; nothing to ingest")
        return 0
    finally:
        conn.close()

    if not rows:
        return 0

    events_moved = 0

    for row in rows:
        try:
            event = Event(
                source=row["source"],
                external_id=row["external_id"],
                occurred_at=datetime.fromisoformat(row["occurred_at"]),
                body=row["body"],
                sensitivity=Sensitivity(row["sensitivity"]),
                untrusted=bool(row.get("untrusted", True)),
                meta=row["meta"] if isinstance(row["meta"], dict) else {},
                ingested_at=datetime.fromisoformat(row["ingested_at"])
                if row["ingested_at"]
                else None,
            )
        except Exception as e:
            logger.warning("skipping malformed row: %s", e)
            continue

        if dry_run:
            events_moved += 1
            continue

        # Append to episodic log (subject to bound - can block)
        episodic.append(event)

        # Chunk and index
        chunks = chunk_event(event)
        try:
            index.upsert(chunks)
        except Exception as e:
            logger.warning("index upsert failed for %s:%s: %s", event.source, event.external_id, e)

        events_moved += 1

    return events_moved
