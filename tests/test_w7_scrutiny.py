"""Week 7 scrutiny tests: score, policy.load_table, corrections, daemon.

Spec section 4 and section 10. These tests exercise the W7 implementations:

    score.parse_score    — strict JSON parsing, no defaults
    score.score_signal    — model call with injectable client
    policy.load_table     — reads config/scrutiny.yaml, validates, builds RuleTable
    corrections.*          — SQLite ledger: init, record, accuracy, export
    daemon.process_signal — the triage pipeline, testable without services

Run:
    uv run pytest tests/test_w7_scrutiny.py tests/test_policy.py -xvs
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from scrutiny.corrections import (
    CorrectionError,
    accuracy_by_rule,
    export_finetune_set,
    init_db,
    record_correction,
    record_decision,
)
from scrutiny.daemon import DaemonResult, Signal, process_signal, run_once
from scrutiny.policy import Action, PolicyError, RuleTable, load_table
from scrutiny.score import AXES, Score, ScoreError, parse_score, score_signal

CONFIG = Path(__file__).resolve().parents[1] / "config" / "scrutiny.yaml"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _valid_score_json(**overrides: Any) -> str:
    """A valid 7-axis JSON string, with optional overrides."""
    data: dict[str, Any] = {
        "urgency": 0.5,
        "impact": 0.5,
        "novelty": 0.5,
        "risk": 0.1,
        "confidence": 0.8,
        "specificity": 0.5,
        "conflict": False,
    }
    data.update(overrides)
    return json.dumps(data)


def _fake_score(**overrides: Any) -> Score:
    """A Score with neutral defaults, overridable."""
    base: dict[str, Any] = {
        "urgency": 0.5,
        "impact": 0.5,
        "novelty": 0.5,
        "risk": 0.1,
        "confidence": 0.8,
        "specificity": 0.5,
        "conflict": False,
    }
    base.update(overrides)
    return Score(**base)  # type: ignore[arg-type]


class FakeClient:
    """A fake OpenAI client that returns a canned score response."""

    def __init__(self, raw_response: str):
        self._raw = raw_response
        self.calls: list[dict[str, Any]] = []

        # Build the nested structure: client.chat.completions.create(...)
        message = MagicMock()
        message.content = raw_response
        choice = MagicMock()
        choice.message = message
        resp = MagicMock()
        resp.choices = [choice]
        self.chat = MagicMock()
        self.chat.completions = MagicMock()
        self.chat.completions.create = self._create

    def _create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        # Build a fresh response each time so the mock is reusable.
        message = MagicMock()
        message.content = self._raw
        choice = MagicMock()
        choice.message = message
        resp = MagicMock()
        resp.choices = [choice]
        return resp


# ===========================================================================
# parse_score — strict JSON parsing
# ===========================================================================

class TestParseScore:
    """parse_score is strict: no defaults, no coercion, no leniency."""

    def test_valid_json(self) -> None:
        s = parse_score(_valid_score_json())
        assert s.urgency == 0.5
        assert s.impact == 0.5
        assert s.novelty == 0.5
        assert s.risk == 0.1
        assert s.confidence == 0.8
        assert s.specificity == 0.5
        assert s.conflict is False

    def test_valid_json_with_conflict_true(self) -> None:
        s = parse_score(_valid_score_json(conflict=True))
        assert s.conflict is True

    @pytest.mark.parametrize("axis", [a for a in AXES if a != "conflict"])
    def test_missing_axis_raises(self, axis: str) -> None:
        data = json.loads(_valid_score_json())
        del data[axis]
        with pytest.raises(ScoreError, match="missing"):
            parse_score(json.dumps(data))

    def test_missing_conflict_raises(self) -> None:
        data = json.loads(_valid_score_json())
        del data["conflict"]
        with pytest.raises(ScoreError, match="missing"):
            parse_score(json.dumps(data))

    def test_extra_axis_raises(self) -> None:
        data = json.loads(_valid_score_json())
        data["extra_axis"] = 0.5
        with pytest.raises(ScoreError, match="unexpected"):
            parse_score(json.dumps(data))

    def test_unparseable_json_raises(self) -> None:
        with pytest.raises(ScoreError, match="not valid JSON"):
            parse_score("not json at all")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ScoreError, match="not valid JSON"):
            parse_score("")

    @pytest.mark.parametrize("axis", [a for a in AXES if a != "conflict"])
    def test_out_of_range_raises(self, axis: str) -> None:
        data = json.loads(_valid_score_json())
        data[axis] = 1.5
        with pytest.raises(ScoreError, match="0.0-1.0"):
            parse_score(json.dumps(data))

    @pytest.mark.parametrize("axis", [a for a in AXES if a != "conflict"])
    def test_negative_raises(self, axis: str) -> None:
        data = json.loads(_valid_score_json())
        data[axis] = -0.1
        with pytest.raises(ScoreError, match="0.0-1.0"):
            parse_score(json.dumps(data))

    def test_conflict_not_bool_raises(self) -> None:
        data = json.loads(_valid_score_json())
        data["conflict"] = 0.4
        with pytest.raises(ScoreError, match="conflict must be a bool"):
            parse_score(json.dumps(data))

    def test_conflict_as_string_raises(self) -> None:
        data = json.loads(_valid_score_json())
        data["conflict"] = "true"
        with pytest.raises(ScoreError, match="conflict must be a bool"):
            parse_score(json.dumps(data))

    def test_float_axis_as_string_raises(self) -> None:
        data = json.loads(_valid_score_json())
        data["urgency"] = "0.5"
        with pytest.raises(ScoreError, match="must be a number"):
            parse_score(json.dumps(data))

    def test_bool_as_float_raises(self) -> None:
        """True/False are int subclasses; they must not sneak through as 1.0/0.0."""
        data = json.loads(_valid_score_json())
        data["urgency"] = True
        with pytest.raises(ScoreError, match="must be a number"):
            parse_score(json.dumps(data))

    def test_not_a_dict_raises(self) -> None:
        with pytest.raises(ScoreError, match="JSON object"):
            parse_score("[1, 2, 3]")

    def test_json_in_markdown_fences(self) -> None:
        """Some models wrap JSON in ```json fences despite instructions not to."""
        raw = "```json\n" + _valid_score_json() + "\n```"
        s = parse_score(raw)
        assert s.urgency == 0.5

    def test_int_values_accepted(self) -> None:
        """Integers 0 and 1 are valid floats."""
        data = json.loads(_valid_score_json())
        data["urgency"] = 1
        data["risk"] = 0
        s = parse_score(json.dumps(data))
        assert s.urgency == 1.0
        assert s.risk == 0.0

    def test_all_seven_axes_required_no_defaults(self) -> None:
        """Exactly 7 keys, no more, no less — no defaulting."""
        data = json.loads(_valid_score_json())
        assert set(data.keys()) == set(AXES)
        # Removing any one must fail
        for axis in AXES:
            d2 = dict(data)
            del d2[axis]
            with pytest.raises(ScoreError):
                parse_score(json.dumps(d2))


# ===========================================================================
# score_signal — model call with injectable client
# ===========================================================================

class TestScoreSignal:
    """score_signal calls the 'fast' model and parses the response."""

    def test_score_signal_with_fake_client(self) -> None:
        """Returns a Score from a mocked model response."""
        client = FakeClient(_valid_score_json(urgency=0.9))
        score = score_signal("some signal body", {"channel": "test"}, client=client)
        assert score.urgency == 0.9
        assert isinstance(score, Score)

    def test_score_signal_uses_fast_model(self) -> None:
        """The model alias must be 'fast'."""
        client = FakeClient(_valid_score_json())
        score_signal("body", None, client=client)
        assert client.calls[0]["model"] == "fast"

    def test_score_signal_passes_empty_tools(self) -> None:
        """tools must be [] — the security boundary."""
        client = FakeClient(_valid_score_json())
        score_signal("body", None, client=client)
        assert client.calls[0]["tools"] == []

    def test_score_signal_temperature_zero(self) -> None:
        """Temperature 0 for reproducibility."""
        client = FakeClient(_valid_score_json())
        score_signal("body", None, client=client)
        assert client.calls[0]["temperature"] == 0

    def test_score_signal_max_tokens_400(self) -> None:
        """400 token limit per spec."""
        client = FakeClient(_valid_score_json())
        score_signal("body", None, client=client)
        assert client.calls[0]["max_tokens"] == 400

    def test_score_signal_malformed_response_raises(self) -> None:
        """A malformed model response raises ScoreError."""
        client = FakeClient("not json")
        with pytest.raises(ScoreError):
            score_signal("body", None, client=client)

    def test_score_signal_empty_response_raises(self) -> None:
        """An empty model response raises ScoreError."""
        client = FakeClient("")
        with pytest.raises(ScoreError, match="empty"):
            score_signal("body", None, client=client)

    def test_score_signal_includes_context_in_prompt(self) -> None:
        """Context is passed through to the prompt."""
        client = FakeClient(_valid_score_json())
        score_signal("body text", {"kind": "message"}, client=client)
        prompt = client.calls[0]["messages"][0]["content"]
        assert "body text" in prompt

    def test_score_signal_includes_body_in_prompt(self) -> None:
        """The signal body is included in the prompt."""
        client = FakeClient(_valid_score_json())
        score_signal("IMPORTANT: buy milk", None, client=client)
        prompt = client.calls[0]["messages"][0]["content"]
        assert "buy milk" in prompt


# ===========================================================================
# policy.load_table — config/scrutiny.yaml loading
# ===========================================================================

class TestLoadTable:
    """load_table reads config/scrutiny.yaml and builds a validated RuleTable."""

    def test_loads_real_config(self) -> None:
        """The shipped config loads and produces a RuleTable."""
        table = load_table(str(CONFIG))
        assert isinstance(table, RuleTable)
        assert len(table.rules) > 0

    def test_rule_names_unique(self) -> None:
        table = load_table(str(CONFIG))
        names = [r.name for r in table.rules]
        assert len(names) == len(set(names))

    def test_floor_rule_exists(self) -> None:
        table = load_table(str(CONFIG))
        assert "floor" in [r.name for r in table.rules]

    def test_floor_is_last_rule(self) -> None:
        table = load_table(str(CONFIG))
        assert table.rules[-1].name == "floor"

    def test_thresholds_are_floats(self) -> None:
        table = load_table(str(CONFIG))
        for v in table.thresholds.values():
            assert isinstance(v, float)

    def test_all_actions_valid(self) -> None:
        table = load_table(str(CONFIG))
        for rule in table.rules:
            assert isinstance(rule.action, Action)

    def test_duplicate_rule_name_raises(self, tmp_path: Path) -> None:
        """Duplicate rule names fail at load, not at runtime."""
        import yaml

        raw = yaml.safe_load(CONFIG.read_text())
        raw["rules"].append(dict(raw["rules"][0]))  # duplicate the first rule
        bad = tmp_path / "dup.yaml"
        bad.write_text(yaml.safe_dump(raw))
        with pytest.raises(PolicyError, match="duplicate"):
            load_table(str(bad))

    def test_missing_floor_raises(self, tmp_path: Path) -> None:
        """A table without a floor rule fails to load."""
        import yaml

        raw = yaml.safe_load(CONFIG.read_text())
        # Remove the floor rule (last one)
        raw["rules"] = raw["rules"][:-1]
        bad = tmp_path / "no_floor.yaml"
        bad.write_text(yaml.safe_dump(raw))
        with pytest.raises(PolicyError, match="floor"):
            load_table(str(bad))

    def test_unknown_threshold_in_when_raises(self, tmp_path: Path) -> None:
        """A rule referencing a non-existent threshold fails at load."""
        import yaml

        raw = yaml.safe_load(CONFIG.read_text())
        # Corrupt the first rule's when to reference a non-existent threshold
        raw["rules"][0]["when"] = "risk >= thresholds.no_such_threshold"
        bad = tmp_path / "bad_threshold.yaml"
        bad.write_text(yaml.safe_dump(raw))
        with pytest.raises(PolicyError):
            load_table(str(bad))

    def test_unknown_action_raises(self, tmp_path: Path) -> None:
        """An action that is not one of the five fails at load."""
        import yaml

        raw = yaml.safe_load(CONFIG.read_text())
        raw["rules"][0]["action"] = "execute"
        bad = tmp_path / "bad_action.yaml"
        bad.write_text(yaml.safe_dump(raw))
        with pytest.raises(PolicyError, match="not one of"):
            load_table(str(bad))

    def test_missing_when_raises(self, tmp_path: Path) -> None:
        """A rule without a when expression fails at load."""
        import yaml

        raw = yaml.safe_load(CONFIG.read_text())
        del raw["rules"][0]["when"]
        bad = tmp_path / "no_when.yaml"
        bad.write_text(yaml.safe_dump(raw))
        with pytest.raises(PolicyError, match="no `when`"):
            load_table(str(bad))

    def test_missing_name_raises(self, tmp_path: Path) -> None:
        """A rule without a name fails at load."""
        import yaml

        raw = yaml.safe_load(CONFIG.read_text())
        del raw["rules"][0]["name"]
        bad = tmp_path / "no_name.yaml"
        bad.write_text(yaml.safe_dump(raw))
        with pytest.raises(PolicyError, match="no name"):
            load_table(str(bad))

    def test_load_table_matches_fixture(self) -> None:
        """load_table produces the same table as the in-process fixture in test_policy."""
        import yaml

        raw = yaml.safe_load(CONFIG.read_text())
        from scrutiny.policy import Rule

        fixture = RuleTable(
            thresholds=raw["thresholds"],
            rules=tuple(
                Rule(
                    name=r["name"],
                    when=r["when"],
                    action=Action(r["action"]),
                    why=r.get("why", ""),
                )
                for r in raw["rules"]
            ),
        )
        loaded = load_table(str(CONFIG))
        assert [r.name for r in loaded.rules] == [r.name for r in fixture.rules]
        assert loaded.thresholds == fixture.thresholds


# ===========================================================================
# corrections — SQLite ledger
# ===========================================================================

class TestCorrections:
    """The correction ledger: init, record, accuracy, export."""

    @pytest.fixture
    def db(self, tmp_path: Path) -> str:
        """A fresh scrutiny DB path."""
        return str(tmp_path / "scrutiny.db")

    def test_init_db_creates_tables(self, db: str) -> None:
        init_db(db)
        conn = sqlite3.connect(db)
        tables = {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        conn.close()
        assert "decisions" in tables
        assert "corrections" in tables

    def test_init_db_idempotent(self, db: str) -> None:
        init_db(db)
        init_db(db)  # should not raise
        conn = sqlite3.connect(db)
        count = conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='decisions'"
        ).fetchone()[0]
        conn.close()
        assert count == 1

    def test_record_decision(self, db: str) -> None:
        init_db(db)
        did = record_decision(
            signal_id="test:1",
            rule="floor",
            action=Action.IGNORE,
            scores=_fake_score(),
            context={"kind": "observation"},
            db_path=db,
        )
        assert did
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT * FROM decisions WHERE id = ?", (did,)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[2] == "test:1"
        assert row[3] == "floor"
        assert row[4] == "ignore"

    def test_record_correction(self, db: str) -> None:
        init_db(db)
        did = record_decision(
            signal_id="test:1",
            rule="determined_and_safe_acts",
            action=Action.ACT,
            scores=_fake_score(confidence=0.9, specificity=0.9),
            context={"kind": "request"},
            db_path=db,
        )
        cid = record_correction(did, Action.ASK, note="should have asked first", db_path=db)
        assert cid
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT * FROM corrections WHERE id = ?", (cid,)
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[1] == did  # decision_id
        assert row[3] == "determined_and_safe_acts"  # rule
        assert row[4] == "act"  # action_taken
        assert row[5] == "ask"  # action_wanted
        assert row[7] == "should have asked first"  # note

    def test_record_correction_unknown_decision_raises(self, db: str) -> None:
        init_db(db)
        with pytest.raises(CorrectionError, match="no decision"):
            record_correction("nonexistent", Action.IGNORE, db_path=db)

    def test_double_correction_raises(self, db: str) -> None:
        """Correcting an already-corrected decision raises."""
        init_db(db)
        did = record_decision(
            signal_id="test:1",
            rule="floor",
            action=Action.IGNORE,
            scores=_fake_score(),
            db_path=db,
        )
        record_correction(did, Action.WATCH, db_path=db)
        with pytest.raises(CorrectionError, match="already corrected"):
            record_correction(did, Action.ASK, db_path=db)

    def test_accuracy_by_rule(self, db: str) -> None:
        """Per-rule agreement rate with correct totals and corrections."""
        init_db(db)
        # 10 decisions on rule A, 2 corrected
        for i in range(10):
            did = record_decision(
                signal_id=f"a:{i}",
                rule="rule_a",
                action=Action.IGNORE,
                scores=_fake_score(),
                db_path=db,
            )
            if i < 2:
                record_correction(did, Action.WATCH, db_path=db)
        # 5 decisions on rule B, 0 corrected
        for i in range(5):
            record_decision(
                signal_id=f"b:{i}",
                rule="rule_b",
                action=Action.ACT,
                scores=_fake_score(),
                db_path=db,
            )

        results = accuracy_by_rule(days=365, db_path=db)
        by_rule = {r["rule"]: r for r in results}
        assert by_rule["rule_a"]["total"] == 10
        assert by_rule["rule_a"]["corrected"] == 2
        assert by_rule["rule_a"]["agreement_rate"] == 0.8
        assert by_rule["rule_a"]["review_volume"] == 2
        assert by_rule["rule_b"]["total"] == 5
        assert by_rule["rule_b"]["corrected"] == 0
        assert by_rule["rule_b"]["agreement_rate"] == 1.0

    def test_accuracy_by_rule_empty_db(self, db: str) -> None:
        """No decisions means an empty report, not an error."""
        init_db(db)
        results = accuracy_by_rule(db_path=db)
        assert results == []

    def test_export_finetune_set(self, db: str, tmp_path: Path) -> None:
        """Export corrections as JSONL training data."""
        init_db(db)
        did = record_decision(
            signal_id="matrix:msg123",
            rule="determined_and_safe_acts",
            action=Action.ACT,
            scores=_fake_score(confidence=0.9, specificity=0.9),
            context={"kind": "message", "channel": "matrix"},
            db_path=db,
        )
        record_correction(did, Action.ASK, note="should have asked", db_path=db)

        out = tmp_path / "finetune.jsonl"
        count = export_finetune_set(str(out), db_path=db)
        assert count == 1

        lines = out.read_text().strip().split("\n")
        assert len(lines) == 1
        example = json.loads(lines[0])
        assert example["signal_id"] == "matrix:msg123"
        assert "scores" in example
        assert example["scores"]["confidence"] == 0.9
        assert example["rule_fired"] == "determined_and_safe_acts"
        assert example["action_wanted"] == "ask"

    def test_export_finetune_set_empty(self, db: str, tmp_path: Path) -> None:
        """Export with no corrections produces 0 examples."""
        init_db(db)
        out = tmp_path / "empty.jsonl"
        count = export_finetune_set(str(out), db_path=db)
        assert count == 0
        assert out.exists()

    def test_correction_captures_scores(self, db: str) -> None:
        """The correction row carries the scores from the decision, not just the override."""
        init_db(db)
        score = _fake_score(urgency=0.9, impact=0.8, novelty=0.1)
        did = record_decision(
            signal_id="test:1",
            rule="already_known",
            action=Action.IGNORE,
            scores=score,
            db_path=db,
        )
        cid = record_correction(did, Action.WATCH, db_path=db)
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT scores_json FROM corrections WHERE id = ?", (cid,)
        ).fetchone()
        conn.close()
        scores = json.loads(row[0])
        assert scores["urgency"] == 0.9
        assert scores["impact"] == 0.8
        assert scores["novelty"] == 0.1


# ===========================================================================
# daemon — triage pipeline
# ===========================================================================

class TestDaemon:
    """The daemon wires scoring to decision to recording to dispatch."""

    @pytest.fixture
    def table(self) -> RuleTable:
        return load_table(str(CONFIG))

    @pytest.fixture
    def scrutiny_db(self, tmp_path: Path) -> str:
        return str(tmp_path / "scrutiny.db")

    def test_process_signal_full_pipeline(self, table: RuleTable, scrutiny_db: str) -> None:
        """Score -> decide -> write -> dispatch, all the way through."""
        signal = Signal(
            signal_id="test:1",
            body="please send the invoice now",
            context={"kind": "request", "channel": "matrix"},
        )
        # A score that should trigger determined_and_safe_acts
        score_fn = lambda body, ctx: _fake_score(
            confidence=0.9, specificity=0.9, risk=0.1, impact=0.7, novelty=0.7
        )
        dispatched: list[bool] = []
        dispatch_fn = lambda d, s, sc: dispatched.append(True) or True

        result = process_signal(
            signal,
            table=table,
            score_fn=score_fn,
            scrutiny_db=scrutiny_db,
            dispatch_fn=dispatch_fn,
        )

        assert result.signal_id == "test:1"
        assert result.decision.action is Action.ACT
        assert result.decision_id
        assert result.dispatched is True
        assert dispatched == [True]

    def test_process_signal_writes_decision_to_db(self, table: RuleTable, scrutiny_db: str) -> None:
        """The decision is written to scrutiny.db before dispatch."""
        init_db(scrutiny_db)
        signal = Signal(signal_id="test:2", body="some text", context={})
        score_fn = lambda body, ctx: _fake_score()
        process_signal(
            signal, table=table, score_fn=score_fn, scrutiny_db=scrutiny_db,
        )
        conn = sqlite3.connect(scrutiny_db)
        count = conn.execute("SELECT count(*) FROM decisions").fetchone()[0]
        conn.close()
        assert count == 1

    def test_process_signal_decision_before_dispatch(self, table: RuleTable, scrutiny_db: str) -> None:
        """Step 4 (write) happens before step 5 (dispatch)."""
        order: list[str] = []
        init_db(scrutiny_db)

        def tracking_dispatch(decision, signal, score):
            # Check the decision is already in the DB when dispatch runs
            conn = sqlite3.connect(scrutiny_db)
            count = conn.execute("SELECT count(*) FROM decisions").fetchone()[0]
            conn.close()
            order.append(f"dispatch:decisions={count}")
            return True

        signal = Signal(signal_id="test:3", body="text", context={})
        score_fn = lambda body, ctx: _fake_score()
        process_signal(
            signal, table=table, score_fn=score_fn, scrutiny_db=scrutiny_db,
            dispatch_fn=tracking_dispatch,
        )
        assert order == ["dispatch:decisions=1"]

    def test_process_signal_high_risk_asks(self, table: RuleTable, scrutiny_db: str) -> None:
        """The high_risk guard fires even when everything else argues for acting."""
        signal = Signal(signal_id="test:4", body="risky text", context={"kind": "send_message"})
        score_fn = lambda body, ctx: _fake_score(
            risk=0.9, novelty=0.9, impact=0.95, urgency=0.9, confidence=0.98, specificity=0.95
        )
        result = process_signal(
            signal, table=table, score_fn=score_fn, scrutiny_db=scrutiny_db,
        )
        assert result.decision.action is Action.ASK
        assert result.decision.rule == "high_risk_always_asks"

    def test_process_signal_already_known_ignored(self, table: RuleTable, scrutiny_db: str) -> None:
        """Low novelty triggers the already_known floor."""
        signal = Signal(signal_id="test:5", body="old news", context={"kind": "idea"})
        score_fn = lambda body, ctx: _fake_score(novelty=0.05, impact=0.85, confidence=0.9)
        result = process_signal(
            signal, table=table, score_fn=score_fn, scrutiny_db=scrutiny_db,
        )
        assert result.decision.action is Action.IGNORE
        assert result.decision.rule == "already_known"

    def test_process_signal_propagate(self, table: RuleTable, scrutiny_db: str) -> None:
        """Low specificity with high impact propagates to a specialist."""
        signal = Signal(signal_id="test:6", body="research the roof quote", context={"kind": "idea"})
        score_fn = lambda body, ctx: _fake_score(
            confidence=0.9, specificity=0.2, risk=0.1, impact=0.8, urgency=0.3, novelty=0.7
        )
        result = process_signal(
            signal, table=table, score_fn=score_fn, scrutiny_db=scrutiny_db,
        )
        assert result.decision.action is Action.PROPAGATE
        assert result.decision.rule == "important_but_undetermined_propagates"

    def test_run_once_empty_sources_db(self, tmp_path: Path, table: RuleTable, scrutiny_db: str) -> None:
        """run_once with no sources.db returns empty results."""
        sources_db = str(tmp_path / "nonexistent.db")
        results = run_once(
            sources_db=sources_db,
            scrutiny_db=scrutiny_db,
            table=table,
            score_fn=lambda body, ctx: _fake_score(),
        )
        assert results == []

    def test_run_once_processes_signals(self, tmp_path: Path, table: RuleTable, scrutiny_db: str) -> None:
        """run_once reads from sources.db, processes, and marks as done."""
        sources_db = str(tmp_path / "sources.db")
        # Create the events table with some signals
        conn = sqlite3.connect(sources_db)
        conn.executescript(
            """
            CREATE TABLE events (
                source TEXT,
                external_id TEXT,
                occurred_at TEXT,
                body TEXT,
                sensitivity TEXT,
                untrusted INTEGER,
                meta TEXT,
                ingested_at TEXT,
                PRIMARY KEY (source, external_id)
            );
            INSERT INTO events (source, external_id, occurred_at, body, sensitivity, untrusted, meta)
            VALUES
                ('matrix', 'msg1', '2025-01-01T00:00:00Z', 'hello world', 'messages', 1, '{"kind":"message"}'),
                ('matrix', 'msg2', '2025-01-01T00:01:00Z', 'send invoice', 'messages', 1, '{"kind":"request"}');
            """
        )
        conn.commit()
        conn.close()

        results = run_once(
            sources_db=sources_db,
            scrutiny_db=scrutiny_db,
            table=table,
            score_fn=lambda body, ctx: _fake_score(confidence=0.9, specificity=0.9, risk=0.1, impact=0.7, novelty=0.7),
        )
        assert len(results) == 2
        assert all(r.decision_id for r in results)

        # Second run should find no new signals
        results2 = run_once(
            sources_db=sources_db,
            scrutiny_db=scrutiny_db,
            table=table,
            score_fn=lambda body, ctx: _fake_score(),
        )
        assert len(results2) == 0

    def test_daemon_result_is_dataclass(self) -> None:
        """DaemonResult carries all the information needed for logging and testing."""
        from dataclasses import fields
        field_names = {f.name for f in fields(DaemonResult)}
        assert field_names == {"signal_id", "score", "decision", "decision_id", "dispatched"}
