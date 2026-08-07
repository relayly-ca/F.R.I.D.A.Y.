"""The checker. ADR-0013: the writer is never the checker.

W3 documents the failure this exists for - "the digest is confidently wrong" - and why a
better prompt does not fix it: a model grading its own output inflates its confidence,
reliably, and the consolidator has just spent its entire context deciding the note was right.

So a DIFFERENT agent asks one narrow question: does every claim in this note appear in the
rows it was built from. Quality is bounded by that schema rather than by model size, which is
the same argument config/agents.yaml already makes for the consolidator running on `fast`.

A note that fails goes to the inbox rather than to disk. It is not silently dropped - a
consolidation that quietly discards its output is indistinguishable from one that had nothing
to say.

Implemented in W3.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    unsupported: tuple[str, ...] = ()
    reason: str = ""


def check_note(note: str, sources: list[str], writer_agent: str) -> CheckResult:
    """Check a generated note against the rows it was built from.

    Args:
        writer_agent: The agent that produced the note. Passed so this function can REFUSE to
            check using the same agent. That refusal is the whole point of the module;
            leaving it to a config value makes it a setting rather than an invariant.

    Raises:
        ValueError: the configured checker agent equals `writer_agent`.
        NotImplementedError: W3.
    """
    raise NotImplementedError("friday.memory.check.check_note is implemented in W3")
