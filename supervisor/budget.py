"""Budget enforcement. Spec section 9.

The supervisor reads per-task budgets from config/agents.yaml (without importing
friday.config) and checks live token spend from the checkpoint database. Over-
budget tasks get SIGTERM, a grace period, then SIGKILL.

Keeps to ~30 lines. The actual kill is in supervisor.main.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT = Path("/srv/friday")
AGENTS_YAML = ROOT / "work" / "config" / "agents.yaml"
CHECKPOINT_DB = ROOT / "db" / "checkpoints.db"
EPISODIC_DB = ROOT / "db" / "episodic.db"


def read_budgets() -> dict[str, dict[str, int]]:
    """Read per-agent max_tokens and wall_clock_s from config/agents.yaml.

    Uses yaml directly rather than importing friday.config, because the supervisor
    must not depend on the codebase it polices.
    """
    try:
        import yaml
    except ImportError:
        return {}

    path = ROOT / "work" / "config" / "agents.yaml"
    if not path.is_file():
        path = Path(__file__).resolve().parents[1] / "config" / "agents.yaml"
    if not path.is_file():
        return {}

    data = yaml.safe_load(path.read_text()) or {}
    agents = data.get("agents", {})
    return {
        name: {
            "max_tokens": spec.get("max_tokens", 0),
            "wall_clock_s": spec.get("wall_clock_s", 0),
        }
        for name, spec in agents.items()
    }


def over_budget_pids() -> list[int]:
    """Return PIDs of tasks that have exceeded their token or wall-clock budget.

    Reads the checkpoint database for running tasks and compares against
    config/agents.yaml budgets. The checkpoint stores tokens_spent and
    wall_clock_s per run, plus the agent name.
    """
    budgets = read_budgets()
    if not budgets or not CHECKPOINT_DB.is_file():
        return []

    over = []
    try:
        with sqlite3.connect(f"file:{CHECKPOINT_DB}?mode=ro", uri=True) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                """SELECT run_id, agent, tokens_spent, wall_clock_s, pid
                   FROM runs WHERE status = 'running'""",  # noqa: S608
            ).fetchall()
    except sqlite3.Error:
        return []

    for row in rows:
        agent = row["agent"]
        if agent not in budgets:
            continue
        budget = budgets[agent]
        if row["tokens_spent"] > budget["max_tokens"]:
            over.append(row["pid"])
        elif row["wall_clock_s"] > budget["wall_clock_s"]:
            over.append(row["pid"])

    return over
