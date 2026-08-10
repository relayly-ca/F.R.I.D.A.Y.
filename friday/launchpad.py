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

Tabs:
  - Overview: component status + agents (the original launchpad)
  - Chat: talk to FRIDAY directly through the LiteLLM proxy
  - Settings: view and change model aliases, profiles, agent configs, Hermes model
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import AsyncGenerator
from datetime import datetime
from pathlib import Path
from typing import Any

from friday.config import ConfigError, get, repo_root
from friday.profile import active, active_name

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
except ImportError:
    FastAPI = None  # type: ignore[assignment,misc]
    Request = None  # type: ignore[assignment,misc]
    HTMLResponse = None  # type: ignore[assignment,misc]
    JSONResponse = None  # type: ignore[assignment,misc]
    StreamingResponse = None  # type: ignore[assignment,misc]

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
        "api_headers": {"Authorization": "Bearer sk-1234"},
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
        r = {
            "name": comp["name"],
            "url": comp["url"],
            "describe": comp["describe"],
            "category": comp["category"],
            "embed": comp.get("embed", False),
        }
        if comp.get("api"):
            probe = _probe(comp["api"], comp.get("api_headers"))
            r.update(probe)
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
            "temperature": spec.temperature,
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


# --- Settings data ------------------------------------------------------------


def _dev_data_dir() -> Path:
    return Path(os.environ.get("HOME", "/tmp")) / ".local/share/friday-dev"


def _litellm_config_path() -> Path:
    return _dev_data_dir() / "litellm.yaml"


def _load_dev_litellm() -> dict[str, Any]:
    """Load the dev-mode LiteLLM config (the one actually running)."""
    import yaml

    p = _litellm_config_path()
    if not p.is_file():
        return {}
    return yaml.safe_load(p.read_text()) or {}


def _available_gguf_models() -> list[dict[str, str]]:
    """Scan the models directory for .gguf files."""
    models_dir = _dev_data_dir() / "models"
    if not models_dir.is_dir():
        return []
    out = []
    for f in sorted(models_dir.glob("*.gguf")):
        size_mb = f.stat().st_size / (1024 * 1024)
        out.append({"name": f.stem, "file": f.name, "size_mb": round(size_mb, 0)})
    return out


def _hermes_model() -> dict[str, Any]:
    """Read Hermes's current model configuration."""
    import yaml

    cfg_path = Path(os.environ.get("HOME", "/tmp")) / ".hermes/config.yaml"
    if not cfg_path.is_file():
        return {"available": False, "reason": "no config.yaml"}
    try:
        raw = yaml.safe_load(cfg_path.read_text()) or {}
    except Exception:
        return {"available": False, "reason": "config.yaml parse error"}
    model = raw.get("model", {})
    return {
        "available": True,
        "primary": model.get("model", "(not set)"),
        "provider": model.get("provider", "(not set)"),
        "base_url": model.get("base_url", ""),
        "api_key_env": model.get("api_key", ""),
        "fallback": raw.get("fallback_model", {}),
        "auxiliary": raw.get("auxiliary_models", {}),
    }


def _settings_data() -> dict[str, Any]:
    """Everything the settings tab needs."""
    # Active profile
    try:
        prof = active()
        prof_name = active_name()
        profile_info = {
            "name": prof_name,
            "describe": prof.describe.strip(),
            "aliases": dict(prof.aliases),
            "resident": list(prof.resident),
            "voice_default": prof.voice_default,
            "agent_overrides": dict(prof.agent_overrides),
        }
    except Exception as e:
        profile_info = {"name": "?", "describe": str(e), "aliases": {}, "resident": []}

    # Dev LiteLLM config (what's actually running)
    litellm_cfg = _load_dev_litellm()
    litellm_models = []
    for entry in litellm_cfg.get("model_list", []):
        litellm_models.append(
            {
                "alias": entry.get("model_name", ""),
                "model": entry.get("litellm_params", {}).get("model", ""),
                "api_base": entry.get("litellm_params", {}).get("api_base", ""),
                "timeout": entry.get("litellm_params", {}).get("timeout", ""),
            }
        )

    # Available GGUF models on disk
    gguf_models = _available_gguf_models()

    # Hermes model
    hermes = _hermes_model()

    # Agents
    agents = _agents()

    return {
        "profile": profile_info,
        "litellm_models": litellm_models,
        "gguf_models": gguf_models,
        "hermes": hermes,
        "agents": agents,
        "config_files": {
            "litellm_dev": str(_litellm_config_path()),
            "litellm_repo": str(repo_root() / "config" / "litellm.yaml"),
            "profiles": str(repo_root() / "config" / "profiles.yaml"),
            "agents": str(repo_root() / "config" / "agents.yaml"),
            "friday_toml": str(repo_root() / "config" / "friday.toml"),
            "hermes_config": str(Path(os.environ.get("HOME", "/tmp")) / ".hermes/config.yaml"),
        },
    }


# --- HTML --------------------------------------------------------------------

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

  /* Tabs */
  .tabs { display: flex; gap: 0; margin-bottom: 0; border-bottom: 1px solid var(--border); }
  .tab { padding: 10px 24px; cursor: pointer; color: var(--dim); font-size: 0.9rem;
         border-bottom: 2px solid transparent; transition: all 0.2s; }
  .tab:hover { color: var(--fg); }
  .tab.active { color: var(--acc); border-bottom-color: var(--acc); }
  .tab-panel { display: none; }
  .tab-panel.active { display: block; }

  /* Chat */
  #chat-box { display: flex; flex-direction: column; height: 70vh; }
  #chat-messages { flex: 1; overflow-y: auto; padding: 12px; background: var(--card);
                   border: 1px solid var(--border); border-radius: 8px; margin-bottom: 12px;
                   display: flex; flex-direction: column; gap: 10px; }
  .msg { max-width: 80%; padding: 10px 14px; border-radius: 12px; font-size: 0.88rem;
         line-height: 1.5; white-space: pre-wrap; word-break: break-word; }
  .msg-user { align-self: flex-end; background: rgba(91,156,246,0.15); border: 1px solid rgba(91,156,246,0.3); }
  .msg-friday { align-self: flex-start; background: var(--card); border: 1px solid var(--border); }
  .msg-system { align-self: center; color: var(--dim); font-size: 0.78rem; }
  .msg-error { align-self: center; color: var(--err); font-size: 0.78rem; }
  #chat-input-row { display: flex; gap: 10px; }
  #chat-input { flex: 1; background: var(--card); border: 1px solid var(--border);
                border-radius: 8px; padding: 12px 16px; color: var(--fg); font-size: 0.9rem;
                font-family: inherit; resize: none; }
  #chat-input:focus { outline: none; border-color: var(--acc); }
  #chat-send { padding: 12px 24px; background: var(--acc); color: #000; border: none;
               border-radius: 8px; cursor: pointer; font-size: 0.9rem; font-weight: 600; }
  #chat-send:hover { opacity: 0.9; }
  #chat-send:disabled { opacity: 0.4; cursor: not-allowed; }
  .chat-model-sel { background: var(--card); border: 1px solid var(--border); border-radius: 6px;
                    padding: 6px 10px; color: var(--fg); font-size: 0.8rem; margin-right: 8px; }

  /* Settings forms */
  .setting-row { display: flex; align-items: center; gap: 12px; padding: 8px 0;
                 border-bottom: 1px solid var(--border); }
  .setting-label { color: var(--dim); font-size: 0.8rem; min-width: 120px; }
  .setting-value { flex: 1; font-size: 0.82rem; }
  select, input[type="text"], input[type="number"] {
    background: var(--bg); border: 1px solid var(--border); border-radius: 6px;
    padding: 6px 10px; color: var(--fg); font-size: 0.82rem; font-family: inherit; }
  select:focus, input:focus { outline: none; border-color: var(--acc); }
  .save-btn { padding: 6px 16px; background: var(--acc); color: #000; border: none;
              border-radius: 6px; cursor: pointer; font-size: 0.8rem; font-weight: 600; }
  .save-btn:hover { opacity: 0.9; }
  .info-note { color: var(--dim); font-size: 0.75rem; margin-top: 6px; line-height: 1.5; }
  .config-path { font-family: monospace; font-size: 0.72rem; color: var(--dim);
                 word-break: break-all; }
</style>
</head>
<body>
<h1>FRIDAY</h1>
<div class="sub" id="ts">Ambient AI launchpad — everything connected, everything local</div>

<div class="tabs">
  <div class="tab active" onclick="showTab('overview')">Overview</div>
  <div class="tab" onclick="showTab('chat')">Chat</div>
  <div class="tab" onclick="showTab('settings')">Settings</div>
</div>

<!-- Overview tab -->
<div class="tab-panel active" id="tab-overview">
  <h2>System Components</h2>
  <div class="grid" id="components"></div>
  <h2>Agents</h2>
  <div class="grid" id="agents"></div>
</div>

<!-- Chat tab -->
<div class="tab-panel" id="tab-chat">
  <h2>Talk to FRIDAY</h2>
  <div id="chat-box">
    <div id="chat-messages"></div>
    <div id="chat-input-row">
      <select class="chat-model-sel" id="chat-model">
        <option value="daily">daily</option>
        <option value="fast">fast</option>
      </select>
      <textarea id="chat-input" rows="1" placeholder="Ask FRIDAY..." autofocus></textarea>
      <button id="chat-send" onclick="sendChat()">Send</button>
    </div>
  </div>
  <div class="info-note">Routes through LiteLLM (:4000) to llama.cpp. Same pipeline as <code>friday.cli ask</code>. Temporal context is injected automatically.</div>
</div>

<!-- Settings tab -->
<div class="tab-panel" id="tab-settings">
  <h2>Hardware Profile</h2>
  <div class="card" id="profile-card"></div>

  <h2>Model Aliases (LiteLLM — what's running)</h2>
  <div class="card" id="litellm-card"></div>
  <div class="info-note">
    These aliases are what every FRIDAY agent references. To swap a model, change what an alias points at here.
    Dev mode config lives at <span class="config-path" id="cfg-litellm"></span>. After changing, restart LiteLLM.
  </div>

  <h2>Available GGUF Models on Disk</h2>
  <div class="card" id="gguf-card"></div>

  <h2>Hermes Agent Model</h2>
  <div class="card" id="hermes-card"></div>
  <div class="info-note">
    This is the model Hermes Agent uses for itself (the agent you're talking to right now).
    Change with: <code>hermes model</code> or <code>hermes config set model.model &lt;name&gt;</code>.
    Config: <span class="config-path" id="cfg-hermes"></span>
  </div>

  <h2>Agents (config/agents.yaml)</h2>
  <div class="grid" id="agents-settings"></div>
  <div class="info-note">Agent budgets, tools, and sensitivity routing. Config: <span class="config-path" id="cfg-agents"></span></div>

  <h2>Config Files</h2>
  <div class="card" id="config-files-card"></div>
</div>

<script>
// --- Tab switching ---
function showTab(name) {
  document.querySelectorAll('.tab').forEach((t, i) => {
    t.classList.toggle('active', t.textContent.toLowerCase() === name);
  });
  document.querySelectorAll('.tab-panel').forEach(p => {
    p.classList.toggle('active', p.id === 'tab-' + name);
  });
  if (name === 'settings') loadSettings();
  if (name === 'chat') { loadChatModels(); document.getElementById('chat-input').focus(); }
}

// --- Status dots/pills ---
const dot = (ok) => `<span class="dot ${ok===true?'dot-ok':ok===false?'dot-err':'dot-unk'}"></span>`;
const pill = (ok, text) => `<span class="pill ${ok===true?'pill-ok':ok===false?'pill-err':'pill-warn'}">${text}</span>`;

// --- Overview load ---
async function loadOverview() {
  const r = await fetch('/api/launchpad');
  const d = await r.json();
  document.getElementById('ts').textContent = d.timestamp + ' — Ambient AI launchpad';

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

  let ah = '';
  for (const a of d.agents) {
    ah += `<div class="card">
      <h3>${a.name}</h3>
      <div class="row"><span class="k">model</span><span>${a.model}</span></div>
      <div class="row"><span class="k">tokens</span><span>${a.max_tokens}</span></div>
      <div class="row"><span class="k">wall clock</span><span>${a.wall_clock_s}s</span></div>
      <div class="row"><span class="k">temp</span><span>${a.temperature}</span></div>
      <div class="row"><span class="k">sensitivity</span><span>${a.sensitivity}</span></div>
      <div class="row"><span class="k">write</span><span>${a.can_write ? 'yes' : 'no'}</span></div>
      <div class="row"><span class="k">tools</span><span>${a.tools.join(', ') || 'none'}</span></div>
    </div>`;
  }
  document.getElementById('agents').innerHTML = ah;
}

// --- Chat ---
let chatModel = 'daily';
let chatBusy = false;

async function loadChatModels() {
  try {
    const r = await fetch('/api/settings');
    const d = await r.json();
    const sel = document.getElementById('chat-model');
    sel.innerHTML = '';
    for (const m of d.litellm_models) {
      const opt = document.createElement('option');
      opt.value = m.alias;
      opt.textContent = `${m.alias} (${m.model})`;
      sel.appendChild(opt);
    }
    sel.value = chatModel;
  } catch(e) {}
}

document.getElementById('chat-model').addEventListener('change', e => { chatModel = e.target.value; });

document.getElementById('chat-input').addEventListener('keydown', e => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
});

async function sendChat() {
  const input = document.getElementById('chat-input');
  const text = input.value.trim();
  if (!text || chatBusy) return;
  chatBusy = true;
  document.getElementById('chat-send').disabled = true;
  input.value = '';
  input.style.height = 'auto';

  addMsg('user', text);
  const fridayMsg = addMsg('friday', '');
  fridayMsg.innerHTML = '<span style="color:var(--dim)">thinking...</span>';

  try {
    const r = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: text, model: chatModel }),
    });

    if (!r.ok) {
      const err = await r.text();
      fridayMsg.innerHTML = '';
      addMsg('error', `Error: ${err}`);
      return;
    }

    const reader = r.body.getReader();
    const decoder = new TextDecoder();
    let content = '';
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\\n');
      buffer = lines.pop();
      for (const line of lines) {
        if (line.startsWith('data: ')) {
          const data = line.slice(6);
          if (data === '[DONE]') continue;
          try {
            const obj = JSON.parse(data);
            const delta = obj.choices?.[0]?.delta?.content || '';
            if (delta) {
              content += delta;
              fridayMsg.textContent = content;
            }
          } catch(e) {}
        }
      }
    }
    if (!content) fridayMsg.textContent = '(no response)';
  } catch(e) {
    fridayMsg.innerHTML = '';
    addMsg('error', `Connection error: ${e.message}`);
  } finally {
    chatBusy = false;
    document.getElementById('chat-send').disabled = false;
    scrollChat();
  }
}

function addMsg(role, text) {
  const msgs = document.getElementById('chat-messages');
  const div = document.createElement('div');
  div.className = 'msg msg-' + role;
  div.textContent = text;
  msgs.appendChild(div);
  scrollChat();
  return div;
}

function scrollChat() {
  const msgs = document.getElementById('chat-messages');
  msgs.scrollTop = msgs.scrollHeight;
}

// auto-grow textarea
const chatInput = document.getElementById('chat-input');
chatInput.addEventListener('input', () => {
  chatInput.style.height = 'auto';
  chatInput.style.height = Math.min(chatInput.scrollHeight, 150) + 'px';
});

// --- Settings ---
async function loadSettings() {
  try {
    const r = await fetch('/api/settings');
    const d = await r.json();
    renderProfile(d.profile);
    renderLiteLLM(d.litellm_models, d.gguf_models);
    renderGGUF(d.gguf_models);
    renderHermes(d.hermes);
    renderAgentsSettings(d.agents);
    renderConfigFiles(d.config_files);
  } catch(e) {
    document.getElementById('profile-card').innerHTML = `<div class="msg-error">Failed to load settings: ${e.message}</div>`;
  }
}

function renderProfile(p) {
  let html = `<h3>Profile: ${p.name}</h3>
    <div class="desc">${p.describe}</div>
    <div class="row"><span class="k">resident</span><span>${p.resident.join(', ') || 'none'}</span></div>
    <div class="row"><span class="k">voice default</span><span>${p.voice_default ? 'on' : 'off'}</span></div>
    <div class="row"><span class="k">agent overrides</span><span>${Object.keys(p.agent_overrides).length || 'none'}</span></div>
    <h3 style="margin-top:12px">Alias → Model mapping</h3>`;
  for (const [alias, model] of Object.entries(p.aliases)) {
    html += `<div class="row"><span class="k">${alias}</span><span>${model || '(not served)'}</span></div>`;
  }
  document.getElementById('profile-card').innerHTML = html;
}

function renderLiteLLM(models, gguf) {
  let html = '';
  for (const m of models) {
    html += `<div class="setting-row">
      <span class="setting-label">${m.alias}</span>
      <span class="setting-value">
        <select id="litellm-${m.alias}" onchange="markChanged('${m.alias}')">
          <option value="${m.model}">${m.model} (current)</option>`;
    for (const g of gguf) {
      if (g.name !== m.model) html += `<option value="${g.name}">${g.name}</option>`;
    }
    html += `</select>
      </span>
      <span class="setting-value" style="font-size:0.72rem;color:var(--dim)">${m.api_base}</span>
    </div>`;
  }
  html += `<div style="margin-top:12px"><button class="save-btn" onclick="saveLiteLLM()">Save & Restart LiteLLM</button></div>`;
  document.getElementById('litellm-card').innerHTML = html;
}

function renderGGUF(models) {
  if (!models.length) {
    document.getElementById('gguf-card').innerHTML = '<div class="desc">No .gguf files found in models directory</div>';
    return;
  }
  let html = '<div style="display:grid;grid-template-columns:1fr 80px 60px;gap:4px;font-size:0.8rem;">';
  html += '<div style="color:var(--dim)">Model</div><div style="color:var(--dim)">Size</div><div style="color:var(--dim)"></div>';
  for (const m of models) {
    html += `<div>${m.name}</div><div style="color:var(--dim)">${Math.round(m.size_mb)}MB</div><div></div>`;
  }
  html += '</div>';
  document.getElementById('gguf-card').innerHTML = html;
}

function renderHermes(h) {
  if (!h.available) {
    document.getElementById('hermes-card').innerHTML = `<div class="desc">Hermes config not readable: ${h.reason}</div>`;
    return;
  }
  let html = `<div class="row"><span class="k">model</span><span>${h.primary}</span></div>
    <div class="row"><span class="k">provider</span><span>${h.provider}</span></div>`;
  if (h.base_url) html += `<div class="row"><span class="k">base_url</span><span>${h.base_url}</span></div>`;
  if (h.fallback && h.fallback.provider) {
    html += `<div class="row"><span class="k">fallback</span><span>${h.fallback.provider}/${h.fallback.model || ''}</span></div>`;
  }
  html += `<div style="margin-top:8px"><a class="open-btn" href="http://127.0.0.1:9119" target="_blank">Open Hermes Dashboard ↗</a></div>`;
  document.getElementById('hermes-card').innerHTML = html;
}

function renderAgentsSettings(agents) {
  let ah = '';
  for (const a of agents) {
    ah += `<div class="card">
      <h3>${a.name}</h3>
      <div class="row"><span class="k">model alias</span><span>${a.model}</span></div>
      <div class="row"><span class="k">max tokens</span><span>${a.max_tokens}</span></div>
      <div class="row"><span class="k">wall clock</span><span>${a.wall_clock_s}s</span></div>
      <div class="row"><span class="k">temperature</span><span>${a.temperature}</span></div>
      <div class="row"><span class="k">sensitivity</span><span>${a.sensitivity}</span></div>
      <div class="row"><span class="k">can write</span><span>${a.can_write ? 'yes' : 'no'}</span></div>
      <div class="row"><span class="k">tools</span><span>${a.tools.join(', ') || 'none'}</span></div>
    </div>`;
  }
  document.getElementById('agents-settings').innerHTML = ah;
}

function renderConfigFiles(paths) {
  let html = '';
  for (const [name, path] of Object.entries(paths)) {
    html += `<div class="row"><span class="k">${name}</span><span class="config-path">${path}</span></div>`;
  }
  document.getElementById('config-files-card').innerHTML = html;
  if (paths.litellm_dev) document.getElementById('cfg-litellm').textContent = paths.litellm_dev;
  if (paths.hermes_config) document.getElementById('cfg-hermes').textContent = paths.hermes_config;
  if (paths.agents) document.getElementById('cfg-agents').textContent = paths.agents;
}

const changedAliases = new Set();
function markChanged(alias) { changedAliases.add(alias); }

async function saveLiteLLM() {
  const changes = {};
  for (const alias of changedAliases) {
    const sel = document.getElementById('litellm-' + alias);
    if (sel) changes[alias] = sel.value;
  }
  if (Object.keys(changes).length === 0) { alert('No changes to save.'); return; }
  if (!confirm('Save alias changes and restart LiteLLM?\\n\\n' + Object.entries(changes).map(([a,m]) => a + ' → ' + m).join('\\n'))) return;
  try {
    const r = await fetch('/api/settings/litellm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(changes),
    });
    const result = await r.json();
    if (r.ok) {
      alert('Done: ' + result.message);
      changedAliases.clear();
      loadSettings();
    } else {
      alert('Error: ' + result.error);
    }
  } catch(e) { alert('Error: ' + e.message); }
}

// --- Init ---
loadOverview();
setInterval(loadOverview, 10000);
</script>
</body>
</html>"""


def create_app():
    if FastAPI is None:
        raise RuntimeError("FastAPI not installed. Run: uv pip install fastapi uvicorn httpx")

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

    @app.get("/api/settings")
    async def settings():
        return _settings_data()

    @app.post("/api/settings/litellm")
    async def update_litellm(request: Request):
        """Update dev LiteLLM alias mappings and restart LiteLLM."""
        import yaml

        try:
            changes = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid JSON"}, status_code=400)

        if not isinstance(changes, dict) or not changes:
            return JSONResponse({"error": "no changes provided"}, status_code=400)

        cfg_path = _litellm_config_path()
        if not cfg_path.is_file():
            return JSONResponse(
                {"error": f"dev LiteLLM config not found: {cfg_path}"}, status_code=404
            )

        try:
            cfg = yaml.safe_load(cfg_path.read_text()) or {}
        except Exception as e:
            return JSONResponse({"error": f"config parse error: {e}"}, status_code=500)

        updated = []
        for entry in cfg.get("model_list", []):
            alias = entry.get("model_name")
            if alias in changes:
                new_model = changes[alias]
                old_model = entry.get("litellm_params", {}).get("model", "")
                # Preserve the openai/ prefix
                if not new_model.startswith("openai/"):
                    new_model = f"openai/{new_model}"
                entry["litellm_params"]["model"] = new_model
                updated.append(f"{alias}: {old_model} → {new_model}")

        if not updated:
            return JSONResponse({"error": "no matching aliases found to update"}, status_code=400)

        # Write back
        cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False, default_flow_style=False))
        return JSONResponse(
            {"message": f"Updated: {'; '.join(updated)}. Restart LiteLLM to apply."}
        )

    @app.post("/api/chat")
    async def chat(request: Request):
        """Stream a chat completion through LiteLLM to FRIDAY."""
        import httpx

        try:
            body = await request.json()
        except Exception:
            return JSONResponse({"error": "invalid json"}, status_code=400)

        message = body.get("message", "").strip()
        model = body.get("model", "daily")
        if not message:
            return JSONResponse({"error": "no message"}, status_code=400)

        # Inject temporal context (same as friday.cli ask)
        try:
            from friday.temporal import inject_context

            system_content = inject_context()
        except Exception:
            system_content = ""

        litellm_url = "http://127.0.0.1:4000/v1/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_content},
                {"role": "user", "content": message},
            ],
            "max_tokens": 4000,
            "temperature": 0.7,
            "stream": True,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer sk-1234",
        }

        async def stream() -> AsyncGenerator[str, None]:
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
                    async with client.stream(
                        "POST", litellm_url, json=payload, headers=headers
                    ) as resp:
                        if resp.status_code != 200:
                            err_body = await resp.aread()
                            yield f"data: {json.dumps({'error': err_body.decode('utf-8', errors='replace')})}\\n\\n"
                            return
                        async for line in resp.aiter_lines():
                            if line.startswith("data: "):
                                yield line + "\\n"
                        yield "data: [DONE]\\n\\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\\n\\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

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
    print(
        "Connects: Wall(:8088) + Hermes(:9119) + Odysseus(:7000) + LiteLLM(:4000) + Qdrant(:6333)"
    )
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
