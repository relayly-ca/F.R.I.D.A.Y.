# FRIDAY

A fully local, always-on ambient AI. One layer per job, nothing redundant.

Everything here runs on your hardware and sends nothing to anyone else's server.

The authoritative document is [`docs/spec/FRIDAY-final-spec.md`](docs/spec/FRIDAY-final-spec.md).
Where any file in this repository disagrees with the spec, the spec wins and the file is the
bug. This README is a map of the spec, not a replacement for it.

Written for the person who maintains this at 3am. That person is you.

## Status

Rebuilding from the spec. The build order in section 6 of the spec is the schedule, and it
says **do not reorder**.

| Week | Do | Done when | Status |
|---|---|---|---|
| 1 | llama.cpp + LiteLLM + OpenJarvis, `--preset chat-simple` | You chat locally | [ ] |
| 1 | Conduit + mautrix bridges + Hermes gateway | You text FRIDAY from your phone | [ ] |
| 2 | Radicale + DAVx5; ingest Matrix db + calendar | She answers "what's my week look like" | [ ] |
| 2-3 | Memory: vault, Qdrant, FTS5, reranker, **eval set** | 20/25 on your own eval questions | [ ] |
| 3 | OpenJarvis `monitor_operative` + `morning_digest` | Vault grows without you writing in it | [ ] |
| 4 | notmuch, files, browser, Home Assistant | Eval score holds after each new source | [ ] |
| 4-5 | Voice: Whisper to Kokoro, wake word + clap, speaker ID | Under 800ms, hands-free, voice-gated | [ ] |
| 5 | MCP tools, OpenHands sandbox, **supervisor** | She can act, and you can kill her | [ ] |
| 6 | Mode detection + brainstorm behavior | She shuts up and takes notes on command | [ ] |
| 7 | **Adaptive Scrutiny** + bounded specialists | She works overnight, reports at breakfast | [ ] |
| 8+ | `jarvis optimize skills --policy dspy` + Hermes Curator | Skills improve measurably, not just numerously | [ ] |

Week 2-3 is the least exciting and the most load-bearing. Voice before memory is the mistake
everyone makes.

## The rule that shapes everything

**One owner per layer.** The failure mode of this project is installing four things that each
do 60% of the job and spending your weekends reconciling them.

Section 3 of the spec lists what was cut and why, so it does not get re-litigated at 2am.
Twelve candidates were rejected, including Khoj, OpenClaw, Open Interpreter, and every chat
frontend. If you find yourself about to install something that overlaps a row below, read
that section first.

## The stack

| Layer | Owner | License | Why it wins the slot |
|---|---|---|---|
| Inference | llama.cpp + vLLM | MIT / Apache-2.0 | Standard. vLLM only when you need throughput |
| Model routing | LiteLLM | MIT | One endpoint, aliases, fallback, spend caps |
| Agent runtime | OpenJarvis | Apache-2.0 | Local-first, DSPy skill optimization, scheduled and continuous agents |
| Messaging + user model | Hermes Agent | MIT | 23 gateways from one process, Honcho user modeling, bounded memory, Curator |
| Proactive triage | Adaptive Scrutiny pattern | see below | The decision layer no other project ships |
| Autonomous coding | OpenHands | MIT | 72% SWE-bench, sandboxed Docker, 100+ providers via Ollama |
| Workspace UI | Odysseus | **AGPL-3.0** | Cookbook hardware matching, files, email, deep research |
| Ambient dashboard | Home Assistant | Apache-2.0 | Wall display, voice satellites, presence, IoT |
| STT | faster-whisper large-v3-turbo | MIT | |
| Wake | openWakeWord + clap detect | Apache-2.0 | Two triggers |
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
urgency . impact . novelty . risk . confidence . specificity . conflict
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

## Memory

Four tiers.

1. **`vault/profile.md`** — hand-written by you, ~1500 tokens, injected into every prompt.
   Honcho feeds proposals into it; you approve them. Not generated. It is the seed
   everything else grows from.
2. **Episodic log** — `episodic.db`, append-only, never edited, only compressed.
3. **Vault** — markdown: `daily/` `projects/` `people/` `ideas/`. Written by the
   consolidation loop, editable by you.
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
