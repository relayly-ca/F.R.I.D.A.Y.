"""The executor. ADR-0012.

Runs a graph, checkpointing after every node, and resumes one from its cursor.

It enforces the two rules from ADR-0013 rather than documenting them, because a rule that
lives only in prose is one a tired evening removes:

  - a node declaring `writes=True` must be immediately preceded by a checker node
  - that checker must run as a DIFFERENT agent than the writer

Both are checked when the graph is loaded, not when the write happens. A graph that would
write unchecked fails at startup, which is the only time anyone is looking.

Graph definitions live under ``agent/core/graphs/`` (ADR-0004) as Python modules. A graph
module defines:

    ENTRY       : str                      — the entry node name
    NODES       : dict[str, NodeDef]        — name → node definition
    EDGES       : dict[str, str | list[str]] — node → next node(s); entry has no predecessor

Each ``NodeDef`` is a dataclass with:

    name        : str           — stable identifier
    agent       : str           — which agent runs this node (must exist in agents.yaml)
    fn          : callable      — (GraphState) -> GraphState
    writes      : bool = False  — whether this node writes to vault/index (ADR-0013)
    checks      : str | None    — name of the node this checker checks (set on checker nodes)
    gate        : HumanGate | None — if set, this node raises a human gate before executing

Edges are inferred from EDGES: ``EDGES[node_name] = "next_node"`` or a list of next nodes.
The entry node is ``ENTRY``. Terminal nodes have ``EDGES[node_name] = None`` or are absent.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from friday.graph.checkpoint import init_db, save
from friday.graph.checkpoint import load as _cp_load
from friday.graph.gate import HumanGate, raise_gate
from friday.graph.state import GraphState, NodeRecord, RunStatus


class GraphError(Exception):
    """Raised when a graph definition is malformed or violates an invariant.

    Never raised for a node failing at runtime - that is a run outcome, recorded in the
    checkpoint. This means the definition itself is wrong.
    """


# ---------------------------------------------------------------------------
# Graph protocol data structures
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NodeDef:
    """One node in a graph definition.

    Attributes:
        name: Stable identifier, matching its key in NODES.
        agent: The agent that runs this node. Must exist in config/agents.yaml.
        fn: Callable taking a GraphState and returning an updated GraphState.
        writes: Whether this node writes to vault or index (ADR-0013).
        checks: If this node is a checker, the name of the node it checks.
        gate: If set, a human gate is raised before this node executes.
    """

    name: str
    agent: str
    fn: Callable[[GraphState], GraphState]
    writes: bool = False
    checks: str | None = None
    gate: HumanGate | None = None


@dataclass
class GraphDef:
    """A loaded, validated graph definition."""

    name: str
    entry: str
    nodes: dict[str, NodeDef]
    edges: dict[str, list[str]]
    module: Any


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _config() -> Any:
    """Return the loaded config, or None if config is unavailable."""
    try:
        from friday.config import get
        return get()
    except Exception:
        return None


def _known_agents() -> set[str]:
    cfg = _config()
    if cfg is None:
        return set()
    return set(cfg.agents.agents.keys())


def _graphs_dir(root: Path | None = None) -> Path:
    cfg = _config()
    if root is not None:
        return root
    if cfg is not None:
        return Path(cfg.friday.paths.core) / "graphs"
    return Path("/srv/friday/agent/core/graphs")


# ---------------------------------------------------------------------------
# Load and validate
# ---------------------------------------------------------------------------

def _load_module(name: str, graphs_dir: Path) -> Any:
    """Import a graph module from the graphs directory."""
    module_path = graphs_dir / f"{name}.py"
    if not module_path.is_file():
        raise GraphError(
            f"graph {name!r} not found at {module_path}. Graph definitions live under "
            f"{graphs_dir}/ (ADR-0004)."
        )
    spec = importlib.util.spec_from_file_location(f"graph_{name}", module_path)
    if spec is None or spec.loader is None:
        raise GraphError(f"cannot load graph module {name!r} from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"graph_{name}"] = module
    spec.loader.exec_module(module)
    return module


def _extract_graph(name: str, module: Any) -> GraphDef:
    """Extract graph structure from a module."""
    entry = getattr(module, "ENTRY", None)
    if not entry:
        raise GraphError(f"graph {name!r}: module has no ENTRY attribute")

    nodes_raw = getattr(module, "NODES", None)
    if not nodes_raw or not isinstance(nodes_raw, dict):
        raise GraphError(f"graph {name!r}: module has no NODES dict")

    edges_raw = getattr(module, "EDGES", {})

    # Normalize nodes
    nodes: dict[str, NodeDef] = {}
    for key, nd in nodes_raw.items():
        if not isinstance(nd, NodeDef):
            raise GraphError(
                f"graph {name!r}: NODES[{key!r}] is {type(nd).__name__}, not NodeDef"
            )
        if nd.name != key:
            raise GraphError(
                f"graph {name!r}: NODES[{key!r}].name is {nd.name!r}, expected {key!r}"
            )
        nodes[key] = nd

    # Normalize edges: each value is a list of target node names
    edges: dict[str, list[str]] = {}
    for src, targets in edges_raw.items():
        if targets is None:
            edges[src] = []
        elif isinstance(targets, str):
            edges[src] = [targets]
        elif isinstance(targets, list):
            edges[src] = list(targets)
        else:
            raise GraphError(
                f"graph {name!r}: EDGES[{src!r}] must be str, list, or None, got "
                f"{type(targets).__name__}"
            )

    # Nodes without an explicit edges entry that are terminal
    for node_name in nodes:
        if node_name not in edges:
            edges[node_name] = []

    return GraphDef(name=name, entry=entry, nodes=nodes, edges=edges, module=module)


def _validate(graph: GraphDef, known_agents: set[str] | None = None) -> None:
    """Run all load-time validations."""
    gname = graph.name

    # 1. Entry exists
    if graph.entry not in graph.nodes:
        raise GraphError(f"graph {gname!r}: entry node {graph.entry!r} not in NODES")

    # 2. Every edge target exists
    for src, targets in graph.edges.items():
        if src not in graph.nodes:
            raise GraphError(
                f"graph {gname!r}: EDGES references unknown source node {src!r}"
            )
        for tgt in targets:
            if tgt not in graph.nodes:
                raise GraphError(
                    f"graph {gname!r}: edge from {src!r} targets unknown node {tgt!r}"
                )

    # 3. Every node reachable from entry (BFS)
    visited: set[str] = set()
    queue = [graph.entry]
    while queue:
        node = queue.pop(0)
        if node in visited:
            continue
        visited.add(node)
        queue.extend(graph.edges.get(node, []))
    unreachable = set(graph.nodes) - visited
    if unreachable:
        raise GraphError(
            f"graph {gname!r}: nodes {sorted(unreachable)!r} are unreachable from entry "
            f"{graph.entry!r}"
        )

    # 4. Every agent named exists in config/agents.yaml
    if known_agents is not None:
        for node_name, nd in graph.nodes.items():
            if nd.agent not in known_agents:
                raise GraphError(
                    f"graph {gname!r}: node {node_name!r} uses agent {nd.agent!r} which is "
                    f"not in config/agents.yaml. An agent without an entry has no budget "
                    f"and no allowlist."
                )

    # 5. Every writing node has a checker immediately before it (ADR-0013)
    #    "Immediately before" means: there exists a node N' such that edges[N'] contains
    #    the writer, and N'.checks == writer.name, and N'.agent != writer.agent.
    for node_name, nd in graph.nodes.items():
        if nd.writes:
            # Find all predecessors that directly edge into this writer
            predecessors = [
                src for src, targets in graph.edges.items() if node_name in targets
            ]
            checkers = [
                src for src in predecessors
                if graph.nodes[src].checks == node_name
            ]
            if not checkers:
                raise GraphError(
                    f"graph {gname!r}: node {node_name!r} declares writes=True but has no "
                    f"checker node immediately before it (ADR-0013). A node that writes "
                    f"without a distinct checker inflates its own confidence."
                )
            for checker_name in checkers:
                checker = graph.nodes[checker_name]
                if checker.agent == nd.agent:
                    raise GraphError(
                        f"graph {gname!r}: checker {checker_name!r} (agent={checker.agent!r}) "
                        f"runs the same agent as writer {node_name!r} (agent={nd.agent!r}). "
                        f"ADR-0013: the checker must be a DIFFERENT agent."
                    )

    # 6. Every gate has non-empty expensive_because
    for node_name, nd in graph.nodes.items():
        if nd.gate is not None:
            if not nd.gate.expensive_because or not nd.gate.expensive_because.strip():
                raise GraphError(
                    f"graph {gname!r}: node {node_name!r} has a gate "
                    f"{nd.gate.name!r} with empty expensive_because. If you cannot write "
                    f"this sentence, the gate is in the wrong place."
                )


def load_graph(name: str, root: Path | None = None) -> GraphDef:
    """Load and validate a graph definition from `agent/core/graphs/`.

    Validation, all of it at load time:
      - every node is reachable from the entry node
      - every edge target exists
      - every writing node has a checker immediately before it (ADR-0013)
      - that checker's agent differs from the writer's agent
      - every agent named exists in config/agents.yaml and so has a budget and an allowlist
      - every human gate has a non-empty `expensive_because`

    ADR-0004: definitions live under `agent/core/`, owned by `fridaysup`. She reads and
    executes them; she does not write them. This function reads.

    Raises:
        GraphError: any of the above.
    """
    graphs_dir = _graphs_dir(root)
    module = _load_module(name, graphs_dir)
    graph = _extract_graph(name, module)
    _validate(graph, known_agents=_known_agents())
    return graph


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

def _new_run_id() -> str:
    return uuid.uuid4().hex[:16]


def _execute_node(graph: GraphDef, node_name: str, state: GraphState) -> GraphState:
    """Execute a single node, handling gates and checkpointing."""
    nd = graph.nodes[node_name]
    state.cursor = node_name
    state.updated_at = datetime.now()

    # If the node has a gate, raise it before executing.
    if nd.gate is not None:
        save(state)
        raise_gate(nd.gate, state.run_id, context=state.data)
        # After raise_gate, the run is WAITING. Return the parked state.
        return _cp_load(state.run_id)

    started_at = datetime.now()
    try:
        new_state = nd.fn(state)
        if new_state is None:
            new_state = state
        ended_at = datetime.now()
        # Record the node execution
        record = NodeRecord(
            node=node_name,
            started_at=started_at,
            ended_at=ended_at,
            agent=nd.agent,
            checked=nd.checks,
        )
        new_state.history.append(record)
        new_state.updated_at = datetime.now()
        # Checkpoint after every node
        save(new_state)
        return new_state
    except Exception as exc:
        # Record the error in the checkpoint
        ended_at = datetime.now()
        state.history.append(NodeRecord(
            node=node_name,
            started_at=started_at,
            ended_at=ended_at,
            agent=nd.agent,
            error=str(exc),
        ))
        state.status = RunStatus.FAILED
        save(state)
        raise


def _next_node(graph: GraphDef, current: str, state: GraphState) -> str | None:
    """Determine the next node after the current one."""
    targets = graph.edges.get(current, [])
    if not targets:
        return None  # terminal
    if len(targets) == 1:
        return targets[0]
    # Multi-way: check if the state has a routing key
    route_key = state.data.get("_route")
    if route_key and route_key in targets:
        return route_key
    # Default: first target
    return targets[0]


def run(name: str, inputs: Mapping[str, Any] | None = None) -> GraphState:
    """Start a run. Checkpoints after every node.

    Returns when the graph completes, parks at a gate, or is suspended. A parked run is not
    a failure and the returned state says which.

    Raises:
        GraphError: the definition is malformed.
    """
    graph = load_graph(name)
    init_db()

    run_id = _new_run_id()
    now = datetime.now()
    state = GraphState(
        run_id=run_id,
        graph=name,
        status=RunStatus.RUNNING,
        started_at=now,
        updated_at=now,
        cursor=graph.entry,
        data=dict(inputs) if inputs else {},
    )
    save(state)

    current = graph.entry
    while current is not None:
        state = _execute_node(graph, current, state)
        # If the run parked at a gate, return the WAITING state
        if state.status == RunStatus.WAITING:
            return state
        if state.status == RunStatus.FAILED:
            return state
        if state.status == RunStatus.SUSPENDED or state.status == RunStatus.KILLED:
            return state

        current = _next_node(graph, current, state)

    # Graph completed
    state.status = RunStatus.DONE
    state.updated_at = datetime.now()
    save(state)
    return state


def resume(run_id: str, amendment: Mapping[str, Any] | None = None) -> GraphState:
    """Resume a WAITING, SUSPENDED or KILLED run from its cursor.

    `amendment` merges into state before the cursor node re-enters. That is the path a
    barge-in `correction` takes (ADR-0019) and the path an `AMENDED` gate answer takes; they
    are the same operation from different surfaces.

    Resuming re-enters the cursor node rather than the one after it, so nodes must be
    idempotent. A node that appends to the vault and then dies would otherwise append twice
    on resume, which is the kind of bug that only appears after a kill.

    Raises:
        KeyError: no such run.
        GraphError: the graph definition is malformed.
    """
    state = _cp_load(run_id)

    if state.status not in (RunStatus.WAITING, RunStatus.SUSPENDED, RunStatus.KILLED,
                            RunStatus.PENDING):
        raise ValueError(
            f"run {run_id!r} is {state.status.value!r}; only WAITING, SUSPENDED, KILLED, "
            f"or PENDING runs can be resumed."
        )

    # Apply amendment
    if amendment:
        state.data.update(dict(amendment))

    # Reload the graph definition (validates again)
    graph = load_graph(state.graph)
    init_db()

    state.status = RunStatus.RUNNING
    state.suspended_for = None
    state.updated_at = datetime.now()
    save(state)

    # If the run was WAITING at a gate and the gate hasn't been answered yet,
    # it stays WAITING — resume should not re-execute a gated node until the
    # gate is answered. However, if the status was SUSPENDED/KILLED/PENDING,
    # we resume from the cursor.
    # The gate.answer() function transitions WAITING → PENDING before calling resume.
    # So if we reach here with status RUNNING (set above), we proceed.

    current = state.cursor
    while current is not None:
        # Skip the cursor node on first iteration if it already ran (idempotent re-entry
        # is the contract, so we DO re-enter it).
        state = _execute_node(graph, current, state)
        if state.status in (RunStatus.WAITING, RunStatus.FAILED,
                            RunStatus.SUSPENDED, RunStatus.KILLED):
            return state
        current = _next_node(graph, current, state)

    state.status = RunStatus.DONE
    state.updated_at = datetime.now()
    save(state)
    return state
