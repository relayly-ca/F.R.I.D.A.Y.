"""The workflow graph. ADR-0012, and a row in the stack table that spec section 1 lacks.

Scrutiny decides whether a signal is worth acting on and then stops. Nothing else owned
**how the work then moves** - the multi-step shape with checks between steps, handoffs,
loops and human approvals - so it was going to accrete as ad-hoc Python across
`friday/loops/`, differently each time.

A graph is jobs connected by arrows with shared state moving between them.

`pydantic_graph` types the nodes, the edges and the state; edges are inferred from a node's
`run()` return annotation. This package adds the three things it does not provide:

    checkpoint.py   position saved after every node
    runner.py       resumption, so a supervisor kill resumes rather than restarts
    gate.py         the human gate, which IS scrutiny's `ask` and not a second inbox

Two rules bind every graph and both are enforced rather than remembered:

**The writer is never the checker** (ADR-0013). A node that writes to the vault or the index
has a distinct checker in front of it, run by a different agent. A single model grading its
own answer inflates its confidence, reliably.

**The smallest graph that raises quality.** A graph per loop, not a graph per system. An
oversized graph is harder to reason about than the code it replaced, and legibility is the
entire point of the layer.

Graph DEFINITIONS live in `/srv/friday/agent/core/graphs/`, owned by `fridaysup`. ADR-0004:
she writes skills, tools, prompts and configs, never the loop that runs them - and a graph
is a loop that runs things. This package is the engine; it is not where the graphs live.

Implemented in W5 (docs/weeks/W5.md step 5).
"""

from friday.graph.gate import GateDecision, HumanGate
from friday.graph.state import GraphState, NodeRecord, RunStatus

__all__ = ["GraphState", "NodeRecord", "RunStatus", "HumanGate", "GateDecision"]
