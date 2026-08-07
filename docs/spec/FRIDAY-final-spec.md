# FRIDAY — final build spec

A fully local, always-on ambient AI. One layer per job, nothing redundant.

Every component below is either open source or source-available, runs on your hardware, and
sends nothing to anyone else's server.

---

## 0. The rule that shapes everything

**One owner per layer.** The failure mode of this project is installing four things that each
do 60% of the job and spending your weekends reconciling them. Every layer below has exactly
one owner. Everything else got cut, and section 3 says why.

---

## 1. The stack

| Layer | Owner | License | Why it wins the slot |
|---|---|---|---|
| Inference | llama.cpp + vLLM | MIT / Apache | Standard. vLLM only when you need throughput |
| Model routing | LiteLLM | MIT | One endpoint, aliases, fallback, spend caps |
| **Agent runtime** | **OpenJarvis** | Apache 2.0 | Local-first by design, DSPy skill optimization, scheduled + continuous agents |
| **Messaging + user model** | **Hermes Agent** | MIT | 23 gateways from one process, Honcho user modeling, bounded memory, skill Curator |
| **Proactive triage** | **Adaptive Scrutiny pattern** | see §4 | The decision layer no other project ships |
| **Autonomous coding** | **OpenHands** | MIT | 72% SWE-bench, sandboxed Docker, 100+ providers via Ollama |
| Workspace UI | Odysseus | AGPL-3.0 | Cookbook hardware matching, files, email, deep research |
| Ambient dashboard | Home Assistant | Apache 2.0 | Wall display, voice satellites, presence, IoT |
| STT | faster-whisper large-v3-turbo | MIT | |
| Wake | openWakeWord + clap detect | Apache 2.0 | Two triggers, see §5 |
| Speaker auth | Resemblyzer voiceprint | MIT | Voice as an auth factor, not just input |
| TTS | Kokoro-82M / Chatterbox-Turbo | Apache 2.0 / MIT | Fast default, cloned voice when it matters |
| Vectors | Qdrant | Apache 2.0 | |
| Structured | SQLite + FTS5 | Public domain | |
| Messages in | Matrix (Conduit) + mautrix bridges | Apache / AGPL | The whole answer to "it knows my messages" |
| Calendar | Radicale + DAVx5 | GPL-3.0 | |
| Mail | mbsync + notmuch | GPL | |
| Tracing | Langfuse | MIT | You will need this at 3am |
| Git | Forgejo | MIT | Agent branches, human merges |
| Secrets | age + sops | MIT / Apache | |
| Network | Headscale or WireGuard | BSD / GPL | Never a port forward |
| Supervisor | ~150 lines you write | yours | The only thing outside the agent's reach |

### Models

| VRAM | Daily driver | Notes |
|---|---|---|
| 12–16 GB | Gemma 4 12B @ Q4 | Works, weak on long agentic chains |
| 16 GB | Devstral-2 22B @ Q4 | Best agentic model in a small footprint |
| **24 GB** | **Qwen 3.6 27B @ Q4** | The sweet spot |
| 32 GB | Qwen3.6-35B-A3B | MoE, fast for its size |
| 48 GB | Qwen3-Coder-Next | Or 27B + concurrent background workers |
| 128 GB | gpt-oss-120b | Apache 2.0, excellent tool calling |

Always resident (~6 GB): Qwen3 4B router · bge-m3 embeddings · bge-reranker-v2-m3 ·
faster-whisper · Kokoro.

Verify current picks before downloading. Odysseus's Cookbook will scan your hardware and
recommend.

---

## 2. Who owns what

```
        ┌──────────── SURFACES ────────────┐
        │  Matrix · Voice · HA wall · Web  │
        └────────────────┬─────────────────┘
                         │
     ┌───────────────────▼───────────────────┐
     │  HERMES — gateways, user model         │
     │  23 channels, Honcho, bounded memory   │
     └───────────────────┬───────────────────┘
                         │
     ┌───────────────────▼───────────────────┐
     │  SCRUTINY — 7-axis triage (yours)      │
     │  act · ask · watch · ignore · propagate│
     └───────┬───────────────────────┬───────┘
             │                       │
   ┌─────────▼─────────┐   ┌─────────▼─────────┐
   │ OPENJARVIS        │   │ OPENHANDS         │
   │ scheduled agents  │   │ bounded coding    │
   │ continuous monitor│   │ sandboxed, branch │
   │ skill optimizer   │   └───────────────────┘
   └─────────┬─────────┘
             │
   ┌─────────▼──────────────────────────────┐
   │  MEMORY — vault · SQLite · Qdrant      │
   └─────────▲──────────────────────────────┘
             │
   ┌─────────┴──────────────────────────────┐
   │  SENSES — Matrix db · CalDAV · notmuch │
   │  files · browser · Home Assistant      │
   └────────────────────────────────────────┘

  LiteLLM sits beside all of it. Supervisor sits above all of it.
```

---

## 3. What we cut, and why

Being explicit so you don't re-litigate this at 2am.

| Cut | Reason |
|---|---|
| **OpenClaw** | Redundant with Hermes for gateways; Hermes has the better memory architecture. Its 13,700-skill library is importable into OpenJarvis anyway — you get the value without the second daemon |
| **Khoj** | Its job is document RAG. OpenJarvis `deep_research` plus your own vault covers it |
| **Jan / AnythingLLM / LibreChat / Open WebUI** | All chat frontends. Odysseus is one, and does more |
| **Open Interpreter / Self-Operating Computer** | Code execution without memory or a permission model. OpenHands is strictly better |
| **Leon** | Dated architecture, small ecosystem |
| **PicoClaw** | A lighter Hermes. You already have Hermes |
| **LittleBird** | $12/mo, data on their infrastructure. Fails the requirement |
| **Azaris / AgentCore** | Cloud SaaS, business-ops focus |
| **cc-hermes-cc** | Every layer is a cloud API. Steal the UX ideas (§5), not the code |
| **harry-ai** | macOS-only, cloud STT by default. Steal the speaker ID (§5) |
| **Omi** | Only if you decide you want an ambient wearable |
| **Paid courses** | Repackaged free docs |

---

## 4. Adaptive Scrutiny — the layer nobody ships

This is the answer to "how does it decide what's worth acting on." OpenAGI is the only
project that ships it, and the design is worth copying exactly.

**Every incoming signal** — a message, a calendar change, an observed pattern, the end of a
brainstorm session — gets scored on seven axes:

```
urgency · impact · novelty · risk · confidence · specificity · conflict
```

Then the agent picks one of five actions:

| Action | Meaning |
|---|---|
| `act` | Do it now, report after |
| `ask` | Surface it, wait for you |
| `watch` | Not yet — re-evaluate on new information |
| `ignore` | Below threshold, log and drop |
| `propagate` | Hand to a bounded specialist |

Why this matters more than it sounds: scoring rejects low-value signals **before the
expensive model is invoked**. That's the difference between an assistant that pings you
forty times a day and one you trust. It's also cheap — the 4B router does the scoring.

### Licensing decision

OpenAGI is **PolyForm Noncommercial** — source-available, not open source. For personal use
that's fine and you can run it directly. If you want the stack license-clean, implement the
pattern yourself: it's a scoring prompt, a threshold table, and a dispatch switch. Maybe 200
lines. The design is the valuable part, not the code.

### Sourcing caveat

Nearly all the coverage praising OpenAGI comes from one blog that ranks it first in every
comparison it publishes. That's content marketing, same as the Vellum posts earlier. Judge
the repo and the license, not the write-ups.

---

## 5. Ideas worth stealing from small projects

Four things from projects too small to build on, each solving a real problem:

**Speaker ID as an auth gate** (from harry-ai). Resemblyzer voiceprint enrollment — read ten
prompts once, then the listener rejects any voice below a cosine threshold. For an always-on
agent with shell access, this is a real security control: without it, anyone in your house
can say the wake word and command your system. Add it to the security layer.

**Clap-to-wake** (from cc-hermes-cc). Two claps via Web Audio, then continuous listening
until you say "ok" to return to standby. Physically cannot false-trigger from speech, unlike
a wake word. Run both — wake word for hands-busy, clap for across-the-room.

**AI-chosen output surface** (from cc-hermes-cc). The model decides *where* the answer goes:
system questions answered by voice with no window, "where is X" opens a map tile, "show me
X" opens images, data questions render a chart. Close by voice. This is the right
interaction model for a wall display.

**Reactive status visualization** (from cc-hermes-cc). Their 3D brain lights up the specific
regions being consulted, then fires on completion. Functional progress indication disguised
as spectacle. Whatever your dashboard looks like, make the visual reflect actual agent state.

---

## 6. Build order

| Week | Do | Done when |
|---|---|---|
| 1 | llama.cpp + LiteLLM + **OpenJarvis** one-line install, `--preset chat-simple` | You chat locally |
| 1 | Conduit + mautrix bridges + Hermes gateway | You text FRIDAY from your phone |
| 2 | Radicale + DAVx5; ingest Matrix db + calendar | She answers "what's my week look like" |
| 2–3 | Memory: vault, Qdrant, FTS5, reranker, **eval set** | 20/25 on your own eval questions |
| 3 | OpenJarvis `monitor_operative` + `morning_digest` | Vault grows without you writing in it |
| 4 | notmuch, files, browser, Home Assistant | Eval score holds after each new source |
| 4–5 | Voice: Whisper → Kokoro, wake word + clap, speaker ID | Under 800ms, hands-free, voice-gated |
| 5 | MCP tools, OpenHands sandbox, **supervisor** | She can act, and you can kill her |
| 6 | Mode detection + brainstorm behavior | She shuts up and takes notes on command |
| 7 | **Adaptive Scrutiny** + bounded specialists | She works overnight, reports at breakfast |
| 8+ | `jarvis optimize skills --policy dspy` + Hermes Curator | Her skills improve measurably, not just numerously |

**Do not reorder.** Voice before memory is the mistake everyone makes. Week 2–3 is the
least exciting and the most load-bearing.

---

## 7. Memory

Four tiers, unchanged from the earlier plan because it's right:

1. **`profile.md`** — hand-written by you, ~1500 tokens, injected into every prompt. Hermes's
   Honcho user model feeds proposals into it; you approve them.
2. **Episodic log** — `episodic.db`, append-only, never edited, only compressed.
3. **Vault** — markdown. `daily/` `projects/` `people/` `ideas/`. Written by the
   consolidation loop, editable by you.
4. **Index** — Qdrant + FTS5, hybrid retrieval with `bge-reranker-v2-m3` on top.

Retrieval: expand query → parallel keyword + vector (top 30 each) → dedupe → rerank to top 8
→ recency boost. Always inject current date/time and today's calendar; local models are
hopeless at temporal reasoning otherwise. Always carry source and timestamp so she can say
"you told me this in March, it may be stale."

**Bounded memory beats unbounded.** Hermes's design — when memory fills, the agent must
consolidate before it can save anything new — is better than nightly compression. Scarcity
forces curation. Adopt it.

**Build the eval set before the ingestion.** 25 questions about your own life with known
answers, in `eval/questions.yaml`. Run after every retrieval change. It's the least
interesting hour in this project and the one that decides whether she feels like FRIDAY or
like a chatbot with a filing cabinet.

---

## 8. Model routing

Two layers. LiteLLM is transport, the agent frameworks are policy.

```yaml
# litellm.yaml
model_list:
  - {model_name: daily,  litellm_params: {model: openai/qwen36-27b, api_base: http://127.0.0.1:8080/v1}}
  - {model_name: fast,   litellm_params: {model: openai/gemma4-4b,  api_base: http://127.0.0.1:8081/v1}}
  - {model_name: coder,  litellm_params: {model: openai/devstral2,  api_base: http://127.0.0.1:8083/v1}}
  - {model_name: vision, litellm_params: {model: openai/qwen3-vl,   api_base: http://127.0.0.1:8084/v1}}
router_settings:
  fallbacks: [{"daily": ["fast"]}, {"coder": ["daily"]}]
```


```bash
hermes model set primary daily
hermes model set auxiliary.curator fast      # weekly job, doesn't need 27B
hermes model set auxiliary.summarizer fast
```

| Role | Alias |
|---|---|
| Scrutiny scoring, intent, classification | `fast` |
| Voice turns | `fast` |
| General reasoning, curation | `daily` |
| Autonomous coding | `coder` |
| Screenshots, vision | `vision` |

**Route by sensitivity first, capability second.** Vault, health, messages and finances
resolve to local aliases by config, not by preference.

Bind LiteLLM to `127.0.0.1` only and issue virtual keys per agent — Hermes shipped a
hardening release specifically patching a LiteLLM credential exposure.

---

## 9. Security

She is an always-on process with your credentials, your entire life indexed, shell access,
and initiative. Prompt injection is the live threat: an email she reads at 3am is untrusted
input with a path to your shell.

- **No port forwarding.** Headscale or WireGuard only.
- **Voice auth.** Resemblyzer gate on every voice command.
- **Filesystem-enforced core.** Agent runs as `friday`; `agent/core/` owned by the supervisor
  user. The agent writes skills, tools, prompts, configs — never the loop that runs them.
- **Capabilities, not credentials.** Secrets in age/sops, decrypted per-call by a helper the
  agent cannot read.
- **Untrusted-content tagging.** Everything ingested gets wrapped and marked. Mitigation, not
  a fix — assume it can fail.
- **Per-task tool allowlists.** Research gets search + read. Coding gets git + shell on one
  branch. Never a global grant.
- **Hard budgets.** Tokens and wall clock per task, enforced by the supervisor. Runaway loops
  are the default failure, not an edge case.
- **Branch only, human merge.** Not once, not for small things.
- **Kill switch** from your phone plus a physical button.
- **Full-disk encryption.**

The supervisor: ~150 lines, different user, outside her reach. Health-checks every 30s,
reverts to last-known-good after three failures, kills over-budget tasks, hard-stops if
`agent/core/` is modified, and only advances the `known-good` tag after a full eval pass.

That's your self-healing — not the agent fixing itself, but a stupid watchdog that reverts.

---

## 10. Where it will break

- **Bridge instability**, WhatsApp especially. Re-link every few months.
- **Retrieval collapse around 10k documents.** The reranker and consolidation loop are what
  save you — which is why they're in week 3, not week 8.
- **Temporal reasoning.** Resolve dates in code, never in the prompt.
- **Runaway overnight tasks.** Your first unbounded run will burn 2M tokens for nothing.
- **Scrutiny false positives.** She'll flag your complaining as a brainstorm. Log every
  correction from day one — that's your fine-tuning set.
- **Idle power draw.** Wake-on-demand the big cards.
- **The week-6 novelty cliff.** The magic wears off and you notice how often she's subtly
  wrong. That's when the eval suite starts earning its keep. Push through.

---

## 11. Start

```bash
# 1. Agent runtime
curl -fsSL https://open-jarvis.github.io/OpenJarvis/install.sh | bash
jarvis init --preset morning-digest-linux

# 2. Scaffold
sudo mkdir -p /srv/friday/{vault/{daily,projects,people,ideas},db,agent/{skills,tools,prompts,core},loops,ingest,work,eval,logs}
cd /srv/friday && git init work
```

Then write `vault/profile.md` by hand. Not generated — you write it. It's the seed everything
else grows from, and it's the reason she'll feel like she knows you.
