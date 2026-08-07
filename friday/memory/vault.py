"""Tier 3: the vault. Markdown, git-backed, Obsidian-compatible.

`daily/ projects/ people/ ideas/`. Written by the consolidation loop, editable by you - and
that second half is load-bearing, because correcting a wrong note by hand is the documented
fix when a digest is wrong.

ADR-0017: every generated note carries YAML frontmatter (source, created, updated, tags, plus
provenance) and links use [[wikilink]] form. Nothing Obsidian-specific is ever REQUIRED to
read the vault - it stays a directory of plain markdown that cat and grep fully understand.
The frontmatter earns its place independently: it is the provenance spec section 7 requires,
in a form the indexer parses without heuristics.

One git commit per consolidation run, never per note. Per-note commits break the revert.

Implemented in W3.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping


def write_note(directory: str, slug: str, body: str, frontmatter: Mapping[str, Any]) -> Path:
    """Write a note with frontmatter. Does not commit.

    Raises:
        ValueError: `directory` is not one of the four in config/memory.yaml, or the
            frontmatter is missing a provenance field.
        NotImplementedError: W3.
    """
    raise NotImplementedError("friday.memory.vault.write_note is implemented in W3")


def commit(message: str) -> str:
    """Commit every pending vault change as ONE commit. Returns the sha.

    One per run. The supervisor reverts to the pre-run commit after a budget kill
    (`revert_vault_on_kill`), and per-note commits leave it nothing single to revert to.

    Raises:
        NotImplementedError: W3.
    """
    raise NotImplementedError("friday.memory.vault.commit is implemented in W3")


def revert_to(sha: str) -> None:
    """Revert the vault to a commit. Used by the supervisor after a kill.

    Raises:
        NotImplementedError: W3.
    """
    raise NotImplementedError("friday.memory.vault.revert_to is implemented in W3")


def note_count() -> int:
    """Notes in the vault, against `max_vault_notes`.

    Raises:
        NotImplementedError: W3.
    """
    raise NotImplementedError("friday.memory.vault.note_count is implemented in W3")


def profile() -> str:
    """Read tier 1, vault/profile.md, injected into every prompt.

    Never generated and never written by this module. Spec section 11: you write it by hand,
    and it is the seed everything else grows from.

    Raises:
        FileNotFoundError: missing, and `profile.required` is true.
        NotImplementedError: W3.
    """
    raise NotImplementedError("friday.memory.vault.profile is implemented in W3")
