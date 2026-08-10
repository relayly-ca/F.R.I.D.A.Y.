"""The human gate. ADR-0012, and it is deliberately not a new concept.

A graph that needs approval raises scrutiny's `ask`, through the same dispatch, into the same
inbox, under the same `ask_expires: false`. There is exactly ONE place a human is asked.

The alternative - a graph-local approval queue - is the thing to refuse. Two inboxes means
two places to check, two notification paths, and eventually one of them grows a timeout
"for convenience", at which point the system acts because you did not answer in time. Spec
section 4 and config/scrutiny.yaml are explicit: `ask` goes to the inbox and stays there,
and there is no configuration key that changes it.

Place the gate where mistakes get expensive. A gate on every node is a system you click
through without reading, which is worse than no gate at all.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from friday.graph.checkpoint import load as _cp_load
from friday.graph.checkpoint import save
from friday.graph.state import RunStatus


class GateDecision(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    AMENDED = "amended"


@dataclass(frozen=True)
class HumanGate:
    """A point in a graph where a person decides.

    Attributes:
        name: Stable identifier, recorded in the checkpoint and the inbox item.
        summary: What is being approved, in one line, written for someone who is not
            currently thinking about this graph. Most gates are read on a phone.
        expensive_because: Why this gate exists. If you cannot write this sentence, the gate
            is probably in the wrong place.
    """

    name: str
    summary: str
    expensive_because: str


def _dispatch_ask(gate: HumanGate, run_id: str, context: Mapping[str, Any] | None) -> None:
    """Dispatch an ask through scrutiny, not through a graph-local queue.

    Scrutiny's dispatch lands in week 7. Before that, this function is structured to call it
    when available, and to record the intent otherwise. The contract is: the ask goes to
    the same inbox, under the same ``ask_expires: false``, and there is no second queue.
    """
    payload = {
        "kind": "ask",
        "source": "graph",
        "gate": gate.name,
        "run_id": run_id,
        "summary": gate.summary,
        "expensive_because": gate.expensive_because,
        "context": dict(context) if context else {},
        "ask_expires": False,
    }
    # Try scrutiny's dispatch. It lands in W7 (scrutiny.daemon). Before that, the ask is
    # recorded by the checkpoint alone, which is sufficient for testing the gate logic.
    try:
        from scrutiny.daemon import dispatch_ask  # W7
        dispatch_ask(payload)
    except ImportError:
        # Scrutiny's dispatch is not yet implemented. The run is already checkpointed as
        # WAITING, so the position is safe. A W7 wiring replaces this branch with the real
        # dispatch and nothing else changes.
        pass


def raise_gate(
    gate: HumanGate,
    run_id: str,
    context: Mapping[str, Any] | None = None,
) -> None:
    """Park the run and raise an `ask`. Does not block a thread.

    Contract:
      - Checkpoints the run as WAITING at the current cursor before the ask is raised. A gate
        that asks first and checkpoints second loses the run if the process dies between.
      - Dispatches through scrutiny, not through a graph-local queue.
      - Never returns a decision. The answer arrives later and resumes the run.
    """
    # 1. Load the current state and mark it WAITING at the cursor.
    state = _cp_load(run_id)
    state.status = RunStatus.WAITING
    state.suspended_for = f"gate:{gate.name}"
    # The cursor stays where it is — resume re-enters the cursor node (idempotency).
    # Record the gate in state data so the answer can find context.
    state.data.setdefault("_gates", [])
    state.data["_gates"].append({
        "name": gate.name,
        "summary": gate.summary,
        "expensive_because": gate.expensive_because,
        "context": dict(context) if context else {},
        "status": "pending",
    })

    # 2. Checkpoint BEFORE dispatching the ask.
    save(state)

    # 3. Dispatch the ask through scrutiny.
    _dispatch_ask(gate, run_id, context)


def answer(run_id: str, decision: GateDecision, amendment: Mapping[str, Any] | None = None) -> None:
    """Record a human decision and resume the run.

    `AMENDED` carries changed state - the same path a barge-in `correction` takes (ADR-0019),
    which is deliberate: "no, the other Sam" and editing a field in the inbox are the same
    operation arriving through different surfaces.
    """
    state = _cp_load(run_id)
    if state.status != RunStatus.WAITING:
        raise ValueError(
            f"run {run_id!r} is {state.status.value!r}, not WAITING. Only a parked run can "
            f"be answered."
        )

    # Record the decision in the gate's history entry.
    gates = state.data.get("_gates", [])
    if gates:
        gates[-1]["status"] = decision.value
        gates[-1]["amendment"] = dict(amendment) if amendment else {}

    # Apply amendment to state data if provided.
    if amendment and decision == GateDecision.AMENDED:
        state.data.update(dict(amendment))

    if decision == GateDecision.REJECTED:
        # A rejected gate fails the run. The run does not resume.
        state.status = RunStatus.FAILED
        state.suspended_for = f"gate_rejected:{gates[-1]['name'] if gates else 'unknown'}"
    else:
        # APPROVED or AMENDED: the run is resumable from its cursor.
        state.status = RunStatus.PENDING
        state.suspended_for = None

    save(state)
