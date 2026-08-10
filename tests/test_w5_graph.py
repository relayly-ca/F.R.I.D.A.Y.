"""W5 graph layer tests.

These tests RUN TODAY and pass without running services. They use temporary directories
for checkpoints and in-process graph definitions, so nothing depends on /srv/friday or on
scrutiny's dispatch (which lands in W7).

    .venv-test/bin/python -m pytest tests/test_w5_graph.py -xvs

What is being protected:

  1. ``spend`` appends to history and updates the aggregate, but does NOT enforce a ceiling.
  2. Checkpoints persist after every node and load by run_id.
  3. ``resumable`` returns only WAITING, SUSPENDED, or KILLED runs.
  4. ``suspend`` parks at the cursor without discarding.
  5. ``raise_gate`` checkpoints as WAITING before dispatching the ask.
  6. ``answer`` records the decision and transitions state correctly.
  7. ``load_graph`` validates reachability, writer!=checker, agent existence, and gate
     expensive_because — all at load time.
  8. ``run`` executes with checkpoints and returns the correct terminal status.
  9. ``resume`` re-enters the cursor node with optional amendment.
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytest

# Ensure the project root is on the path for imports.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from friday.graph import checkpoint
from friday.graph.gate import GateDecision, HumanGate, answer, raise_gate
from friday.graph.runner import (
    GraphError,
    load_graph,
    resume,
    run,
)
from friday.graph.state import GraphState, RunStatus

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path: Path, monkeypatch) -> Path:
    """A temporary SQLite path for checkpoints, patched into all modules."""
    p = tmp_path / "checkpoints.db"
    checkpoint.init_db(p)

    # Patch the checkpoint module's default path resolver so all callers (gate, runner)
    # that go through checkpoint's internal functions land in our temp DB.
    monkeypatch.setattr(checkpoint, "_default_db_path", lambda: p)

    # Also patch the functions that gate and runner imported at module level.
    import friday.graph.gate as gate_mod
    import friday.graph.runner as runner_mod

    # Make their imported copies route through our patched checkpoint functions.
    # checkpoint.save/load accept an optional path arg; when called without one,
    # _default_db_path (now patched) provides the path.
    gate_mod.save = checkpoint.save
    gate_mod._cp_load = checkpoint.load
    runner_mod.save = checkpoint.save
    runner_mod._cp_load = checkpoint.load
    runner_mod.init_db = checkpoint.init_db

    return p


@pytest.fixture
def graphs_dir(tmp_path: Path) -> Path:
    """A temporary directory for graph definitions."""
    d = tmp_path / "graphs"
    d.mkdir()
    return d


def _make_state(
    run_id: str = "test-run-1",
    graph: str = "test_graph",
    status: RunStatus = RunStatus.RUNNING,
    cursor: str | None = "node_a",
) -> GraphState:
    """Create a GraphState for testing."""
    now = datetime.now()
    return GraphState(
        run_id=run_id,
        graph=graph,
        status=status,
        started_at=now,
        updated_at=now,
        cursor=cursor,
    )


def _write_graph(graphs_dir: Path, name: str, content: str) -> Path:
    """Write a graph module to the graphs directory."""
    p = graphs_dir / f"{name}.py"
    p.write_text(content)
    return p


# ---------------------------------------------------------------------------
# Test: GraphState.spend
# ---------------------------------------------------------------------------

class TestSpend:
    """spend() appends to history and updates the aggregate; no ceiling."""

    def test_spend_appends_history(self):
        state = _make_state()
        assert len(state.history) == 0
        assert state.tokens_spent == 0

        state.spend(100, node="my_node", agent="consolidator")

        assert len(state.history) == 1
        rec = state.history[0]
        assert rec.tokens == 100
        assert rec.node == "my_node"
        assert rec.agent == "consolidator"

    def test_spend_updates_aggregate(self):
        state = _make_state()
        state.spend(50, node="a")
        state.spend(75, node="b")
        assert state.tokens_spent == 125

    def test_spend_does_not_enforce_ceiling(self):
        """The supervisor enforces the ceiling, not spend()."""
        state = _make_state()
        state.spend(10_000_000)
        assert state.tokens_spent == 10_000_000

    def test_spend_negative_raises(self):
        state = _make_state()
        with pytest.raises(ValueError, match="non-negative"):
            state.spend(-1)

    def test_spend_defaults_to_cursor_node(self):
        state = _make_state(cursor="current_node")
        state.spend(10)
        assert state.history[-1].node == "current_node"

    def test_spend_defaults_to_unknown_when_no_cursor(self):
        state = _make_state(cursor=None)
        state.spend(10)
        assert state.history[-1].node == "unknown"


# ---------------------------------------------------------------------------
# Test: Checkpoint persistence
# ---------------------------------------------------------------------------

class TestCheckpoint:
    """init_db, save, load, resumable, suspend."""

    def test_init_db_idempotent(self, tmp_path: Path):
        p = tmp_path / "cp.db"
        checkpoint.init_db(p)
        checkpoint.init_db(p)
        assert p.exists()

    def test_save_and_load_roundtrip(self, db_path: Path):
        state = _make_state(run_id="rt-1")
        state.spend(42, node="a")
        checkpoint.save(state)

        loaded = checkpoint.load("rt-1")
        assert loaded.run_id == "rt-1"
        assert loaded.graph == "test_graph"
        assert loaded.status == RunStatus.RUNNING
        assert loaded.tokens_spent == 42
        assert len(loaded.history) == 1
        assert loaded.history[0].tokens == 42

    def test_load_missing_raises_keyerror(self, db_path: Path):
        with pytest.raises(KeyError, match="no checkpoint"):
            checkpoint.load("nonexistent")

    def test_save_updates_existing(self, db_path: Path):
        state = _make_state(run_id="upd-1")
        state.spend(10, node="a")
        checkpoint.save(state)

        state.spend(20, node="b")
        state.status = RunStatus.DONE
        checkpoint.save(state)

        loaded = checkpoint.load("upd-1")
        assert loaded.tokens_spent == 30
        assert loaded.status == RunStatus.DONE

    def test_resumable_returns_waiting_suspended_killed(self, db_path: Path):
        s_running = _make_state(run_id="r-run", status=RunStatus.RUNNING)
        checkpoint.save(s_running)

        s_waiting = _make_state(run_id="r-wait", status=RunStatus.WAITING)
        checkpoint.save(s_waiting)

        s_suspended = _make_state(run_id="r-susp", status=RunStatus.SUSPENDED)
        checkpoint.save(s_suspended)

        s_killed = _make_state(run_id="r-kill", status=RunStatus.KILLED)
        checkpoint.save(s_killed)

        s_done = _make_state(run_id="r-done", status=RunStatus.DONE)
        checkpoint.save(s_done)

        result = checkpoint.resumable()
        run_ids = {s.run_id for s in result}
        assert "r-wait" in run_ids
        assert "r-susp" in run_ids
        assert "r-kill" in run_ids
        assert "r-run" not in run_ids
        assert "r-done" not in run_ids

    def test_resumable_filtered_by_graph(self, db_path: Path):
        s1 = _make_state(run_id="g1-1", graph="graph_one", status=RunStatus.SUSPENDED)
        checkpoint.save(s1)
        s2 = _make_state(run_id="g2-1", graph="graph_two", status=RunStatus.SUSPENDED)
        checkpoint.save(s2)

        result = checkpoint.resumable(graph="graph_one")
        assert len(result) == 1
        assert result[0].run_id == "g1-1"

    def test_suspend_parks_at_cursor(self, db_path: Path):
        state = _make_state(run_id="susp-1", cursor="node_b", status=RunStatus.RUNNING)
        checkpoint.save(state)

        checkpoint.suspend("susp-1", reason="barge_in:new_task")

        loaded = checkpoint.load("susp-1")
        assert loaded.status == RunStatus.SUSPENDED
        assert loaded.cursor == "node_b"
        assert loaded.suspended_for == "barge_in:new_task"

    def test_suspend_missing_raises_keyerror(self, db_path: Path):
        with pytest.raises(KeyError):
            checkpoint.suspend("nonexistent", reason="test")

    def test_suspend_with_killed_status(self, db_path: Path):
        state = _make_state(run_id="kill-1", status=RunStatus.RUNNING)
        checkpoint.save(state)

        checkpoint.suspend("kill-1", reason="budget_kill",
                           status=RunStatus.KILLED)

        loaded = checkpoint.load("kill-1")
        assert loaded.status == RunStatus.KILLED
        assert loaded.suspended_for == "budget_kill"

    def test_persists_data_dict(self, db_path: Path):
        state = _make_state(run_id="data-1")
        state.data["query"] = "what's the weather"
        state.data["route"] = "researcher"
        checkpoint.save(state)

        loaded = checkpoint.load("data-1")
        assert loaded.data["query"] == "what's the weather"
        assert loaded.data["route"] == "researcher"


# ---------------------------------------------------------------------------
# Test: Human gate
# ---------------------------------------------------------------------------

class TestGate:
    """raise_gate and answer."""

    @pytest.fixture
    def gate(self) -> HumanGate:
        return HumanGate(
            name="vault_write_gate",
            summary="Write a daily note to the vault",
            expensive_because="Vault writes persist to disk and git; a wrong note "
                              "is editable but visible until corrected.",
        )

    def test_raise_gate_checkpoints_as_waiting(self, db_path: Path, gate: HumanGate):
        state = _make_state(run_id="gate-1", cursor="write_node", status=RunStatus.RUNNING)
        checkpoint.save(state)

        raise_gate(gate, "gate-1")

        loaded = checkpoint.load("gate-1")
        assert loaded.status == RunStatus.WAITING
        assert loaded.cursor == "write_node"
        assert loaded.suspended_for == f"gate:{gate.name}"

    def test_raise_gate_records_gate_in_data(self, db_path: Path, gate: HumanGate):
        state = _make_state(run_id="gate-2", status=RunStatus.RUNNING)
        checkpoint.save(state)

        raise_gate(gate, "gate-2", context={"note": "daily.md"})

        loaded = checkpoint.load("gate-2")
        gates = loaded.data.get("_gates", [])
        assert len(gates) == 1
        assert gates[0]["name"] == gate.name
        assert gates[0]["status"] == "pending"
        assert gates[0]["context"]["note"] == "daily.md"

    def test_answer_approved_resumes(self, db_path: Path, gate: HumanGate):
        state = _make_state(run_id="gate-3", cursor="write", status=RunStatus.WAITING)
        state.data["_gates"] = [{
            "name": gate.name,
            "summary": gate.summary,
            "expensive_because": gate.expensive_because,
            "context": {},
            "status": "pending",
        }]
        state.suspended_for = f"gate:{gate.name}"
        checkpoint.save(state)

        answer("gate-3", GateDecision.APPROVED)

        loaded = checkpoint.load("gate-3")
        assert loaded.status == RunStatus.PENDING
        assert loaded.suspended_for is None
        assert loaded.data["_gates"][-1]["status"] == "approved"

    def test_answer_rejected_fails_run(self, db_path: Path, gate: HumanGate):
        state = _make_state(run_id="gate-4", status=RunStatus.WAITING)
        state.data["_gates"] = [{
            "name": gate.name,
            "summary": gate.summary,
            "expensive_because": gate.expensive_because,
            "context": {},
            "status": "pending",
        }]
        checkpoint.save(state)

        answer("gate-4", GateDecision.REJECTED)

        loaded = checkpoint.load("gate-4")
        assert loaded.status == RunStatus.FAILED

    def test_answer_amended_applies_amendment(self, db_path: Path, gate: HumanGate):
        state = _make_state(run_id="gate-5", status=RunStatus.WAITING)
        state.data["target"] = "original_target"
        state.data["_gates"] = [{
            "name": gate.name,
            "summary": gate.summary,
            "expensive_because": gate.expensive_because,
            "context": {},
            "status": "pending",
        }]
        checkpoint.save(state)

        answer("gate-5", GateDecision.AMENDED, amendment={"target": "new_target"})

        loaded = checkpoint.load("gate-5")
        assert loaded.status == RunStatus.PENDING
        assert loaded.data["target"] == "new_target"
        assert loaded.data["_gates"][-1]["amendment"]["target"] == "new_target"

    def test_answer_on_non_waiting_raises(self, db_path: Path):
        state = _make_state(run_id="gate-6", status=RunStatus.RUNNING)
        checkpoint.save(state)

        with pytest.raises(ValueError, match="not WAITING"):
            answer("gate-6", GateDecision.APPROVED)


# ---------------------------------------------------------------------------
# Test: Graph validation (load_graph)
# ---------------------------------------------------------------------------

class TestLoadGraph:
    """load_graph validations."""

    def test_simple_graph_loads(self, graphs_dir: Path):
        _write_graph(graphs_dir, "simple", '''
from friday.graph.runner import NodeDef

ENTRY = "start"
NODES = {
    "start": NodeDef(name="start", agent="conversation", fn=lambda s: s),
    "end": NodeDef(name="end", agent="conversation", fn=lambda s: s),
}
EDGES = {"start": "end", "end": None}
''')
        graph = load_graph("simple", root=graphs_dir)
        assert graph.entry == "start"
        assert "start" in graph.nodes
        assert "end" in graph.nodes
        assert graph.edges["start"] == ["end"]

    def test_missing_entry_raises(self, graphs_dir: Path):
        _write_graph(graphs_dir, "no_entry", '''
from friday.graph.runner import NodeDef
NODES = {"a": NodeDef(name="a", agent="conversation", fn=lambda s: s)}
EDGES = {}
''')
        with pytest.raises(GraphError, match="no ENTRY"):
            load_graph("no_entry", root=graphs_dir)

    def test_entry_not_in_nodes_raises(self, graphs_dir: Path):
        _write_graph(graphs_dir, "bad_entry", '''
from friday.graph.runner import NodeDef
ENTRY = "nonexistent"
NODES = {"a": NodeDef(name="a", agent="conversation", fn=lambda s: s)}
EDGES = {}
''')
        with pytest.raises(GraphError, match="entry node.*not in NODES"):
            load_graph("bad_entry", root=graphs_dir)

    def test_unreachable_node_raises(self, graphs_dir: Path):
        _write_graph(graphs_dir, "unreachable", '''
from friday.graph.runner import NodeDef
ENTRY = "a"
NODES = {
    "a": NodeDef(name="a", agent="conversation", fn=lambda s: s),
    "b": NodeDef(name="b", agent="conversation", fn=lambda s: s),
    "orphan": NodeDef(name="orphan", agent="conversation", fn=lambda s: s),
}
EDGES = {"a": "b", "b": None}
''')
        with pytest.raises(GraphError, match="unreachable"):
            load_graph("unreachable", root=graphs_dir)

    def test_edge_to_unknown_node_raises(self, graphs_dir: Path):
        _write_graph(graphs_dir, "bad_edge", '''
from friday.graph.runner import NodeDef
ENTRY = "a"
NODES = {"a": NodeDef(name="a", agent="conversation", fn=lambda s: s)}
EDGES = {"a": "nonexistent"}
''')
        with pytest.raises(GraphError, match="targets unknown node"):
            load_graph("bad_edge", root=graphs_dir)

    def test_writer_without_checker_raises(self, graphs_dir: Path):
        """ADR-0013: a writing node must have a checker before it."""
        _write_graph(graphs_dir, "no_checker", '''
from friday.graph.runner import NodeDef
ENTRY = "write_node"
NODES = {
    "write_node": NodeDef(name="write_node", agent="consolidator", fn=lambda s: s, writes=True),
}
EDGES = {"write_node": None}
''')
        with pytest.raises(GraphError, match="writes=True but has no checker"):
            load_graph("no_checker", root=graphs_dir)

    def test_writer_with_same_agent_checker_raises(self, graphs_dir: Path):
        """ADR-0013: the checker must be a different agent."""
        _write_graph(graphs_dir, "same_checker", '''
from friday.graph.runner import NodeDef
ENTRY = "check"
NODES = {
    "check": NodeDef(name="check", agent="consolidator", fn=lambda s: s, checks="write"),
    "write": NodeDef(name="write", agent="consolidator", fn=lambda s: s, writes=True),
}
EDGES = {"check": "write", "write": None}
''')
        with pytest.raises(GraphError, match="same agent"):
            load_graph("same_checker", root=graphs_dir)

    def test_writer_with_different_agent_checker_passes(self, graphs_dir: Path):
        """ADR-0013: a different-agent checker before a writer is valid."""
        _write_graph(graphs_dir, "good_checker", '''
from friday.graph.runner import NodeDef
ENTRY = "check"
NODES = {
    "check": NodeDef(name="check", agent="curator", fn=lambda s: s, checks="write"),
    "write": NodeDef(name="write", agent="consolidator", fn=lambda s: s, writes=True),
}
EDGES = {"check": "write", "write": None}
''')
        graph = load_graph("good_checker", root=graphs_dir)
        assert graph.entry == "check"

    def test_unknown_agent_raises(self, graphs_dir: Path):
        _write_graph(graphs_dir, "bad_agent", '''
from friday.graph.runner import NodeDef
ENTRY = "a"
NODES = {"a": NodeDef(name="a", agent="nonexistent_agent", fn=lambda s: s)}
EDGES = {"a": None}
''')
        with pytest.raises(GraphError, match="not in config/agents.yaml"):
            load_graph("bad_agent", root=graphs_dir)

    def test_gate_without_expensive_because_raises(self, graphs_dir: Path):
        _write_graph(graphs_dir, "bad_gate", '''
from friday.graph.runner import NodeDef
from friday.graph.gate import HumanGate
ENTRY = "a"
NODES = {
    "a": NodeDef(
        name="a", agent="conversation", fn=lambda s: s,
        gate=HumanGate(name="g", summary="s", expensive_because=""),
    ),
}
EDGES = {"a": None}
''')
        with pytest.raises(GraphError, match="empty expensive_because"):
            load_graph("bad_gate", root=graphs_dir)

    def test_gate_with_expensive_because_passes(self, graphs_dir: Path):
        _write_graph(graphs_dir, "good_gate", '''
from friday.graph.runner import NodeDef
from friday.graph.gate import HumanGate
ENTRY = "a"
NODES = {
    "a": NodeDef(
        name="a", agent="conversation", fn=lambda s: s,
        gate=HumanGate(
            name="g", summary="approving a write",
            expensive_because="vault writes persist to git and disk",
        ),
    ),
}
EDGES = {"a": None}
''')
        graph = load_graph("good_gate", root=graphs_dir)
        assert graph.nodes["a"].gate is not None

    def test_graph_not_found_raises(self, graphs_dir: Path):
        with pytest.raises(GraphError, match="not found"):
            load_graph("nonexistent", root=graphs_dir)

    def test_multi_edge_graph(self, graphs_dir: Path):
        _write_graph(graphs_dir, "multi", '''
from friday.graph.runner import NodeDef
ENTRY = "a"
NODES = {
    "a": NodeDef(name="a", agent="conversation", fn=lambda s: s),
    "b": NodeDef(name="b", agent="conversation", fn=lambda s: s),
    "c": NodeDef(name="c", agent="conversation", fn=lambda s: s),
}
EDGES = {"a": ["b", "c"], "b": None, "c": None}
''')
        graph = load_graph("multi", root=graphs_dir)
        assert set(graph.edges["a"]) == {"b", "c"}


# ---------------------------------------------------------------------------
# Test: Run and resume
# ---------------------------------------------------------------------------

class TestRun:
    """run() and resume()."""

    def test_simple_run_completes(self, graphs_dir: Path, db_path: Path):
        _write_graph(graphs_dir, "simple_run", '''
from friday.graph.runner import NodeDef

def fn_a(state):
    state.data["ran_a"] = True
    return state

def fn_b(state):
    state.data["ran_b"] = True
    return state

ENTRY = "a"
NODES = {
    "a": NodeDef(name="a", agent="conversation", fn=fn_a),
    "b": NodeDef(name="b", agent="conversation", fn=fn_b),
}
EDGES = {"a": "b", "b": None}
''')
        import friday.graph.runner as runner_mod
        original = runner_mod._graphs_dir
        runner_mod._graphs_dir = lambda root=None: graphs_dir
        try:
            state = run("simple_run", inputs={"query": "hello"})
        finally:
            runner_mod._graphs_dir = original

        assert state.status == RunStatus.DONE
        assert state.data["ran_a"] is True
        assert state.data["ran_b"] is True
        assert state.data["query"] == "hello"
        assert len(state.history) == 2

    def test_run_with_gate_parks_waiting(self, graphs_dir: Path, db_path: Path):
        _write_graph(graphs_dir, "gated_run", '''
from friday.graph.runner import NodeDef
from friday.graph.gate import HumanGate

def fn_gate(state):
    state.data["passed_gate"] = True
    return state

ENTRY = "gate_node"
NODES = {
    "gate_node": NodeDef(
        name="gate_node", agent="conversation", fn=fn_gate,
        gate=HumanGate(
            name="test_gate",
            summary="approving a test",
            expensive_because="this is a test of the gate mechanism",
        ),
    ),
}
EDGES = {"gate_node": None}
''')
        import friday.graph.runner as runner_mod
        original = runner_mod._graphs_dir
        runner_mod._graphs_dir = lambda root=None: graphs_dir
        try:
            state = run("gated_run")
        finally:
            runner_mod._graphs_dir = original

        assert state.status == RunStatus.WAITING
        assert state.suspended_for == "gate:test_gate"

    def test_run_checkpoints_after_every_node(self, graphs_dir: Path, db_path: Path):
        _write_graph(graphs_dir, "checkpointed", '''
from friday.graph.runner import NodeDef

def fn_a(state):
    state.data["step"] = 1
    return state

def fn_b(state):
    state.data["step"] = 2
    return state

def fn_c(state):
    state.data["step"] = 3
    return state

ENTRY = "a"
NODES = {
    "a": NodeDef(name="a", agent="conversation", fn=fn_a),
    "b": NodeDef(name="b", agent="conversation", fn=fn_b),
    "c": NodeDef(name="c", agent="conversation", fn=fn_c),
}
EDGES = {"a": "b", "b": "c", "c": None}
''')
        import friday.graph.runner as runner_mod
        original = runner_mod._graphs_dir
        runner_mod._graphs_dir = lambda root=None: graphs_dir
        try:
            state = run("checkpointed")
        finally:
            runner_mod._graphs_dir = original

        assert state.status == RunStatus.DONE
        loaded = checkpoint.load(state.run_id)
        assert loaded.status == RunStatus.DONE
        assert loaded.data["step"] == 3
        assert len(loaded.history) == 3

    def test_resume_from_done_raises(self, graphs_dir: Path, db_path: Path):
        _write_graph(graphs_dir, "resume_test", '''
from friday.graph.runner import NodeDef
ENTRY = "a"
NODES = {"a": NodeDef(name="a", agent="conversation", fn=lambda s: s)}
EDGES = {"a": None}
''')
        import friday.graph.runner as runner_mod
        original = runner_mod._graphs_dir
        runner_mod._graphs_dir = lambda root=None: graphs_dir
        try:
            state = run("resume_test")
            assert state.status == RunStatus.DONE
            with pytest.raises(ValueError, match="only WAITING"):
                resume(state.run_id)
        finally:
            runner_mod._graphs_dir = original

    def test_resume_from_suspended(self, graphs_dir: Path, db_path: Path):
        _write_graph(graphs_dir, "resume_susp", '''
from friday.graph.runner import NodeDef

def fn_a(state):
    state.data.setdefault("a_runs", 0)
    state.data["a_runs"] += 1
    return state

def fn_b(state):
    state.data["b_ran"] = True
    return state

ENTRY = "a"
NODES = {
    "a": NodeDef(name="a", agent="conversation", fn=fn_a),
    "b": NodeDef(name="b", agent="conversation", fn=fn_b),
}
EDGES = {"a": "b", "b": None}
''')
        import friday.graph.runner as runner_mod
        original = runner_mod._graphs_dir
        runner_mod._graphs_dir = lambda root=None: graphs_dir
        try:
            state = run("resume_susp")
            assert state.status == RunStatus.DONE

            checkpoint.suspend(state.run_id, reason="test_suspend")
            loaded = checkpoint.load(state.run_id)
            assert loaded.status == RunStatus.SUSPENDED

            resumed = resume(state.run_id)
        finally:
            runner_mod._graphs_dir = original

        assert resumed.status == RunStatus.DONE
        # The cursor after completion is the last node (b), so resume re-enters b.
        # Node 'a' ran once during the original run and is not re-entered.
        assert resumed.data["a_runs"] == 1
        assert resumed.data["b_ran"] is True

    def test_resume_with_amendment(self, graphs_dir: Path, db_path: Path):
        _write_graph(graphs_dir, "resume_amend", '''
from friday.graph.runner import NodeDef

def fn_a(state):
    state.data["a_ran"] = True
    return state

ENTRY = "a"
NODES = {"a": NodeDef(name="a", agent="conversation", fn=fn_a)}
EDGES = {"a": None}
''')
        import friday.graph.runner as runner_mod
        original = runner_mod._graphs_dir
        runner_mod._graphs_dir = lambda root=None: graphs_dir
        try:
            state = run("resume_amend")
            assert state.status == RunStatus.DONE

            checkpoint.suspend(state.run_id, reason="amend_test")
            resumed = resume(state.run_id, amendment={"corrected": True})
        finally:
            runner_mod._graphs_dir = original

        assert resumed.status == RunStatus.DONE
        assert resumed.data["corrected"] is True

    def test_resumable_lists_parked_runs(self, graphs_dir: Path, db_path: Path):
        _write_graph(graphs_dir, "resumable_test", '''
from friday.graph.runner import NodeDef
ENTRY = "a"
NODES = {"a": NodeDef(name="a", agent="conversation", fn=lambda s: s)}
EDGES = {"a": None}
''')
        import friday.graph.runner as runner_mod
        original = runner_mod._graphs_dir
        runner_mod._graphs_dir = lambda root=None: graphs_dir
        try:
            state = run("resumable_test")
            assert state.status == RunStatus.DONE

            # Should not appear in resumable
            result = checkpoint.resumable()
            assert state.run_id not in {s.run_id for s in result}

            # Suspend and check
            checkpoint.suspend(state.run_id, reason="test")
            result = checkpoint.resumable()
            run_ids = {s.run_id for s in result}
            assert state.run_id in run_ids
        finally:
            runner_mod._graphs_dir = original
