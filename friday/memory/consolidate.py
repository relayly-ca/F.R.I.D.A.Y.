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


class MemoryFull(Exception):
    """Raised when a write cannot proceed and consolidation could not free space.

    NOT raised in the normal blocking case - normally the write waits and then succeeds. This
    means consolidation ran and did not free enough, which is a real condition needing a
    human, and not a reason to raise the bound.
    """


def should_consolidate() -> tuple[bool, bool]:
    """Returns (should_run, must_block) against the current bound.

    `must_block` is True at the bound. That is the forcing function; a caller that ignores it
    has removed the mechanism ADR-0007 exists for.

    Raises:
        NotImplementedError: W3.
    """
    raise NotImplementedError("friday.memory.consolidate.should_consolidate is implemented in W3")


def consolidate(dry_run: bool = False) -> int:
    """Run one consolidation pass. Returns notes written.

    Reads unconsolidated episodic rows, extracts to a schema, writes vault notes, marks rows
    consolidated. ONE git commit per run (`commit_per_run`), never per note - per-note commits
    break the revert the supervisor depends on in W5.

    Every note goes through friday.memory.check before it lands. ADR-0013: the writer is
    never the checker.

    Raises:
        MemoryFull: consolidation could not free enough space.
        NotImplementedError: W3.
    """
    raise NotImplementedError("friday.memory.consolidate.consolidate is implemented in W3")
