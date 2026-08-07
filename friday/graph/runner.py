"""The executor. ADR-0012.

Runs a graph, checkpointing after every node, and resumes one from its cursor.

It enforces the two rules from ADR-0013 rather than documenting them, because a rule that
lives only in prose is one a tired evening removes:

  - a node declaring `writes=True` must be immediately preceded by a checker node
  - that checker must run as a DIFFERENT agent than the writer

Both are checked when the graph is loaded, not when the write happens. A graph that would
write unchecked fails at startup, which is the only time anyone is looking.

Implemented in W5.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from friday.graph.state import GraphState


class GraphError(Exception):
    """Raised when a graph definition is malformed or violates an invariant.

    Never raised for a node failing at runtime - that is a run outcome, recorded in the
    checkpoint. This means the definition itself is wrong.
    """


def load_graph(name: str, root: Path | None = None) -> Any:
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
        NotImplementedError: W5.
    """
    raise NotImplementedError("friday.graph.runner.load_graph is implemented in W5")


def run(name: str, inputs: Mapping[str, Any] | None = None) -> GraphState:
    """Start a run. Checkpoints after every node.

    Returns when the graph completes, parks at a gate, or is suspended. A parked run is not
    a failure and the returned state says which.

    Raises:
        GraphError: the definition is malformed.
        NotImplementedError: W5.
    """
    raise NotImplementedError("friday.graph.runner.run is implemented in W5")


def resume(run_id: str, amendment: Mapping[str, Any] | None = None) -> GraphState:
    """Resume a WAITING, SUSPENDED or KILLED run from its cursor.

    `amendment` merges into state before the cursor node re-enters. That is the path a
    barge-in `correction` takes (ADR-0019) and the path an `AMENDED` gate answer takes; they
    are the same operation from different surfaces.

    Resuming re-enters the cursor node rather than the one after it, so nodes must be
    idempotent. A node that appends to the vault and then dies would otherwise append twice
    on resume, which is the kind of bug that only appears after a kill.

    Raises:
        NotImplementedError: W5.
    """
    raise NotImplementedError("friday.graph.runner.resume is implemented in W5")
