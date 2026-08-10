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

import re
import subprocess
from pathlib import Path
from typing import Any, Mapping

import yaml

from friday.config import get


def _vault_path() -> Path:
    return get().memory.vault.path


def _validate_directory(directory: str) -> str:
    """Validate and return the directory, raising on unknown dirs."""
    dirs = get().memory.vault.dirs
    if directory not in dirs:
        raise ValueError(
            f"directory {directory!r} is not one of the four configured vault dirs "
            f"{list(dirs)}. The vault is daily/ projects/ people/ ideas/."
        )
    return directory


_REQUIRED_FRONTMATTER = {"source", "created"}


def write_note(
    directory: str, slug: str, body: str, frontmatter: Mapping[str, Any]
) -> Path:
    """Write a note with frontmatter. Does not commit.

    Raises:
        ValueError: `directory` is not one of the four in config/memory.yaml, or the
            frontmatter is missing a provenance field.
    """
    _validate_directory(directory)

    missing = _REQUIRED_FRONTMATTER - set(frontmatter.keys())
    if missing:
        raise ValueError(
            f"frontmatter is missing required provenance fields: {sorted(missing)}. "
            f"Spec section 7 requires provenance on every note."
        )

    vault = _vault_path()
    note_dir = vault / directory
    note_dir.mkdir(parents=True, exist_ok=True)

    # Convert [[wikilinks]] are left as-is; they are Obsidian-compatible already
    # Build frontmatter YAML
    fm = dict(frontmatter)
    fm_text = yaml.dump(fm, default_flow_style=False, sort_keys=False)

    content = f"---\n{fm_text}---\n\n{body}\n"
    note_path = note_dir / f"{slug}.md"
    note_path.write_text(content)

    return note_path


def commit(message: str) -> str:
    """Commit every pending vault change as ONE commit. Returns the sha.

    One per run. The supervisor reverts to the pre-run commit after a budget kill
    (`revert_vault_on_kill`), and per-note commits leave it nothing single to revert to.
    """
    vault = _vault_path()

    def _git(*args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(vault), *args],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr}")
        return result.stdout.strip()

    _git("add", "-A")
    # Check if there's anything to commit
    status = _git("status", "--porcelain")
    if not status:
        # Nothing to commit; return current HEAD
        return _git("rev-parse", "HEAD")

    sha = _git("commit", "-m", message)
    # Extract the sha from the commit output
    # git commit output: "[main abc1234] message"
    match = re.search(r"\[.*?\s([0-9a-f]{7,})\]", sha)
    if match:
        return match.group(1)
    # Fallback: use rev-parse
    return _git("rev-parse", "HEAD")


def revert_to(sha: str) -> None:
    """Revert the vault to a commit. Used by the supervisor after a kill."""
    vault = _vault_path()
    subprocess.run(
        ["git", "-C", str(vault), "reset", "--hard", sha],
        capture_output=True,
        text=True,
        check=True,
    )


def note_count() -> int:
    """Notes in the vault, against `max_vault_notes`."""
    vault = _vault_path()
    if not vault.exists():
        return 0

    count = 0
    for d in get().memory.vault.dirs:
        dir_path = vault / d
        if dir_path.exists():
            count += sum(1 for f in dir_path.glob("*.md") if f.is_file())

    # Also count profile.md if it exists (but it's hand-written, not a generated note)
    # Per the spec, note_count is against max_vault_notes which is about generated notes
    return count


def profile() -> str:
    """Read tier 1, vault/profile.md, injected into every prompt.

    Never generated and never written by this module. Spec section 11: you write it by hand,
    and it is the seed everything else grows from.

    Raises:
        FileNotFoundError: missing, and `profile.required` is true.
    """
    cfg = get()
    profile_path = cfg.memory.profile.path

    if not profile_path.exists():
        if cfg.memory.profile.required:
            raise FileNotFoundError(
                f"profile.md not found at {profile_path}. Spec section 11: profile.md is "
                f"hand-written by you and is the seed everything else grows from. Without it "
                f"she does not know who you are."
            )
        return ""

    return profile_path.read_text()
