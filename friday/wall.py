"""FRIDAY wall surface. Spec section 1: "Agent state, running graphs, pending gates.
Renders; never commands."

A lightweight FastAPI dashboard. Renders agent state, system status, running
graphs, and pending human gates as JSON + a simple HTML page. The wall surface
NEVER sends commands — it renders. All commands go through the CLI or the
supervisor.

    uv run python -m friday.wall --port 8088
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

from friday.config import ConfigError, get
from friday.profile import active, active_name


def _system_state() -> dict[str, Any]:
    """Probe the box for current state. Works in both systemd and dev mode."""
    state: dict[str, Any] = {}

    # Services — try systemd first, then fall back to port probes for dev mode
    dev_pids = Path(os.environ.get("HOME", "/tmp")) / ".local/share/friday-dev/pids"
    dev_checks = {
        "friday-litellm": (4000, "litellm"),
        "friday-llama@daily": (8080, "llama-daily"),
        "friday-llama@fast": (8080, "llama-daily"),  # same process on dev
        "friday-hermes": (9119, None),   # Hermes dashboard
        "friday-supervisor": (None, "supervisor"),
    }
    for unit, (port, pid_name) in dev_checks.items():
        if port is not None:
            # Try port probe first (works in dev mode without systemd)
            try:
                import urllib.request
                req = urllib.request.Request(f"http://127.0.0.1:{port}/")
                urllib.request.urlopen(req, timeout=2)
                state[f"unit:{unit}"] = True
                continue
            except Exception:
                pass
        # Fall back to systemd
        if shutil.which("systemctl"):
            result = subprocess.run(
                ["systemctl", "is-active", "--quiet", unit], check=False,
            )
            state[f"unit:{unit}"] = result.returncode == 0
        else:
            state[f"unit:{unit}"] = False

    # Also probe services not in systemd (Qdrant, Hermes, Odysseus)
    for name, port in [("qdrant", 6333), ("hermes-dashboard", 9119), ("odysseus", 7000)]:
        try:
            import urllib.request
            req = urllib.request.Request(f"http://127.0.0.1:{port}/")
            urllib.request.urlopen(req, timeout=2)
            state[f"service:{name}"] = True
        except Exception:
            state[f"service:{name}"] = False

    # profile
    try:
        prof = active()
        state["profile"] = {
            "name": active_name(),
            "describe": prof.describe.strip(),
            "aliases": {k: v for k, v in prof.aliases.items()},
        }
    except Exception:
        state["profile"] = None

    # build tracker
    try:
        from friday.status import render
        state["stage"] = render()
    except Exception:
        state["stage"] = "unavailable"

    return state


def _agents() -> list[dict[str, Any]]:
    """Agent configs from config/agents.yaml."""
    try:
        cfg = get()
    except ConfigError:
        return []
    return [
        {
            "name": name,
            "model": spec.model,
            "max_tokens": spec.max_tokens,
            "wall_clock_s": spec.wall_clock_s,
            "temperature": spec.temperature,
            "sensitivity": spec.sensitivity.value,
            "can_write": spec.can_write,
            "tools": list(spec.tools),
        }
        for name, spec in sorted(cfg.agents.agents.items())
    ]


def _graphs() -> list[dict[str, Any]]:
    """Running and recent graph runs from the checkpoint db."""
    db = Path("/srv/friday/db/checkpoints.db")
    if not db.is_file():
        return []
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                """SELECT run_id, graph, status, started_at, updated_at,
                          tokens_spent, wall_clock_s, cursor
                   FROM runs ORDER BY updated_at DESC LIMIT 20"""
            ).fetchall()
            return [dict(r) for r in rows]
    except sqlite3.Error:
        return []


def _gates() -> list[dict[str, Any]]:
    """Pending human gates from the checkpoint db."""
    db = Path("/srv/friday/db/checkpoints.db")
    if not db.is_file():
        return []
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                """SELECT run_id, gate_name, summary, expensive_because, created_at
                   FROM gates WHERE status = 'waiting' ORDER BY created_at DESC"""
            ).fetchall()
            return [dict(r) for r in rows]
    except sqlite3.Error:
        return []


def _scrutiny_decisions() -> list[dict[str, Any]]:
    """Recent scrutiny decisions."""
    db = Path("/srv/friday/db/scrutiny.db")
    if not db.is_file():
        return []
    try:
        with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as c:
            c.row_factory = sqlite3.Row
            rows = c.execute(
                """SELECT decision_id, signal_id, rule, action, decided_at
                   FROM decisions ORDER BY decided_at DESC LIMIT 20"""
            ).fetchall()
            return [dict(r) for r in rows]
    except sqlite3.Error:
        return []


def _data() -> dict[str, Any]:
    """Everything the wall renders."""
    return {
        "timestamp": datetime.now().isoformat(),
        "system": _system_state(),
        "agents": _agents(),
        "graphs": _graphs(),
        "gates": _gates(),
        "scrutiny": _scrutiny_decisions(),
    }


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FRIDAY</title>
<style>
  :root { --bg: #0a0a0a; --fg: #e0e0e0; --dim: #666; --acc: #4a9; --warn: #e94; --err: #e44; --card: #1a1a1a; }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: var(--bg); color: var(--fg); font-family: -apple-system, system-ui, monospace; padding: 20px; }
  h1 { font-size: 1.4rem; margin-bottom: 4px; letter-spacing: 2px; }
  h2 { font-size: 0.9rem; color: var(--dim); margin: 24px 0 12px; text-transform: uppercase; letter-spacing: 1px; }
  .sub { color: var(--dim); font-size: 0.85rem; margin-bottom: 20px; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 12px; }
  .card { background: var(--card); border-radius: 8px; padding: 14px; }
  .card h3 { font-size: 0.95rem; margin-bottom: 8px; }
  .row { display: flex; justify-content: space-between; padding: 3px 0; font-size: 0.82rem; }
  .row .k { color: var(--dim); }
  .pill { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 0.75rem; font-weight: bold; }
  .up { background: #142; color: var(--acc); }
  .down { background: #311; color: var(--err); }
  .waiting { background: #331; color: var(--warn); }
  .ok { background: #142; color: var(--acc); }
  #refresh { float: right; }
  pre { font-size: 0.8rem; overflow-x: auto; color: var(--dim); white-space: pre-wrap; }
</style>
</head>
<body>
<div id="refresh"><button onclick="location.reload()" style="background:var(--card);color:var(--fg);border:1px solid var(--dim);padding:6px 16px;border-radius:6px;cursor:pointer">Refresh</button></div>
<h1>FRIDAY</h1>
<div class="sub" id="ts"></div>

<h2>Services</h2>
<div class="grid" id="services"></div>

<h2>Agents</h2>
<div class="grid" id="agents"></div>

<h2>Pending Gates</h2>
<div class="grid" id="gates"></div>

<h2>Recent Decisions</h2>
<div class="grid" id="scrutiny"></div>

<h2>Build Status</h2>
<pre id="stage"></pre>

<script>
const UP = (s) => `<span class="pill up">${s}</span>`;
const DOWN = (s) => `<span class="pill down">${s}</span>`;

async function load() {
  const r = await fetch('/api/state');
  const d = await r.json();
  document.getElementById('ts').textContent = d.timestamp;

  // Services
  const svc = d.system;
  let html = '';
  for (const [k, v] of Object.entries(svc)) {
    if (k.startsWith('unit:')) {
      const name = k.slice(5);
      html += `<div class="card"><h3>${name}</h3>${v ? UP('active') : DOWN('inactive')}</div>`;
    }
  }
  if (svc.profile) {
    html += `<div class="card"><h3>Profile: ${svc.profile.name}</h3><div class="row"><span class="k">desc</span><span>${svc.profile.describe}</span></div>`;
    for (const [a, m] of Object.entries(svc.profile.aliases)) {
      html += `<div class="row"><span class="k">${a}</span><span>${m || 'off'}</span></div>`;
    }
    html += '</div>';
  }
  document.getElementById('services').innerHTML = html;

  // Agents
  let ah = '';
  for (const a of d.agents) {
    ah += `<div class="card"><h3>${a.name}</h3>
      <div class="row"><span class="k">model</span><span>${a.model}</span></div>
      <div class="row"><span class="k">tokens</span><span>${a.max_tokens}</span></div>
      <div class="row"><span class="k">wall clock</span><span>${a.wall_clock_s}s</span></div>
      <div class="row"><span class="k">sensitivity</span><span>${a.sensitivity}</span></div>
      <div class="row"><span class="k">write</span><span>${a.can_write ? 'yes' : 'no'}</span></div>
      <div class="row"><span class="k">tools</span><span>${a.tools.join(', ') || 'none'}</span></div>
    </div>`;
  }
  document.getElementById('agents').innerHTML = ah;

  // Gates
  let gh = '';
  if (d.gates.length === 0) {
    gh = '<div class="sub">No pending gates</div>';
  } else {
    for (const g of d.gates) {
      gh += `<div class="card"><h3>${g.gate_name}</h3>
        <div class="row"><span class="k">run</span><span>${g.run_id}</span></div>
        <div class="row"><span class="k">summary</span><span>${g.summary}</span></div>
        <div class="row"><span class="k">because</span><span>${g.expensive_because}</span></div>
      </div>`;
    }
  }
  document.getElementById('gates').innerHTML = gh;

  // Scrutiny
  let sh = '';
  if (d.scrutiny.length === 0) {
    sh = '<div class="sub">No decisions logged yet</div>';
  } else {
    for (const s of d.scrutiny) {
      const cls = s.action === 'act' ? 'ok' : s.action === 'ask' ? 'waiting' : '';
      sh += `<div class="card"><h3><span class="pill ${cls}">${s.action}</span></h3>
        <div class="row"><span class="k">rule</span><span>${s.rule}</span></div>
        <div class="row"><span class="k">at</span><span>${s.decided_at}</span></div>
      </div>`;
    }
  }
  document.getElementById('scrutiny').innerHTML = sh;

  // Stage
  document.getElementById('stage').textContent = d.system.stage || '';
}

load();
setInterval(load, 5000);
</script>
</body>
</html>"""


def create_app():
    """Create the FastAPI app."""
    try:
        from fastapi import FastAPI
        from fastapi.responses import HTMLResponse, JSONResponse
    except ImportError:
        raise RuntimeError(
            "FastAPI not installed. Run: uv pip install fastapi uvicorn"
        )

    app = FastAPI(title="FRIDAY Wall", docs_url="/api/docs")

    @app.get("/", response_class=HTMLResponse)
    async def root():
        return HTML

    @app.get("/api/state")
    async def state():
        return _data()

    @app.get("/api/state/json")
    async def state_json():
        return JSONResponse(_data(), headers={"Content-Type": "application/json"})

    return app


def main() -> int:
    import sys

    port = 8088
    for i, arg in enumerate(sys.argv):
        if arg == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])

    try:
        import uvicorn
    except ImportError:
        print("uvicorn not installed. Run: uv pip install uvicorn fastapi")
        return 1

    app = create_app()
    print(f"FRIDAY wall surface on http://127.0.0.1:{port}")
    print("Renders; never commands. Spec section 1.")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
