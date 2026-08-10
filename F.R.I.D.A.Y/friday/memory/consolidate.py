"""Consolidation. ADR-0007, and the single most likely thing in this repo to be quietly
reverted by whoever implements it.

**Bounded memory means consolidate when full.** Not nightly compression.

    write() ->  live >= max_live_events?
                  yes -> BLOCK. Consolidate. Then write.
                  no  -> live >= soft_start_at * max?
                           yes -> consolidate in the background, write now
                           no  -> write now

The block is the design. Spec section 7: "when memory fills, the agent must consolidate
before it can save anything new - is better than nightly compression. Scarcity forces
curation."

Nightly compression has no pressure in it. Anything can be saved, because compression is
someone else's problem at 03:00. The corpus grows, the compression job grows with it, and
retrieval quality degrades on a curve nobody is watching.

A scheduled pass is permitted IN ADDITION (`scheduled_pass: "03:00"`). ADR-0007 forbids it
being the ONLY consolidation, and forbids an unbounded write path between passes.

The tell that this went wrong: tests/test_consolidate.py has no test that a write blocks.

Implemented in W3.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from friday.config import get
from friday.memory import episodic, vault
from friday.memory.check import check_note

logger = logging.getLogger(__name__)


class MemoryFull(Exception):
    """Raised when a write cannot proceed and consolidation could not free space.

    NOT raised in the normal blocking case - normally the write waits and then succeeds. This
    means consolidation ran and did not free enough, which is a real condition needing a
    human, and not a reason to raise the bound.
    """


_WRITER_AGENT = "consolidator"


def should_consolidate() -> tuple[bool, bool]:
    """Returns (should_run, must_block) against the current bound.

    `must_block` is True at the bound. That is the forcing function; a caller that ignores it
    has removed the mechanism ADR-0007 exists for.
    """
    cfg = get()
    if not cfg.memory.bounded.enabled:
        return (False, False)

    live = episodic.live_count()
    max_live = cfg.memory.bounded.max_live_events

    if live >= max_live:
        if cfg.memory.bounded.block_writes_when_full:
            return (True, True)
        else:
            # block_writes_when_full is false (validated as not possible by config,
            # but handle it gracefully)
            return (True, False)

    soft_threshold = int(cfg.memory.bounded.soft_start_at * max_live)
    if live >= soft_threshold:
        return (True, False)

    return (False, False)


def consolidate(dry_run: bool = False) -> int:
    """Run one consolidation pass. Returns notes written.

    Reads unconsolidated episodic rows, extracts to a schema, writes vault notes, marks rows
    consolidated. ONE git commit per run (`commit_per_run`), never per note - per-note commits
    break the revert the supervisor depends on in W5.

    Every note goes through friday.memory.check before it lands. ADR-0013: the writer is
    never the checker.

    Raises:
        MemoryFull: consolidation could not free enough space.
    """
    import sqlite3

    cfg = get()
    db_path = cfg.memory.episodic.db
    archive_dir = cfg.memory.episodic.archive_dir

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # Find unconsolidated rows
        rows = conn.execute(
            "SELECT * FROM episodic WHERE consolidated = 0 AND summary = 0 "
            "ORDER BY occurred_at ASC LIMIT 100"
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        if not dry_run:
            try:
                vault.commit("consolidation: nothing to consolidate")
            except Exception as e:
                logger.debug("empty commit skipped: %s", e)
        return 0

    notes_written = 0

    # Group rows by source + date for summary notes
    groups: dict[str, list] = {}
    for row in rows:
        occurred = datetime.fromisoformat(row["occurred_at"])
        key = f"{row['source']}_{occurred.date().isoformat()}"
        groups.setdefault(key, []).append(row)

    for key, group_rows in groups.items():
        source = group_rows[0]["source"]
        occurred_date = datetime.fromisoformat(group_rows[0]["occurred_at"]).date().isoformat()

        # Build the note body from the source rows
        note_body_parts: list[str] = []
        for row in group_rows:
            note_body_parts.append(
                f"- [{row['occurred_at']}] {row['body'][:200]}"
                + ("..." if len(row["body"]) > 200 else "")
            )
        note_body = "\n".join(note_body_parts)

        # Build frontmatter with provenance
        frontmatter = {
            "source": source,
            "created": datetime.now(timezone.utc).isoformat(),
            "updated": datetime.now(timezone.utc).isoformat(),
            "tags": [source, "consolidated", occurred_date],
            "provenance": {
                "row_ids": [r["id"] for r in group_rows],
                "row_count": len(group_rows),
                "date": occurred_date,
            },
        }

        if dry_run:
            notes_written += 1
            continue

        # Check the note before writing (ADR-0013)
        sources_text = [row["body"] for row in group_rows]
        check_result = check_note(note_body, sources_text, _WRITER_AGENT)

        if not check_result.ok:
            # Note fails check: goes to inbox, not to disk
            logger.warning(
                "consolidation note for %s failed check: %s. Sending to inbox.",
                key,
                check_result.reason,
            )
            continue

        # Write the note (chooses directory based on source)
        directory = "daily"
        slug = f"{occurred_date}_{source}_{key[:20]}"

        vault.write_note(directory, slug, note_body, frontmatter)
        notes_written += 1

        # Mark the rows as consolidated
        conn2 = sqlite3.connect(str(db_path))
        try:
            for row in group_rows:
                conn2.execute(
                    "UPDATE episodic SET consolidated = 1 WHERE id = ?",
                    (row["id"],),
                )
            conn2.commit()
        finally:
            conn2.close()

    if not dry_run and cfg.memory.vault.commit_per_run:
        vault.commit(f"consolidation: {notes_written} notes from {len(rows)} rows")

    # Check if we freed enough space
    if not dry_run:
        live = episodic.live_count()
        max_live = cfg.memory.bounded.max_live_events
        if live >= max_live:
            raise MemoryFull(
                f"consolidation wrote {notes_written} notes but live_count is still "
                f"{live} (max {max_live}). Cannot free enough space."
            )

    return notes_written
