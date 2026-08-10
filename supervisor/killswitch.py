"""The kill switch. Spec section 9: from your phone plus a physical button.

The phone path must NOT depend on Hermes, OpenJarvis, or the model being healthy.
The whole point of a kill switch is that it works when everything else has stopped
working. It is handled by the supervisor, not by the agent — a kill switch routed
through the thing it kills is not a kill switch.

    uv run python -m supervisor.killswitch --test     # simulate a trigger
    uv run python -m supervisor.killswitch --clear    # clear the trigger
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path("/srv/friday")
KILL_FILE = ROOT / "kill_switch"


def is_triggered() -> bool:
    return KILL_FILE.exists()


def trigger() -> None:
    """Drop the kill switch file. The supervisor's next loop will catch it."""
    KILL_FILE.parent.mkdir(parents=True, exist_ok=True)
    KILL_FILE.write_text("triggered\n")
    print(f"Kill switch triggered at {KILL_FILE}")


def clear() -> None:
    KILL_FILE.unlink(missing_ok=True)
    print(f"Kill switch cleared at {KILL_FILE}")


def main(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv[1:]
    if "--test" in argv:
        trigger()
        print("The supervisor will stop all managed units on its next health check.")
        print("Run with --clear to reset.")
        return 0
    if "--clear" in argv:
        clear()
        return 0
    if is_triggered():
        print("Kill switch is currently TRIGGERED.")
        return 0
    print("Kill switch is clear.")
    print("Usage: python -m supervisor.killswitch [--test | --clear]")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
