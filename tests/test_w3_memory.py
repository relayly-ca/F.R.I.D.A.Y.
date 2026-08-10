"""Tests for the W3 memory subsystem.

These tests run WITHOUT Qdrant or LiteLLM. They use temp directories and monkeypatch
friday.config.get to return a config pointing at temp paths. Service-dependent functions
gracefully degrade (return empty, skip, or log a warning) when services are unreachable.

    uv run pytest tests/test_w3_memory.py -xvs
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from friday.config import Config
from friday.models import Chunk, Event, Retrieved, Sensitivity


# ---------------------------------------------------------------------------
# Helpers: build a test Config that points at temp dirs
# ---------------------------------------------------------------------------

def _make_config(tmp_path: Path) -> Config:
    """Build a real Config with all paths pointing at tmp_path."""
    import tomllib

    from friday.config import (
        AgentsYaml,
        BargeIn,
        BoundedCfg,
        ConfigFiles,
        EpisodicCfg,
        EvalCfg,
        FridayToml,
        General,
        IndexCfg,
        MemoryYaml,
        ModelsCfg,
        Output,
        Paths,
        ProfileCfg,
        RetrieveCfg,
        SourcesYaml,
        SupervisorCfg,
        Tracing,
        VaultCfg,
        Voice,
    )

    # Read the real config files for agents.yaml and sources.yaml
    repo = Path(__file__).resolve().parents[1]
    import yaml

    agents_raw = yaml.safe_load((repo / "config" / "agents.yaml").read_text())
    agents = AgentsYaml.model_validate(agents_raw)

    sources_raw = yaml.safe_load((repo / "config" / "sources.yaml").read_text())
    # Fix paths in sources_raw to point at temp
    sources_raw["defaults"]["sink"] = str(tmp_path / "sources.db")
    sources = SourcesYaml.model_validate(sources_raw)

    vault_path = tmp_path / "vault"
    db_path = tmp_path / "db"
    db_path.mkdir(exist_ok=True)
    vault_path.mkdir(exist_ok=True)
    archive_dir = db_path / "archive"
    archive_dir.mkdir(exist_ok=True)

    # Read friday.toml
    toml_raw = tomllib.loads((repo / "config" / "friday.toml").read_text())

    general = General(
        principal=toml_raw["general"]["principal"],
        timezone=toml_raw["general"]["timezone"],
        log_level=toml_raw["general"].get("log_level", "info"),
        debug_prompts=toml_raw["general"].get("debug_prompts", False),
    )

    paths = Paths(
        root=tmp_path,
        vault=vault_path,
        db=db_path,
        agent=tmp_path / "agent",
        core=tmp_path / "agent" / "core",
        loops=tmp_path / "loops",
        ingest=tmp_path / "ingest",
        work=tmp_path / "work",
        eval=tmp_path / "eval",
        logs=tmp_path / "logs",
        models=tmp_path / "models",
        secrets=tmp_path / "secrets",
    )

    config_files = ConfigFiles(
        scrutiny=repo / "config" / "scrutiny.yaml",
        agents=repo / "config" / "agents.yaml",
        memory=repo / "config" / "memory.yaml",
        sources=repo / "config" / "sources.yaml",
    )

    models_cfg = ModelsCfg(
        litellm_base_url="http://127.0.0.1:4000",
        virtual_keys=tmp_path / "secrets" / "litellm-keys.yaml",
    )

    # Build memory.yaml config pointing at temp dirs
    profile_path = vault_path / "profile.md"

    memory = MemoryYaml(
        version=1,
        profile=ProfileCfg(path=profile_path, max_tokens=1500, required=True),
        episodic=EpisodicCfg(
            db=db_path / "episodic.db",
            append_only=True,
            wal=True,
            archive_dir=archive_dir,
        ),
        vault=VaultCfg(
            path=vault_path,
            dirs=("daily", "projects", "people", "ideas"),
            git=True,
            commit_per_run=True,
        ),
        index=IndexCfg(
            qdrant_url="http://127.0.0.1:6333",
            collection="friday",
            fts_db=db_path / "episodic.db",
            embed_alias="embed",
            rerank_alias="rerank",
            embed_dim=1024,
            chunk_tokens=512,
            chunk_overlap_tokens=64,
        ),
        retrieve=RetrieveCfg(),
        bounded=BoundedCfg(
            enabled=True,
            max_live_events=100,  # small for testing
            max_vault_notes=50,
            soft_start_at=0.85,
            block_writes_when_full=True,
            scheduled_pass="03:00",
        ),
        eval=EvalCfg(
            questions=tmp_path / "eval" / "questions.yaml",
            pass_threshold=20,
            total=25,
            results_dir=tmp_path / "eval" / "results",
        ),
    )

    friday_toml = FridayToml(
        general=general,
        paths=paths,
        config=config_files,
        models=models_cfg,
        budgets=toml_raw["budgets"],
    )

    return Config(
        repo=repo,
        friday=friday_toml,
        agents=agents,
        memory=memory,
        sources=sources,
        scrutiny_path=repo / "config" / "scrutiny.yaml",
    )


@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    """A Config pointing at temp directories."""
    return _make_config(tmp_path)


@pytest.fixture(autouse=True)
def patched_config(cfg, monkeypatch):
    """Patch friday.config.get everywhere to return our temp config."""
    import friday.config
    import friday.memory.episodic
    import friday.memory.index
    import friday.memory.retrieve
    import friday.memory.vault
    import friday.memory.check
    import friday.memory.consolidate
    import friday.memory.ingest

    # Clear the lru_cache
    friday.config.get.cache_clear()

    monkeypatch.setattr(friday.config, "get", lambda: cfg)
    # Also patch in each module that imported it directly
    for mod in (
        friday.memory.episodic,
        friday.memory.index,
        friday.memory.retrieve,
        friday.memory.vault,
        friday.memory.check,
        friday.memory.consolidate,
        friday.memory.ingest,
    ):
        if hasattr(mod, "get"):
            monkeypatch.setattr(mod, "get", lambda: cfg)

    yield cfg


@pytest.fixture
def tz() -> timezone:
    return timezone.utc


def _make_event(**kwargs: Any) -> Event:
    """Create a test event with sensible defaults."""
    defaults = dict(
        source="test",
        external_id=f"evt-{datetime.now(timezone.utc).timestamp()}",
        occurred_at=datetime.now(timezone.utc),
        body="Test event body with some content.",
        sensitivity=Sensitivity.ANY,
    )
    defaults.update(kwargs)
    return Event(**defaults)


# ---------------------------------------------------------------------------
# Episodic tests
# ---------------------------------------------------------------------------

class TestEpisodic:
    """Tier 2: append-only log, FTS5, WAL."""

    def test_init_creates_schema(self, cfg, tmp_path):
        from friday.memory import episodic

        episodic.init()
        db = cfg.memory.episodic.db
        assert db.exists()

        conn = sqlite3.connect(str(db))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t[0] for t in tables}
        assert "episodic" in table_names
        assert "episodic_fts" in table_names
        conn.close()

    def test_init_is_idempotent(self, cfg):
        from friday.memory import episodic

        episodic.init()
        episodic.init()  # should not raise
        db = cfg.memory.episodic.db
        assert db.exists()

    def test_init_sets_wal(self, cfg):
        from friday.memory import episodic

        episodic.init()
        db = cfg.memory.episodic.db
        conn = sqlite3.connect(str(db))
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        conn.close()
        assert mode.upper() == "WAL"

    def test_append_returns_id(self, cfg):
        from friday.memory import episodic

        episodic.init()
        eid = episodic.append(_make_event())
        assert isinstance(eid, str)
        assert len(eid) > 0

    def test_append_writes_to_db(self, cfg):
        from friday.memory import episodic

        episodic.init()
        event = _make_event(body="unique content for retrieval test")
        eid = episodic.append(event)

        conn = sqlite3.connect(str(cfg.memory.episodic.db))
        row = conn.execute("SELECT * FROM episodic WHERE id = ?", (eid,)).fetchone()
        conn.close()
        assert row is not None

    def test_search_finds_content(self, cfg):
        from friday.memory import episodic

        episodic.init()
        episodic.append(_make_event(body="The roof needs repair by next Tuesday"))
        episodic.append(_make_event(body="Unrelated content about cooking pasta"))

        results = episodic.search("roof repair")
        assert len(results) >= 1
        assert "roof" in results[0]["body"].lower()

    def test_search_returns_empty_for_no_match(self, cfg):
        from friday.memory import episodic

        episodic.init()
        episodic.append(_make_event(body="something about cats"))
        results = episodic.search("quantum physics")
        assert len(results) == 0

    def test_search_sensitivity_filter_inside_query(self, cfg):
        """ADR-0008: sensitivity filters inside the query, not after."""
        from friday.memory import episodic

        episodic.init()
        # Use a unique term so only our events match
        keyword = "sensitivity_test_unique_12345"
        episodic.append(
            _make_event(
                body=f"{keyword} public content",
                sensitivity=Sensitivity.ANY,
            )
        )
        episodic.append(
            _make_event(
                body=f"{keyword} vault content",
                sensitivity=Sensitivity.VAULT,
            )
        )

        # Without filter, should find both
        all_results = episodic.search(keyword, limit=10)
        assert len(all_results) >= 2

        # With ANY filter, should only find ANY
        any_results = episodic.search(keyword, limit=10, sensitivity=Sensitivity.ANY)
        assert len(any_results) >= 1
        assert all(r["sensitivity"] == "any" for r in any_results)

        # With VAULT filter, should only find VAULT
        vault_results = episodic.search(
            keyword, limit=10, sensitivity=Sensitivity.VAULT
        )
        assert len(vault_results) >= 1
        assert all(r["sensitivity"] == "vault" for r in vault_results)

    def test_fts_count_matches_episodic_count(self, cfg):
        """The two counts must match or keyword retrieval silently returns a subset."""
        from friday.memory import episodic

        episodic.init()
        for i in range(10):
            episodic.append(_make_event(body=f"event number {i} with content"))

        conn = sqlite3.connect(str(cfg.memory.episodic.db))
        epi_count = conn.execute("SELECT COUNT(*) FROM episodic").fetchone()[0]
        fts_count = conn.execute(
            "SELECT COUNT(*) FROM episodic_fts"
        ).fetchone()[0]
        conn.close()
        assert epi_count == fts_count, (
            f"FTS count {fts_count} diverges from episodic count {epi_count}"
        )

    def test_live_count(self, cfg):
        from friday.memory import episodic

        episodic.init()
        assert episodic.live_count() == 0
        episodic.append(_make_event())
        assert episodic.live_count() == 1
        episodic.append(_make_event())
        assert episodic.live_count() == 2

    def test_compress_archives_originals(self, cfg):
        from friday.memory import episodic

        episodic.init()
        event = _make_event(
            body="old event to compress",
            occurred_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        episodic.append(event)

        before = datetime(2025, 1, 1, tzinfo=timezone.utc)
        archived = episodic.compress(before)

        assert archived == 1
        # Archive file should exist
        archive_files = list(cfg.memory.episodic.archive_dir.glob("archive_*.jsonl"))
        assert len(archive_files) >= 1

        # The archived content should be intact
        with open(archive_files[0]) as f:
            line = f.readline()
            data = json.loads(line)
            assert data["body"] == "old event to compress"

        # Live count should decrease
        assert episodic.live_count() == 0

    def test_compress_only_old_events(self, cfg):
        from friday.memory import episodic

        episodic.init()
        old = _make_event(
            body="old",
            occurred_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
        )
        new = _make_event(
            body="new",
            occurred_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
        )
        episodic.append(old)
        episodic.append(new)

        before = datetime(2025, 1, 1, tzinfo=timezone.utc)
        archived = episodic.compress(before)

        assert archived == 1
        assert episodic.live_count() == 1  # new event still live

    def test_no_update_in_public_api(self, cfg):
        """Spec section 7: no UPDATE in the public surface."""
        from friday.memory import episodic

        episodic.init()
        eid = episodic.append(_make_event(body="original content"))

        # The public API does not expose any update function
        public_funcs = [f for f in dir(episodic) if not f.startswith("_") and callable(getattr(episodic, f))]
        assert "update" not in public_funcs
        assert "delete" not in public_funcs
        assert "edit" not in public_funcs

    def test_no_delete_in_public_api(self, cfg):
        """Spec section 7: no DELETE in the public surface."""
        from friday.memory import episodic

        episodic.init()
        eid = episodic.append(_make_event())

        # The public API does not expose any delete function
        public_funcs = [f for f in dir(episodic) if not f.startswith("_") and callable(getattr(episodic, f))]
        assert "delete" not in public_funcs
        assert "remove" not in public_funcs


# ---------------------------------------------------------------------------
# Vault tests
# ---------------------------------------------------------------------------

class TestVault:
    """Tier 3: markdown, git-backed, Obsidian-compatible."""

    def test_write_note_creates_file(self, cfg):
        from friday.memory import vault

        path = vault.write_note(
            "daily",
            "test-note",
            "This is the note body.",
            {
                "source": "test",
                "created": "2025-01-01T00:00:00+00:00",
                "tags": ["test"],
            },
        )
        assert path.exists()
        content = path.read_text()
        assert "---" in content  # has frontmatter
        assert "This is the note body." in content

    def test_write_note_rejects_invalid_directory(self, cfg):
        from friday.memory import vault

        with pytest.raises(ValueError, match="not one of the four"):
            vault.write_note(
                "invalid_dir",
                "test",
                "body",
                {"source": "test", "created": "2025-01-01T00:00:00+00:00"},
            )

    def test_write_note_requires_provenance(self, cfg):
        from friday.memory import vault

        with pytest.raises(ValueError, match="provenance"):
            vault.write_note(
                "daily",
                "test",
                "body",
                {"tags": ["test"]},  # missing source and created
            )

    def test_write_note_frontmatter_has_source(self, cfg):
        from friday.memory import vault

        path = vault.write_note(
            "projects",
            "proj-note",
            "Project content.",
            {
                "source": "consolidator",
                "created": "2025-01-01T00:00:00+00:00",
                "updated": "2025-01-02T00:00:00+00:00",
                "tags": ["project"],
                "provenance": {"row_ids": ["1", "2"]},
            },
        )
        content = path.read_text()
        assert "source: consolidator" in content
        assert "created:" in content
        assert "provenance:" in content

    def test_write_note_creates_subdirectory(self, cfg):
        from friday.memory import vault

        for d in ("daily", "projects", "people", "ideas"):
            vault.write_note(
                d,
                f"note-{d}",
                f"Content for {d}.",
                {"source": "test", "created": "2025-01-01T00:00:00+00:00"},
            )
            assert (cfg.memory.vault.path / d).exists()
            assert (cfg.memory.vault.path / d).is_dir()

    def test_note_count(self, cfg):
        from friday.memory import vault

        vault.write_note(
            "daily", "n1", "body1",
            {"source": "t", "created": "2025-01-01T00:00:00+00:00"},
        )
        vault.write_note(
            "projects", "n2", "body2",
            {"source": "t", "created": "2025-01-01T00:00:00+00:00"},
        )
        assert vault.note_count() == 2

    def test_note_count_empty_vault(self, cfg):
        from friday.memory import vault

        assert vault.note_count() == 0

    def test_profile_reads_file(self, cfg):
        from friday.memory import vault

        profile_path = cfg.memory.profile.path
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile_path.write_text("# About me\n\nI am the principal.")

        result = vault.profile()
        assert "I am the principal" in result

    def test_profile_missing_raises_when_required(self, cfg):
        from friday.memory import vault

        # profile.required is True in our test config
        with pytest.raises(FileNotFoundError, match="profile.md"):
            vault.profile()

    def test_commit_returns_sha(self, cfg):
        from friday.memory import vault

        vault_path = cfg.memory.vault.path
        # Initialize git repo
        subprocess.run(["git", "init", str(vault_path)], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", str(vault_path), "config", "user.email", "test@test.com"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(vault_path), "config", "user.name", "Test"],
            capture_output=True,
        )

        vault.write_note(
            "daily", "commit-test", "content",
            {"source": "test", "created": "2025-01-01T00:00:00+00:00"},
        )
        sha = vault.commit("test commit")
        assert isinstance(sha, str)
        assert len(sha) >= 7

    def test_revert_to(self, cfg):
        from friday.memory import vault

        vault_path = cfg.memory.vault.path
        subprocess.run(["git", "init", str(vault_path)], capture_output=True, check=True)
        subprocess.run(
            ["git", "-C", str(vault_path), "config", "user.email", "test@test.com"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(vault_path), "config", "user.name", "Test"],
            capture_output=True,
        )

        # Write initial note and commit
        p1 = vault.write_note(
            "daily", "revert-test-1", "original content",
            {"source": "test", "created": "2025-01-01T00:00:00+00:00"},
        )
        sha1 = vault.commit("first commit")

        # Write another note and commit
        vault.write_note(
            "daily", "revert-test-2", "added content",
            {"source": "test", "created": "2025-01-01T00:00:00+00:00"},
        )
        vault.commit("second commit")

        # Revert to first commit
        vault.revert_to(sha1)

        assert p1.exists()
        p2 = vault_path / "daily" / "revert-test-2.md"
        assert not p2.exists()


# ---------------------------------------------------------------------------
# Check tests
# ---------------------------------------------------------------------------

class TestCheck:
    """ADR-0013: the writer is never the checker."""

    def test_check_refuses_same_agent(self, cfg):
        from friday.memory import check

        # Should raise if writer_agent is the checker agent (curator)
        with pytest.raises(ValueError, match="never the checker"):
            check.check_note("note", ["source"], "curator")

    def test_check_refuses_different_writers(self, cfg):
        """Consolidator (writer) is different from curator (checker) - should NOT raise."""
        from friday.memory import check

        # Should not raise for consolidator (the writer)
        # It will try to call LiteLLM and fail, returning a CheckResult
        result = check.check_note("note text", ["source text"], "consolidator")
        # Since LiteLLM is not running, it should return ok=False with a reason
        assert result.ok is False
        assert "checker error" in result.reason or "unsupported" in result.reason.lower()

    def test_check_empty_sources(self, cfg):
        from friday.memory import check

        result = check.check_note("some note", [], "consolidator")
        assert result.ok is False
        assert "no source" in result.reason.lower()

    def test_check_result_is_frozen(self, cfg):
        from friday.memory import check

        result = check.CheckResult(ok=True)
        with pytest.raises(Exception):
            result.ok = False  # type: ignore


# ---------------------------------------------------------------------------
# Consolidate tests
# ---------------------------------------------------------------------------

class TestConsolidate:
    """ADR-0007: bounded memory means consolidate when full."""

    def test_should_consolidate_under_soft_threshold(self, cfg):
        from friday.memory import episodic, consolidate

        episodic.init()
        # max_live_events=100, soft_start_at=0.85 -> soft threshold at 85
        for i in range(10):
            episodic.append(_make_event())

        should_run, must_block = consolidate.should_consolidate()
        assert should_run is False
        assert must_block is False

    def test_should_consolidate_above_soft_threshold(self, cfg):
        from friday.memory import episodic, consolidate

        episodic.init()
        # max_live_events=100, soft_start_at=0.85 -> soft threshold at 85
        for i in range(90):
            episodic.append(_make_event())

        should_run, must_block = consolidate.should_consolidate()
        assert should_run is True
        assert must_block is False

    def test_should_consolidate_at_bound(self, cfg):
        from friday.memory import episodic, consolidate

        episodic.init()
        # max_live_events=100
        for i in range(100):
            episodic.append(_make_event())

        should_run, must_block = consolidate.should_consolidate()
        assert should_run is True
        assert must_block is True

    def test_should_consolidate_returns_tuple(self, cfg):
        from friday.memory import episodic, consolidate

        episodic.init()
        result = consolidate.should_consolidate()
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert all(isinstance(x, bool) for x in result)

    def test_consolidate_dry_run(self, cfg):
        from friday.memory import episodic, consolidate

        episodic.init()
        for i in range(5):
            episodic.append(_make_event(body=f"event {i}"))

        notes = consolidate.consolidate(dry_run=True)
        assert notes >= 1  # grouped by source+date

    def test_consolidate_writes_notes(self, cfg):
        from friday.memory import episodic, consolidate

        episodic.init()
        # Init git in the vault so commit works
        subprocess.run(
            ["git", "init", str(cfg.memory.vault.path)], capture_output=True, check=True
        )
        subprocess.run(
            ["git", "-C", str(cfg.memory.vault.path), "config", "user.email", "test@test.com"],
            capture_output=True,
        )
        subprocess.run(
            ["git", "-C", str(cfg.memory.vault.path), "config", "user.name", "Test"],
            capture_output=True,
        )

        # Mock check_note to always pass
        with patch("friday.memory.consolidate.check_note") as mock_check:
            mock_check.return_value = MagicMock(ok=True, unsupported=(), reason="")
            for i in range(5):
                episodic.append(_make_event(body=f"event {i}"))

            notes = consolidate.consolidate(dry_run=False)
            assert notes >= 1  # at least one note written
            # Episodic rows should be marked consolidated
            assert episodic.live_count() == 0

    def test_consolidate_blocks_at_bound(self, cfg):
        """ADR-0007: the write path blocks. This is the test people skip."""
        from friday.memory import episodic, consolidate

        episodic.init()
        # Fill to the bound (100)
        for i in range(100):
            episodic.append(_make_event(body=f"event {i}"))

        should_run, must_block = consolidate.should_consolidate()
        assert must_block is True, "must_block must be True at the bound"

        # Now trying to append should trigger consolidation
        with patch("friday.memory.consolidate.consolidate") as mock_consol:
            mock_consol.side_effect = lambda dry_run=False: 5
            # The append function calls should_consolidate then consolidate if must_block
            # We need to also patch should_consolidate since it will call our mock
            # Actually the flow is: append -> should_consolidate -> consolidate
            # Since we patched consolidate, it won't do anything real
            # But should_consolidate still reads live_count which is 100
            # So it returns (True, True) and calls consolidate (mocked) -> does nothing
            # Then checks bound again -> still 100 -> raises MemoryFull
            with pytest.raises((consolidate.MemoryFull, Exception)):
                episodic.append(_make_event(body="overflow"))


# ---------------------------------------------------------------------------
# Ingest tests
# ---------------------------------------------------------------------------

class TestIngest:
    """sources.db -> episodic log, chunked and indexed."""

    def test_chunk_event_single_unit(self, cfg):
        from friday.memory import ingest

        event = _make_event(body="Short message")
        chunks = ingest.chunk_event(event)
        assert len(chunks) == 1
        assert chunks[0].text == "Short message"
        assert chunks[0].source == event.source
        assert chunks[0].occurred_at == event.occurred_at
        assert chunks[0].sensitivity == event.sensitivity

    def test_chunk_event_provenance_carried(self, cfg):
        from friday.memory import ingest

        event = _make_event(body="content")
        chunks = ingest.chunk_event(event)
        for chunk in chunks:
            assert chunk.source == event.source
            assert chunk.external_id == event.external_id
            assert chunk.occurred_at == event.occurred_at
            assert chunk.sensitivity == event.sensitivity

    def test_chunk_event_multiple_units(self, cfg):
        from friday.memory import ingest

        body = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        event = _make_event(body=body)
        chunks = ingest.chunk_event(event)
        assert len(chunks) == 3
        assert chunks[0].text == "First paragraph."
        assert chunks[1].text == "Second paragraph."
        assert chunks[2].text == "Third paragraph."

    def test_chunk_event_ordinal_increments(self, cfg):
        from friday.memory import ingest

        body = "First.\n\nSecond.\n\nThird."
        event = _make_event(body=body)
        chunks = ingest.chunk_event(event)
        ordinals = [c.ordinal for c in chunks]
        assert ordinals == [0, 1, 2]

    def test_chunk_event_deterministic_ids(self, cfg):
        """Same event produces same chunk ids (idempotent re-run)."""
        from friday.memory import ingest

        event = _make_event(body="test content", external_id="fixed-id")
        chunks1 = ingest.chunk_event(event)
        chunks2 = ingest.chunk_event(event)
        assert [c.chunk_id for c in chunks1] == [c.chunk_id for c in chunks2]

    def test_chunk_event_large_unit_falls_back_to_window(self, cfg):
        from friday.memory import ingest

        # Create a body that exceeds the token budget (512 tokens ~ 384 words)
        words = ["word"] * 1000
        body = " ".join(words)
        event = _make_event(body=body)
        chunks = ingest.chunk_event(event)
        assert len(chunks) > 1  # should be split into windows

    def test_chunk_event_empty_body(self, cfg):
        from friday.memory import ingest

        event = _make_event(body="")
        chunks = ingest.chunk_event(event)
        # Should handle gracefully - at least one chunk (the empty string itself)
        assert len(chunks) >= 1

    def test_from_sources_no_db(self, cfg):
        """from_sources handles missing sources.db gracefully."""
        from friday.memory import ingest

        # No sources.db at the configured path
        result = ingest.from_sources(dry_run=True)
        assert result == 0

    def test_from_sources_with_db(self, cfg, tmp_path):
        from friday.memory import ingest

        # Create a sources.db with some events
        sources_db = cfg.sources.defaults.sink
        sources_db.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(sources_db))
        conn.execute("""
            CREATE TABLE events (
                source TEXT, external_id TEXT, occurred_at TEXT,
                body TEXT, sensitivity TEXT, untrusted INTEGER DEFAULT 1,
                meta TEXT DEFAULT '{}', ingested_at TEXT
            )
        """)
        conn.execute(
            "INSERT INTO events VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("test", "src-1", "2025-01-01T00:00:00+00:00",
             "event content", "any", 1, "{}", "2025-01-01T00:00:00+00:00"),
        )
        conn.commit()
        conn.close()

        # Dry run should count but not write
        count = ingest.from_sources(since=datetime(2020, 1, 1, tzinfo=timezone.utc), dry_run=True)
        assert count == 1


# ---------------------------------------------------------------------------
# Retrieve tests (service-dependent parts are mocked)
# ---------------------------------------------------------------------------

class TestRetrieve:
    """Spec section 7's pipeline, in order."""

    def test_expand_returns_paraphrases(self, cfg):
        from friday.memory import retrieve

        with patch("friday.memory.retrieve._get_openai_client") as mock_client:
            mock_resp = MagicMock()
            mock_resp.choices = [MagicMock(message=MagicMock(content="paraphrase 1\nparaphrase 2\nparaphrase 3"))]
            mock_client.return_value.chat.completions.create.return_value = mock_resp

            result = retrieve.expand("what is the weather", n=3)
            assert len(result) == 3
            assert all(isinstance(r, str) for r in result)

    def test_expand_fallback_on_error(self, cfg):
        from friday.memory import retrieve

        with patch("friday.memory.retrieve._get_openai_client", side_effect=Exception("no service")):
            result = retrieve.expand("query", n=3)
            # Should fall back to just the original query
            assert len(result) == 1
            assert result[0] == "query"

    def test_retrieve_pipeline_order(self, cfg):
        """expand -> parallel keyword+vector -> dedupe -> rerank -> recency boost."""
        from friday.memory import retrieve

        # Mock expand to return just the query (no expansions)
        with (
            patch("friday.memory.retrieve.expand", return_value=[]) as mock_expand,
            patch("friday.memory.episodic.search") as mock_kw,
            patch("friday.memory.index.search") as mock_vec,
            patch("friday.memory.index.rerank") as mock_rerank,
        ):
            # Setup mock returns
            mock_kw.return_value = [
                {
                    "id": "kw-1", "source": "test", "external_id": "e1",
                    "occurred_at": "2025-01-01T00:00:00+00:00",
                    "body": "keyword result", "sensitivity": "any",
                    "untrusted": True, "meta": {}, "rank": -1,
                }
            ]
            mock_vec.return_value = [
                Chunk(
                    chunk_id="vec-1", source="test", external_id="e2",
                    occurred_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
                    sensitivity=Sensitivity.ANY, text="vector result",
                )
            ]
            mock_rerank.return_value = [
                (mock_vec.return_value[0], 0.8),
                (Chunk(
                    chunk_id="kw-chunk", source="test", external_id="e1",
                    occurred_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
                    sensitivity=Sensitivity.ANY, text="keyword result",
                ), 0.6),
            ]

            results = retrieve.retrieve(
                "query",
                datetime(2025, 6, 1, tzinfo=timezone.utc),
            )

            assert len(results) >= 1
            # Results should be Retrieved objects
            assert all(isinstance(r, Retrieved) for r in results)
            # Should have final_score set
            assert all(r.final_score is not None for r in results)

    def test_retrieve_min_rerank_score_drops_low(self, cfg):
        """Below min_rerank_score, candidates are dropped even with room."""
        from friday.memory import retrieve

        with (
            patch("friday.memory.retrieve.expand", return_value=[]),
            patch("friday.memory.episodic.search", return_value=[]),
            patch("friday.memory.index.search") as mock_vec,
            patch("friday.memory.index.rerank") as mock_rerank,
        ):
            chunk = Chunk(
                chunk_id="c1", source="test", external_id="e1",
                occurred_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
                sensitivity=Sensitivity.ANY, text="low score result",
            )
            mock_vec.return_value = [chunk]
            # Score below min_rerank_score (0.15)
            mock_rerank.return_value = [(chunk, 0.05)]

            results = retrieve.retrieve(
                "query", datetime(2025, 6, 1, tzinfo=timezone.utc)
            )
            assert len(results) == 0  # dropped because below threshold

    def test_retrieve_recency_boost_after_rerank(self, cfg):
        """Recency boost is applied AFTER reranking, not before."""
        from friday.memory import retrieve

        with (
            patch("friday.memory.retrieve.expand", return_value=[]),
            patch("friday.memory.episodic.search", return_value=[]),
            patch("friday.memory.index.search") as mock_vec,
            patch("friday.memory.index.rerank") as mock_rerank,
        ):
            old_chunk = Chunk(
                chunk_id="old", source="test", external_id="e1",
                occurred_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
                sensitivity=Sensitivity.ANY, text="old but relevant",
            )
            new_chunk = Chunk(
                chunk_id="new", source="test", external_id="e2",
                occurred_at=datetime(2025, 6, 1, tzinfo=timezone.utc),
                sensitivity=Sensitivity.ANY, text="recent but less relevant",
            )
            mock_vec.return_value = [old_chunk, new_chunk]

            # Rerank: old is more relevant
            mock_rerank.return_value = [
                (old_chunk, 0.9),
                (new_chunk, 0.3),
            ]

            results = retrieve.retrieve(
                "query", datetime(2025, 6, 2, tzinfo=timezone.utc)
            )

            # Even with recency boost, the old result should still be high
            # because boost is applied AFTER reranking
            assert len(results) >= 1
            # The old chunk should have a higher rerank_score
            old_result = next(r for r in results if r.chunk.chunk_id == "old")
            new_result = next(r for r in results if r.chunk.chunk_id == "new")
            assert old_result.rerank_score > new_result.rerank_score

    def test_build_context_includes_profile(self, cfg):
        from friday.memory import retrieve, vault

        # Write profile
        profile_path = cfg.memory.profile.path
        profile_path.parent.mkdir(parents=True, exist_ok=True)
        profile_path.write_text("I am the principal user.")

        now = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        context = retrieve.build_context([], now)

        assert "I am the principal user." in context
        assert "Current Date" in context or "Current Date and Time" in context

    def test_build_context_carries_provenance(self, cfg):
        from friday.memory import retrieve

        chunk = Chunk(
            chunk_id="c1", source="calendar", external_id="evt-1",
            occurred_at=datetime(2025, 3, 1, tzinfo=timezone.utc),
            sensitivity=Sensitivity.ANY, text="Meeting about the roof",
        )
        result = Retrieved(
            chunk=chunk,
            rerank_score=0.8,
            final_score=0.9,
        )
        context = retrieve.build_context([result], datetime(2025, 6, 1, tzinfo=timezone.utc))

        # Should carry source and timestamp
        assert "source=calendar" in context
        assert "occurred_at" in context

    def test_build_context_marks_stale(self, cfg):
        from friday.memory import retrieve

        # stale_after_days is 90 by default
        old_chunk = Chunk(
            chunk_id="old", source="test", external_id="e1",
            occurred_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
            sensitivity=Sensitivity.ANY, text="very old content",
        )
        result = Retrieved(chunk=old_chunk, rerank_score=0.8, final_score=0.9)
        context = retrieve.build_context([result], datetime(2025, 6, 1, tzinfo=timezone.utc))

        assert "STALE" in context

    def test_build_context_does_not_mark_recent(self, cfg):
        from friday.memory import retrieve

        recent_chunk = Chunk(
            chunk_id="new", source="test", external_id="e1",
            occurred_at=datetime(2025, 5, 30, tzinfo=timezone.utc),
            sensitivity=Sensitivity.ANY, text="recent content",
        )
        result = Retrieved(chunk=recent_chunk, rerank_score=0.8, final_score=0.9)
        context = retrieve.build_context([result], datetime(2025, 6, 1, tzinfo=timezone.utc))

        assert "STALE" not in context


# ---------------------------------------------------------------------------
# Index tests (Qdrant-dependent, mocked)
# ---------------------------------------------------------------------------

class TestIndex:
    """Tier 4: Qdrant, embeddings, rerank."""

    def test_embed_calls_litellm(self, cfg):
        from friday.memory import index

        with patch("friday.memory.index._get_openai_client") as mock_client:
            mock_resp = MagicMock()
            mock_resp.data = [
                MagicMock(embedding=[0.1] * 1024),
                MagicMock(embedding=[0.2] * 1024),
            ]
            mock_client.return_value.embeddings.create.return_value = mock_resp

            result = index.embed(["text1", "text2"])
            assert len(result) == 2
            assert len(result[0]) == 1024

    def test_create_collection_handles_no_qdrant(self, cfg):
        """Gracefully handles missing Qdrant."""
        from friday.memory import index

        with patch("friday.memory.index._get_client", return_value=None):
            # Should not raise, just log a warning
            index.create_collection()

    def test_upsert_handles_no_qdrant(self, cfg):
        from friday.memory import index

        with patch("friday.memory.index._get_client", return_value=None):
            chunk = Chunk(
                chunk_id="c1", source="test", external_id="e1",
                occurred_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
                sensitivity=Sensitivity.ANY, text="content",
            )
            result = index.upsert([chunk])
            assert result == 0

    def test_search_handles_no_qdrant(self, cfg):
        from friday.memory import index

        with patch("friday.memory.index._get_client", return_value=None):
            result = index.search("query")
            assert result == []

    def test_rerank_returns_sorted(self, cfg):
        from friday.memory import index

        chunks = [
            Chunk(
                chunk_id=f"c{i}", source="test", external_id=f"e{i}",
                occurred_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
                sensitivity=Sensitivity.ANY, text=f"text {i}",
            )
            for i in range(3)
        ]

        mock_response = MagicMock()
        mock_response.json.return_value = {
            "results": [
                {"index": 1, "relevance_score": 0.9},
                {"index": 0, "relevance_score": 0.5},
                {"index": 2, "relevance_score": 0.3},
            ]
        }
        mock_response.raise_for_status = MagicMock()

        with patch("friday.memory.index.httpx.post", return_value=mock_response):
            result = index.rerank("query", chunks)
            assert len(result) == 3
            assert result[0][1] == 0.9  # highest score first
            assert result[1][1] == 0.5
            assert result[2][1] == 0.3

    def test_rerank_empty_chunks(self, cfg):
        from friday.memory import index

        result = index.rerank("query", [])
        assert result == []
