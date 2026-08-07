# FRIDAY

A fully local, always-on ambient AI. One layer per job, nothing redundant.

Everything here runs on your hardware and sends nothing to anyone else's server.

The authoritative document is [`docs/spec/FRIDAY-final-spec.md`](docs/spec/FRIDAY-final-spec.md).
Where any file in this repository disagrees with the spec, the spec wins and the file is the
bug. This README is a map of the spec, not a replacement for it.

Written for the person who maintains this at 3am. That person is you.

## Requirements

Two hardware profiles, and the same repository runs on both. Nothing in the architecture
depends on which box it is: spec section 8's aliases are indirection, so a profile changes
what `daily` points at and touches no calling code ([ADR-0025](docs/DECISIONS.md)).

| | `dev` | `target` |
|---|---|---|
| GPU | anything, including none | **24 GB VRAM** |
| RAM / disk | 16 GB / 40 GB | 32-64 GB / 250 GB-1 TB |
| Weights | ~4 GB | ~40 GB |
| `daily` | the small model | Qwen 3.6 27B @ Q4 |
| `embed` / `rerank` | bge-m3 / bge-reranker-v2-m3 | **identical** |

```bash
echo 'dev' | sudo tee /etc/friday/profile      # default is target
```

Because the embedding and reranking models are the same in both, **retrieval is comparable
across profiles** — a change that helps on dev helps on target, and week 2-3, the long pole,
is fully testable on a weak GPU. Answer quality is not comparable, so the 20/25 gate is a
target-profile gate.

Arch Linux throughout. Full-disk encryption is an install-time decision and cannot be added
later. Full bill of materials, every package, and what is deliberately absent:
[`docs/INSTALL.md`](docs/INSTALL.md).

## Status

Rebuilding from the spec. The build order in section 6 of the spec is the schedule, and it
says **do not reorder**.

| Week | Guide | Do | Done when | Status |
|---|---|---|---|---|
| 1 | [W1](docs/weeks/W1.md) | llama.cpp + LiteLLM + OpenJarvis, `--preset chat-simple` | You chat locally | [ ] |
| 1 | [W1](docs/weeks/W1.md) | Conduit + mautrix bridges + Hermes gateway | You text FRIDAY from your phone | [ ] |
| 2 | [W2](docs/weeks/W2.md) | Radicale + DAVx5; ingest Matrix db + calendar | She answers "what's my week look like" | [ ] |
| 2-3 | [W2](docs/weeks/W2.md), [W3](docs/weeks/W3.md) | Memory: vault, Qdrant, FTS5, reranker, **eval set** | 20/25 on your own eval questions | [ ] |
| 3 | [W3](docs/weeks/W3.md) | OpenJarvis `monitor_operative` + `morning_digest` | Vault grows without you writing in it | [ ] |
| 4 | [W4](docs/weeks/W4.md) | notmuch, files, browser, Home Assistant | Eval score holds after each new source | [ ] |
| 4-5 | [W4](docs/weeks/W4.md), [W5](docs/weeks/W5.md) | Voice: Whisper to Kokoro, wake word + clap, speaker ID | Under 800ms, hands-free, voice-gated | [ ] |
| 5 | [W5](docs/weeks/W5.md) | MCP tools, OpenHands sandbox, **supervisor** | She can act, and you can kill her | [ ] |
| 6 | [W6](docs/weeks/W6.md) | Mode detection + brainstorm behavior | She shuts up and takes notes on command | [ ] |
| 7 | [W7](docs/weeks/W7.md) | **Adaptive Scrutiny** + bounded specialists | She works overnight, reports at breakfast | [ ] |
| 8+ | [W8](docs/weeks/W8.md) | `jarvis optimize skills --policy dspy` + Hermes Curator | Skills improve measurably, not just numerously | [ ] |

Week 2-3 is the least exciting and the most load-bearing. Voice before memory is the mistake
everyone makes.

## The rule that shapes everything

**One owner per layer.** The failure mode of this project is installing four things that each
do 60% of the job and spending your weekends reconciling them.

Section 3 of the spec lists what was cut and why, so it does not get re-litigated at 2am.
Twelve candidates were rejected, including Khoj, OpenClaw, Open Interpreter, and every chat
frontend. If you find yourself about to install something that overlaps a row below, read
that section first.

Candidates that arrived after the spec was written are recorded the same way in
[ADR-0015](docs/DECISIONS.md) — including Archon, which is a coding harness and not the
knowledge base and dashboard it used to be, and which is cut for a cloud dependency and an
overlap with OpenHands rather than for lacking merit.

## The stack

| Layer | Owner | License | Why it wins the slot |
|---|---|---|---|
| Inference | llama.cpp + vLLM | MIT / Apache-2.0 | Standard. vLLM only when you need throughput |
| Model routing | LiteLLM | MIT | One endpoint, aliases, fallback, spend caps |
| Agent runtime | OpenJarvis | Apache-2.0 | Local-first, DSPy skill optimization, scheduled and continuous agents |
| Messaging + user model | Hermes Agent | MIT | 23 gateways from one process, Honcho user modeling, bounded memory, Curator |
| Proactive triage | Adaptive Scrutiny pattern | see below | The decision layer no other project ships |
| Workflow graph | pydantic-graph + `friday/graph/` | MIT / yours | How multi-step work moves: checks, handoffs, loops, human gates |
| Autonomous coding | OpenHands | MIT | 72% SWE-bench, sandboxed Docker, 100+ providers via Ollama |
| Workspace UI | Odysseus | **AGPL-3.0** | Cookbook hardware matching, files, email, deep research |
| Devices and presence | Home Assistant | Apache-2.0 | ESP32/ESPHome voice satellites, presence, IoT. **Deferred past W8** |
| Wall surface | Next.js + Tailwind + shadcn/ui | yours | Agent state, running graphs, pending gates. Renders; never commands |
| Voice pipeline | Pipecat | BSD-2-Clause | VAD, turn-taking, streaming, barge-in phase 1. Transport only; the policy stays ours |
| STT | faster-whisper large-v3-turbo | MIT | One process, on the GPU. Satellites stream and never transcribe |
| Wake | openWakeWord + clap detect | Apache-2.0 | Two triggers. A clap cannot false-trigger from speech |
| Speaker auth | Resemblyzer voiceprint | MIT | Voice as an auth factor, not just input |
| TTS | Kokoro-82M / Chatterbox-Turbo | Apache-2.0 / MIT | Fast default, cloned voice when it matters |
| Vectors | Qdrant | Apache-2.0 | |
| Structured | SQLite + FTS5 | Public domain | |
| Messages in | Matrix (Conduit) + mautrix bridges | Apache-2.0 / AGPL-3.0 | The whole answer to "it knows my messages" |
| Calendar | Radicale + DAVx5 | GPL-3.0 | |
| Mail | mbsync + notmuch | GPL | |
| Tracing | Langfuse | MIT | You will need this at 3am |
| Git | Forgejo | MIT | Agent branches, human merges |
| Secrets | age + sops | MIT / Apache-2.0 | |
| Network | Headscale or WireGuard | BSD / GPL | Never a port forward |
| Supervisor | ~150 lines you write | yours | The only thing outside her reach |

Odysseus is AGPL-3.0 and mautrix, Radicale, notmuch and mbsync are GPL-family. They run as
separate processes, so this repository's MIT license is not affected. If you ever link
against one rather than exec it, that changes.

**Libraries are not layers.** `pydantic-ai` (MIT) is the agent and tool library inside
`friday/` and `scrutiny/`: typed tools, validated arguments, and guaranteed structured
output. It does not take a row above, because it is not a daemon and removing it would not
require replacing a layer. LiteLLM remains transport. Its Logfire integration is **not**
adopted — Langfuse owns tracing, and a second owner is the failure this whole document is
organised against. See [ADR-0011](docs/DECISIONS.md).

**Adaptive Scrutiny** is the one layer with a licensing decision attached. OpenAGI ships the
pattern under **PolyForm Noncommercial**, which is source-available, not open source. For
personal use you can run it directly. To keep the stack license-clean, implement the pattern
yourself: a scoring prompt, a threshold table, and a dispatch switch, around 200 lines. The
design is the valuable part.

## Who owns what

```
        +------------ SURFACES ------------+
        |  Matrix . Voice . HA wall . Web  |
        +----------------+-----------------+
                         |
     +-------------------v-------------------+
     |  HERMES - gateways, user model        |
     |  23 channels, Honcho, bounded memory  |
     +-------------------+-------------------+
                         |
     +-------------------v-------------------+
     |  SCRUTINY - 7-axis triage (yours)     |
     |  act . ask . watch . ignore . propagate|
     +-------------------+-------------------+
                         |
     +-------------------v-------------------+
     |  GRAPH - how the work moves           |
     |  jobs . state . checks . human gates  |
     +-------+-----------------------+-------+
             |                       |
   +---------v---------+   +---------v---------+
   | OPENJARVIS        |   | OPENHANDS         |
   | scheduled agents  |   | bounded coding    |
   | continuous monitor|   | sandboxed, branch |
   | skill optimizer   |   +-------------------+
   +---------+---------+
             |
   +---------v------------------------------+
   |  MEMORY - vault . SQLite . Qdrant      |
   +---------^------------------------------+
             |
   +---------+------------------------------+
   |  SENSES - Matrix db . CalDAV . notmuch |
   |  files . browser . Home Assistant      |
   +----------------------------------------+

  LiteLLM sits beside all of it. Supervisor sits above all of it.
```

## Adaptive Scrutiny

Every incoming signal — a message, a calendar change, an observed pattern, the end of a
brainstorm session — is scored on **seven axes**:

```
urgency . impact . novelty . repetition . risk . confidence . specificity
```

and dispatched to one of **five actions**:

| Action | Meaning |
|---|---|
| `act` | Do it now, report after |
| `ask` | Surface it, wait for you |
| `watch` | Not yet, re-evaluate on new information |
| `ignore` | Below threshold, log and drop |
| `propagate` | Hand to a bounded specialist |

Scoring rejects low-value signals **before the expensive model is invoked**. That is the
difference between an assistant that pings you forty times a day and one you trust. It is
also cheap: the 4B router does the scoring.

Seven graded axes, all floats, all thresholded. `conflict` used to be listed among them and
is not an axis — `config/scrutiny.yaml` always declared it `type: bool` while the other six
were floats, and the rule table used it once, alone, with no threshold. It is a **flag**, and
it moved to `context` beside `speaker_verified`. `repetition` took the seventh slot, matching
OpenAGI's source, and it is the axis that finds work worth automating
([ADR-0014](docs/DECISIONS.md)).

## The graph

Scrutiny decides whether a signal is worth acting on. It says nothing about **how the work
then moves**, and until that has an owner it accretes as ad-hoc Python, differently each
time.

A graph is jobs connected by arrows with shared state moving between them. Reserve one for
work with multiple steps, multiple sources, parallel paths, checks, risks, or approvals —
and use the smallest graph that raises quality. An oversized graph is harder to reason about
than the code it replaced.

`pydantic-graph` types the nodes, the edges and the state. `friday/graph/` owns the three
things it does not provide:

- **Checkpoints** after every node, so a run has a resumable position.
- **Resumption**, so a supervisor budget kill resumes rather than restarts. That is what
  makes killing a task cheap enough to actually do.
- **The human gate**, which is not a new concept: it is scrutiny's `ask`, through the same
  dispatch into the same inbox. There is exactly one place a human is asked.

Two rules bind every graph.

**The writer is never the checker.** Any node that writes to the vault or the index has a
distinct checker in front of it, run by a different agent. A single model grading its own
answer inflates its confidence, and "the digest is confidently wrong" is a failure this
repository had already written down before it had anywhere to put the fix.

**Graph definitions live in `agent/core/`.** She writes skills, tools, prompts and configs.
A graph is a loop that runs things, so she does not write it — the same boundary, enforced
the same way, by the filesystem.

Beside that sits the **ratchet**: every logged correction can be promoted into a permanent
rule in the threshold table. Promotion proposes a diff and never applies it. The table stays
hand-maintained, which is what makes it correctable; the ratchet just does the tedious part
of working out which rule was wrong, on which scores, how often.

See [ADR-0012](docs/DECISIONS.md) and [ADR-0013](docs/DECISIONS.md).

## Memory

Four tiers.

1. **`vault/profile.md`** — hand-written by you, ~1500 tokens, injected into every prompt.
   Honcho feeds proposals into it; you approve them. Not generated. It is the seed
   everything else grows from.
2. **Episodic log** — `episodic.db`, append-only, never edited, only compressed.
3. **Vault** — markdown: `daily/` `projects/` `people/` `ideas/`. Written by the
   consolidation loop, editable by you. Obsidian-compatible: YAML frontmatter and
   `[[wikilinks]]`, so DataviewJS can query it. Nothing Obsidian-specific is ever required
   to read it ([ADR-0017](docs/DECISIONS.md)).
4. **Index** — Qdrant + FTS5, hybrid retrieval with `bge-reranker-v2-m3` on top.

Retrieval: expand query, parallel keyword and vector at top 30 each, dedupe, rerank to top 8,
recency boost. Always inject the current date and time and today's calendar — local models
are hopeless at temporal reasoning otherwise. Always carry source and timestamp, so she can
say "you told me this in March, it may be stale."

**Bounded memory beats unbounded.** When memory fills, she must consolidate before saving
anything new. Scarcity forces curation. This is not nightly compression, and the difference
matters.

**Build the eval set before the ingestion.** 25 questions about your own life with known
answers, in `eval/questions.yaml`. The least interesting hour in this project and the one
that decides whether she feels like FRIDAY or like a chatbot with a filing cabinet.

## Models

| VRAM | Daily driver |
|---|---|
| 12-16 GB | Gemma 4 12B @ Q4 |
| 16 GB | Devstral-2 22B @ Q4 |
| **24 GB** | **Qwen 3.6 27B @ Q4** |
| 32 GB | Qwen3.6-35B-A3B |
| 48 GB | Qwen3-Coder-Next |
| 128 GB | gpt-oss-120b |

Always resident, about 6 GB: Qwen3 4B router, bge-m3 embeddings, bge-reranker-v2-m3,
faster-whisper, Kokoro.

Aliases: `fast` for scrutiny scoring, intent, classification and voice turns; `daily` for
general reasoning and curation; `coder` for autonomous coding; `vision` for screenshots.

**Route by sensitivity first, capability second.** Vault, health, messages and finances
resolve to local aliases by config, not by preference.

Verify current model picks before downloading. Odysseus's Cookbook scans your hardware and
recommends.

## Security

She is an always-on process with your credentials, your entire life indexed, shell access,
and initiative. **Prompt injection is the live threat**: an email she reads at 3am is
untrusted input with a path to your shell.

- No port forwarding. Headscale or WireGuard only.
- Voice auth. Resemblyzer gate on every voice command.
- Filesystem-enforced core. She runs as `friday`; `agent/core/` is owned by the supervisor
  user. She writes skills, tools, prompts, configs — never the loop that runs them.
- Capabilities, not credentials. Secrets in age/sops, decrypted per call by a helper she
  cannot read.
- Untrusted-content tagging. Mitigation, not a fix — **assume it can fail**, and put the
  real boundary somewhere that survives that.
- Per-task tool allowlists. Never a global grant.
- Hard budgets on tokens and wall clock, enforced by the supervisor. Runaway loops are the
  default failure, not an edge case.
- Branch only, human merge. Not once, not for small things.
- Kill switch from your phone plus a physical button.
- Full-disk encryption.

The supervisor is ~150 lines, runs as a different user, and sits outside her reach. It
health-checks every 30s, reverts to last-known-good after three failures, kills over-budget
tasks, hard-stops if `agent/core/` is modified, and **only advances the `known-good` tag
after a full eval pass**.

That is the self-healing: not the agent fixing itself, but a stupid watchdog that reverts.

Full threat model in [`docs/SECURITY.md`](docs/SECURITY.md).

## Where it will break

Section 10 of the spec, worth reading before you are surprised by it: bridge instability
(WhatsApp especially), retrieval collapse around 10k documents, temporal reasoning, runaway
overnight tasks, scrutiny false positives, idle power draw, and the week-6 novelty cliff.

Log every scrutiny correction from day one. That is your fine-tuning set.

## Start

Do not skip to week 5. See [`docs/weeks/`](docs/weeks/) for the phase guides.

```bash
# 1. Agent runtime
curl -fsSL https://open-jarvis.github.io/OpenJarvis/install.sh | bash
jarvis init --preset morning-digest-linux

# 2. Scaffold
sudo mkdir -p /srv/friday/{vault/{daily,projects,people,ideas},db,agent/{skills,tools,prompts,core},loops,ingest,work,eval,logs}
cd /srv/friday && git init work
```

Then write `vault/profile.md` by hand.

## License

MIT for this repository. Upstream components carry their own licenses; see the stack table.
Verify each against its upstream before shipping anything derived — projects relicense.
