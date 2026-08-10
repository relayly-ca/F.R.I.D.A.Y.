"""FRIDAY launchpad. The unified UI that connects everything.

Spec section 1: "Agent state, running graphs, pending gates. Renders; never commands."
This goes one step further — it links every component of the stack into one page,
so you see the whole system at a glance and can reach any surface in one click.

Components:
  - FRIDAY wall (this server)     :8088  — agents, gates, scrutiny, build status
  - Hermes Agent dashboard        :9119  — sessions, config, skills, gateways, memory
  - Odysseus workspace            :7000  — files, email, deep research, cookbook
  - LiteLLM proxy                 :4000  — model routing, aliases, fallbacks
  - Qdrant vectors                :6333  — collection state
  - llama.cpp servers             :8080/8082/8085 — GPU inference

The launchpad probes each one and shows green/red, then embeds or links to it.
It renders; never commands — same boundary as the wall.
"""

from __future__ import annotations

import json
import subprocess
import urllib.request
import urllib.error
from datetime import datetime
from typing import Any

from friday.config import ConfigError, get, repo_root
from friday.profile import active, active_name

# --- Component registry ------------------------------------------------------

COMPONENTS: list[dict[str, Any]] = [
    {
        "name": "FRIDAY Wall",
        "url": "http://127.0.0.1:8088",
        "api": "http://127.0.0.1:8088/api/state",
        "category": "friday",
        "describe": "Agents, gates, scrutiny decisions, build status",
        "embed": False,
    },
    {
        "name": "Hermes Dashboard",
        "url": "http://127.0.0.1:9119",
        "api": "http://127.0.0.1:9119/api/status",
        "category": "messaging",
        "describe": "Sessions, config, skills, gateways, memory, cron jobs",
        "embed": False,  # Hermes has its own auth, can't iframe
    },
    {
        "name": "Odysseus",
        "url": "http://127.0.0.1:7000",
        "api": None,  # Needs login
        "category": "workspace",
        "describe": "Files, email, deep research, hardware cookbook",
        "embed": False,  # Login wall
    },
    {
        "name": "LiteLLM Proxy",
        "url": "http://127.0.0.1:4000",
        "api": "http://127.0.0.1:4000/v1/models",
        "api_headers": {"Authorization": "Bearer sk-friday-dev-key-not-for-production"},
        "category": "inference",
        "describe": "Model routing, aliases, fallbacks, spend caps",
        "embed": False,
    },
    {
        "name": "Qdrant Vectors",
        "url": "http://127.0.0.1:6333",
        "api": "http://127.0.0.1:6333/collections",
        "category": "memory",
        "describe": "Vector index, collection state",
        "embed": False,
    },
    {
        "name": "llama.cpp :8080",
        "url": "http://127.0.0.1:8080",
        "api": "http://127.0.0.1:8080/health",
        "category": "inference",
        "describe": "daily + fast model (Qwen3-4B)",
        "embed": False,
    },
    {
        "name": "llama.cpp :8082",
        "url": "http://127.0.0.1:8082",
        "api": "http://127.0.0.1:8082/health",
        "category": "inference",
        "describe": "embed model (bge-m3)",
        "embed": False,
    },
    {
        "name": "llama.cpp :8085",
        "url": "http://127.0.0.1:8085",
        "api": "http://127.0.0.1:8085/health",
        "category": "inference",
        "describe": "rerank model (bge-reranker-v2-m3)",
        "embed": False,
    },
]


def _probe(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    """Probe a URL. Returns {ok, status, detail}."""
    try:
        req = urllib.request.Request(url, headers=headers or {})
        with urllib.request.urlopen(req, timeout=3) as resp:
            body = resp.read(4096).decode("utf-8", errors="replace")
            return {"ok": True, "status": resp.status, "detail": body[:200]}
    except urllib.error.HTTPError as e:
        return {"ok": e.code == 405, "status": e.code, "detail": f"HTTP {e.code}"}
    except urllib.error.URLError as e:
        return {"ok": False, "status": 0, "detail": str(e.reason)}
    except Exception as e:
        return {"ok": False, "status": 0, "detail": str(e)[:100]}


def _all_status() -> list[dict[str, Any]]:
    """Probe every component."""
    results = []
    for comp in COMPONENTS:
        r = {"name": comp["name"], "url": comp["url"], "describe": comp["describe"],
             "category": comp["category"], "embed": comp.get("embed", False)}
        if comp.get("api"):
            probe = _probe(comp["api"], comp.get("api_headers"))
            r.update(probe)
            # Parse model list for LiteLLM
            if comp["name"] == "LiteLLM Proxy" and probe["ok"]:
                try:
                    data = json.loads(probe["detail"] + "}]}")  # fix truncation
                except Exception:
                    pass
        else:
            r.update({"ok": None, "status": 0, "detail": "no probe (needs auth)"})
        results.append(r)
    return results


def _agents() -> list[dict[str, Any]]:
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
            "sensitivity": spec.sensitivity.value,
            "can_write": spec.can_write,
            "tools": list(spec.tools),
        }
        for name, spec in sorted(cfg.agents.agents.items())
    ]


def _data() -> dict[str, Any]:
    return {
        "timestamp": datetime.now().isoformat(),
        "components": _all_status(),
        "agents": _agents(),
    }


HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FRIDAY — Launchpad</title>
<style>
  :root { --bg: #08090a; --fg: #e8e8e8; --dim: #555; --acc: #5b9cf6; --warn: #e9a23b;
           --err: #e45757; --ok: #4ec9b0; --card: #161719; --border: #2a2b2d; }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { background: var(--bg); color: var(--fg);
         font-family: -apple-system, 'SF Pro Display', system-ui, monospace; padding: 20px 40px; }
  h1 { font-size: 1.6rem; letter-spacing: 4px; font-weight: 300; }
  .sub { color: var(--dim); font-size: 0.85rem; margin-bottom: 24px; }
  h2 { font-size: 0.75rem; color: var(--dim); margin: 28px 0 12px;
       text-transform: uppercase; letter-spacing: 2px; font-weight: 600; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 14px; }
  .card { background: var(--card); border: 1px solid var(--border); border-radius: 10px;
          padding: 16px; transition: border-color 0.2s; }
  .card:hover { border-color: var(--acc); }
  .card h3 { font-size: 1rem; margin-bottom: 4px; display: flex; align-items: center; gap: 8px; }
  .card .desc { color: var(--dim); font-size: 0.8rem; margin-bottom: 12px; }
  .row { display: flex; justify-content: space-between; padding: 2px 0; font-size: 0.78rem; }
  .row .k { color: var(--dim); }
  .dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
  .dot-ok { background: var(--ok); } .dot-err { background: var(--err); }
  .dot-warn { background: var(--warn); } .dot-unk { background: var(--dim); }
  .pill { display: inline-block; padding: 1px 6px; border-radius: 4px;
          font-size: 0.7rem; font-weight: 600; }
  .pill-ok { background: rgba(78,201,176,0.15); color: var(--ok); }
  .pill-err { background: rgba(228,87,87,0.15); color: var(--err); }
  .pill-warn { background: rgba(233,162,59,0.15); color: var(--warn); }
  a { color: var(--acc); text-decoration: none; }
  a:hover { text-decoration: underline; }
  .open-btn { display: inline-block; padding: 4px 12px; border: 1px solid var(--border);
              border-radius: 6px; font-size: 0.75rem; color: var(--acc); margin-top: 8px; }
  .open-btn:hover { background: var(--border); text-decoration: none; }
  iframe { width: 100%; height: 480px; border: 1px solid var(--border); border-radius: 8px;
           margin-top: 8px; }
  .cat-inference { border-left: 3px solid var(--acc); }
  .cat-memory { border-left: 3px solid var(--ok); }
  .cat-messaging { border-left: 3px solid #c586c0; }
  .cat-workspace { border-left: 3px solid #dcdcaa; }
  .cat-friday { border-left: 3px solid var(--warn); }
</style>
</head>
<body>
<h1>FRIDAY</h1>
<div class="sub" id="ts">Ambient AI launchpad — everything connected, everything local</div>

<h2>System Components</h2>
<div class="grid" id="components"></div>

<h2>Agents</h2>
<div class="grid" id="agents"></div>

<h2>FRIDAY Wall</h2>
<div id="wall-embed"></div>

<script>
const dot = (ok) => `<span class="dot ${ok===true?'dot-ok':ok===false?'dot-err':'dot-unk'}"></span>`;
const pill = (ok, text) => `<span class="pill ${ok===true?'pill-ok':ok===false?'pill-err':'pill-warn'}">${text}</span>`;

async function load() {
  const r = await fetch('/api/launchpad');
  const d = await r.json();
  document.getElementById('ts').textContent = d.timestamp + ' — Ambient AI launchpad';

  // Components
  let html = '';
  for (const c of d.components) {
    const cls = 'cat-' + c.category;
    const status = c.ok === true ? 'UP' : c.ok === false ? 'DOWN' : '?';
    html += `<div class="card ${cls}">
      <h3>${dot(c.ok)} ${c.name} ${pill(c.ok, status)}</h3>
      <div class="desc">${c.describe}</div>
      <div class="row"><span class="k">URL</span><a href="${c.url}" target="_blank">${c.url}</a></div>
      <div class="row"><span class="k">probe</span><span>${c.detail || ''}</span></div>`;
    if (c.embed) {
      html += `<iframe src="${c.url}" sandbox="allow-same-origin allow-scripts"></iframe>`;
    } else {
      html += `<a class="open-btn" href="${c.url}" target="_blank">Open ↗</a>`;
    }
    html += `</div>`;
  }
  document.getElementById('components').innerHTML = html;

  // Agents
  let ah = '';
  for (const a of d.agents) {
    ah += `<div class="card">
      <h3>${a.name}</h3>
      <div class="row"><span class="k">model</span><span>${a.model}</span></div>
      <div class="row"><span class="k">tokens</span><span>${a.max_tokens}</span></div>
      <div class="row"><span class="k">wall clock</span><span>${a.wall_clock_s}s</span></div>
      <div class="row"><span class="k">sensitivity</span><span>${a.sensitivity}</span></div>
      <div class="row"><span class="k">write</span><span>${a.can_write ? 'yes' : 'no'}</span></div>
      <div class="row"><span class="k">tools</span><span>${a.tools.join(', ') || 'none'}</span></div>
    </div>`;
  }
  document.getElementById('agents').innerHTML = ah;
}

load();
setInterval(load, 10000);
</script>
</body>
</html>"""


def create_app():
    try:
        from fastapi import FastAPI
        from fastapi.responses import HTMLResponse, JSONResponse
    except ImportError as exc:
        raise RuntimeError(f"FastAPI not installed: {exc}") from exc

    app = FastAPI(title="FRIDAY Launchpad", docs_url="/api/docs")

    @app.get("/", response_class=HTMLResponse)
    async def root():
        return HTML

    @app.get("/api/launchpad")
    async def launchpad():
        return _data()

    @app.get("/api/launchpad/json")
    async def launchpad_json():
        return JSONResponse(_data(), headers={"Content-Type": "application/json"})

    return app


def main() -> int:
    import sys

    port = 8090
    for i, arg in enumerate(sys.argv):
        if arg == "--port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])

    try:
        import uvicorn
    except ImportError:
        print("uvicorn not installed. Run: uv pip install uvicorn fastapi")
        return 1

    app = create_app()
    print(f"FRIDAY launchpad on http://127.0.0.1:{port}")
    print("Connects: Wall(:8088) + Hermes(:9119) + Odysseus(:7000) + LiteLLM(:4000) + Qdrant(:6333)")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
