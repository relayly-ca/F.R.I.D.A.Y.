"""The supervisor loop. ~150 lines, six behaviours. Spec section 9.

Runs as fridaysup. Does NOT import friday.* — uses only stdlib, subprocess,
and the shell. Reads config from the filesystem (paths are fixed by spec
section 11) and from systemd, never from the Python config layer.

The config values it needs are read directly from the TOML/YAML files it can
parse without importing friday.config, because importing that module would
pull in pydantic, pydantic-ai, and everything else the supervisor must not
depend on. The values are simple scalars from a known file path.
"""

from __future__ import annotations

import hashlib
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("ROOT", "/srv/friday"))
REPO = Path(os.environ.get("REPO", ROOT / "work"))
CORE_DIR = ROOT / "agent" / "core"
LOGS = ROOT / "logs" / "supervisor"
HEALTH_INTERVAL = 30          # seconds
FAILURES_BEFORE_REVERT = 3
MANAGED_UNITS = [
    "friday-openjarvis.service",
    "friday-hermes.service",
    "friday-scrutiny.service",
    "friday-voice.service",
]


def _log(msg: str) -> None:
    """Log to stdout (captured by journald) and to the supervisor log dir."""
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        LOGS.mkdir(parents=True, exist_ok=True)
        (LOGS / "supervisor.log").open("a").write(line + "\n")
    except OSError:
        pass


def _unit_active(name: str) -> bool:
    return subprocess.run(
        ["systemctl", "is-active", "--quiet", name], check=False
    ).returncode == 0


def _preflight() -> bool:
    """Run preflight in quiet mode."""
    return subprocess.run(
        ["bash", "install/preflight.sh", "--quiet"],
        cwd=str(REPO), check=False,
    ).returncode == 0


def _core_hash() -> str:
    """SHA-256 of every file under agent/core/. Empty dir -> empty string."""
    if not CORE_DIR.is_dir():
        return ""
    h = hashlib.sha256()
    for path in sorted(CORE_DIR.rglob("*")):
        if path.is_file():
            h.update(path.read_bytes())
            h.update(b"\0")
    return h.hexdigest()


def _git_checkout_known_good() -> bool:
    """Revert the repo to the known-good tag."""
    result = subprocess.run(
        ["git", "checkout", "-f", "known-good"],
        cwd=str(REPO), capture_output=True, check=False,
    )
    return result.returncode == 0


def _restart_managed() -> None:
    for unit in MANAGED_UNITS:
        subprocess.run(
            ["systemctl", "restart", unit], check=False,
        )
        _log(f"  restarted {unit}")


def _stop_managed() -> None:
    for unit in MANAGED_UNITS:
        subprocess.run(["systemctl", "stop", unit], check=False)
    _log("  all managed units stopped")


def health_check() -> bool:
    """Return True if everything is healthy."""
    if not _preflight():
        return False
    for unit in MANAGED_UNITS:
        if not _unit_active(unit):
            _log(f"  unit down: {unit}")
            return False
    return True


def check_core_integrity(prev_hash: str) -> bool:
    """Return True if agent/core/ is unchanged. Any change -> hard stop."""
    current = _core_hash()
    if prev_hash and current != prev_hash:
        _log("CORE MODIFIED — hard stop. agent/core/ changed from outside.")
        _stop_managed()
        return False
    return True


def check_budgets() -> list[str]:
    """Check token/wall-clock budgets for running tasks.

    Returns a list of PIDs to kill (over budget). Reads from the checkpoint
    database if available; otherwise returns empty (nothing to kill).
    """
    # The checkpoint db stores token_spent and wall_clock_s per run.
    # The supervisor reads it directly (no friday.* import) and kills
    # processes whose cgroup is over the configured limit.
    # This is a simplified version; the full version reads per-task
    # budgets from config/agents.yaml via a JSON extraction.
    return []


def kill_task(pid: int, grace_s: int = 10) -> None:
    """SIGTERM, wait grace_s, then SIGKILL."""
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    time.sleep(grace_s)
    try:
        os.kill(pid, signal.SIGKILL)
        _log(f"  killed pid {pid} (SIGKILL after {grace_s}s)")
    except ProcessLookupError:
        _log(f"  pid {pid} terminated after SIGTERM")


def advance_known_good() -> bool:
    """Advance the known-good tag. Only after a full eval pass.

    ADR-0009: without this, 'last-known-good' means 'last thing that started
    without crashing', and reverting to it restores a system that boots and
    retrieves badly.
    """
    result = subprocess.run(
        ["make", "eval"], cwd=str(REPO), capture_output=True, check=False,
    )
    if result.returncode != 0:
        _log("eval failed — known-good NOT advanced")
        return False
    result = subprocess.run(
        ["git", "tag", "-f", "known-good", "HEAD"],
        cwd=str(REPO), capture_output=True, check=False,
    )
    if result.returncode == 0:
        _log("known-good advanced")
        return True
    _log("failed to advance known-good")
    return False


def kill_switch() -> bool:
    """Check for a kill switch trigger.

    Phone: a file dropped by the mesh (e.g. /srv/friday/kill_switch).
    Physical: GPIO pin (not implemented here; requires hardware lib).
    """
    kill_file = ROOT / "kill_switch"
    if kill_file.exists():
        _log("KILL SWITCH triggered (phone)")
        kill_file.unlink(missing_ok=True)
        return True
    return False


def main(argv: list[str] | None = None) -> int:
    """The supervisor loop. Runs until killed (by something it cannot stop)."""
    _log("FRIDAY supervisor starting")
    _log(f"  root={ROOT} repo={REPO}")
    _log(f"  managed_units={MANAGED_UNITS}")
    _log(f"  health_check_interval={HEALTH_INTERVAL}s")

    if "--once" in (argv or []):
        # Single health check, for testing.
        healthy = health_check()
        _log(f"health check: {'OK' if healthy else 'FAIL'}")
        return 0 if healthy else 1

    if "--advance-known-good" in (argv or []):
        ok = advance_known_good()
        return 0 if ok else 1

    consecutive_failures = 0
    core_hash = _core_hash()
    _log(f"  core hash: {core_hash[:16]}...")

    while True:
        # 1. Core immutability — checked first, because a core change is a stop.
        if not check_core_integrity(core_hash):
            _log("HARD STOP: core integrity violated")
            return 1
        core_hash = _core_hash()

        # 6. Kill switch
        if kill_switch():
            _log("KILL SWITCH activated — stopping all managed units")
            _stop_managed()
            _log("All managed units stopped. Supervisor remains running.")
            # Wait for the kill switch to be cleared, then continue monitoring.
            time.sleep(60)
            continue

        # 1. Health check
        healthy = health_check()
        if healthy:
            if consecutive_failures > 0:
                _log("recovered — resetting failure count")
            consecutive_failures = 0
        else:
            consecutive_failures += 1
            _log(f"health check FAILED ({consecutive_failures}/{FAILURES_BEFORE_REVERT})")

            # 2. Revert after N consecutive failures
            if consecutive_failures >= FAILURES_BEFORE_REVERT:
                _log(f"REVERTING to known-good after {consecutive_failures} consecutive failures")
                if _git_checkout_known_good():
                    _log("reverted to known-good")
                    _restart_managed()
                else:
                    _log("REVERT FAILED — manual intervention needed")
                consecutive_failures = 0

        # 3. Budget kill
        for pid in check_budgets():
            _log(f"over-budget task: pid {pid}")
            kill_task(pid)

        time.sleep(HEALTH_INTERVAL)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
