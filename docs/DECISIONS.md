# Decision log

Architecture decision records. Append; do not rewrite.

The spec is the root document. These ADRs record decisions the spec makes, decisions it
implies, and decisions made after it. An ADR that contradicts the spec is wrong unless it
explicitly supersedes a numbered section and says so.

The point of this file is that a future session, or a future you, does not relitigate a
settled question at 2am with less context than the person who settled it. Section 3 of the
spec exists for the same reason and is quoted here rather than re-argued.

Format: Context / Decision / Consequences / Date.

| ADR | Title | Source | Status |
|---|---|---|---|
| 0001 | One owner per layer | spec §0, §3 | Accepted |
| 0002 | Seven axes, five actions | spec §4 | Accepted |
| 0003 | Implement Adaptive Scrutiny rather than run OpenAGI | spec §4 | Accepted |
| 0004 | Filesystem-enforced core | spec §9 | Accepted |
| 0005 | Capabilities, not credentials | spec §9 | Accepted |
| 0006 | Assume untrusted-content tagging fails | spec §9 | Accepted |
| 0007 | Bounded memory: consolidate when full | spec §7 | Accepted |
| 0008 | Route by sensitivity first, capability second | spec §8 | Accepted |
| 0009 | The supervisor gates the known-good tag | spec §9 | Accepted |
| 0010 | OpenHands keeps the autonomous-coding slot; OpenCode is out | this session | Accepted |
| 0011 | pydantic-ai is the agent and tool library; LiteLLM stays transport | this session | Accepted |
| 0012 | A workflow graph layer: pydantic-graph for typing, ours for state and gates | **extends spec §1** | Accepted |
| 0013 | The ratchet, and the writer is never the checker | spec §10 | Accepted |
| 0014 | The seventh axis: conflict is a flag, repetition is the axis | **supersedes ADR-0002, amends spec §4** | Accepted |
| 0015 | Candidates evaluated and cut, August 2026 | spec §3 | Accepted |
| 0016 | The ambient dashboard is two layers: Home Assistant and a wall surface | **extends spec §1** | Accepted |
| 0017 | The vault is Obsidian-compatible | spec §7 | Accepted |
| 0018 | STT stays large-v3-turbo; the satellites do not transcribe | spec §1 | Accepted |
| 0019 | Barge-in: stop acoustically, classify semantically, suspend rather than kill | spec §5, §6 | Accepted |
| 0020 | Vision and IoT defer past W8; ambient means one room first | **reorders spec §6** | Accepted |
| 0021 | ADR-0003 re-examined: OpenAGI stays out, for ADR-0001 and not for the licence | **amends ADR-0003** | Accepted |
| 0022 | OpenAGI does not replace Hermes | spec §1, §7 | Accepted |
| 0023 | Pipecat owns the voice pipeline transport; the policy stays ours | spec §1, §6 | Accepted |
| 0024 | Radicale and Odysseus do not overlap; ADR-0015 was wrong | **corrects ADR-0015** | Accepted |
| 0025 | Hardware profiles; nothing in the architecture depends on the box | spec §1, §8 | Accepted |
| 0026 | MCP in both directions, and each is a different risk | spec §9 | Accepted |
| 0027 | No Supabase; SQLite and Qdrant stay | spec §1, §7 | Accepted |
| 0028 | The repository is forkable; personal data never enters it | this session | Accepted |
| 0029 | Prompt assembly order is frozen-then-volatile | spec §7 | Accepted |
| 0030 | Context management within a run, distinct from memory across runs | spec §7 | Accepted |
| 0031 | Progressive disclosure for skills and tools | spec §6 | Accepted |
| 0032 | A secret in the vault outlives the fix | spec §9 | Accepted |
| 0033 | Scheduled work keeps run records and pauses itself | spec §10 | Accepted |
| 0034 | Rubrics for tasks, and the grader is not the writer | spec §4 | Accepted |
| 0035 | Answers cite their sources inline | spec §7 | Accepted |
| 0036 | The knowledge graph is derived from the vault, not authored beside it | spec §7 | Accepted |
| 0037 | The vault is OKF-shaped; the schema is ours | spec §7 | Accepted |

---

## ADR-0001: One owner per layer

**Context**

Spec §0: "The failure mode of this project is installing four things that each do 60% of the
job and spending your weekends reconciling them."

It happens gradually. Nobody decides to run two agent runtimes. Someone installs a second
thing for one feature, it accretes responsibilities, and eighteen months later neither can
be removed.

**Decision**

Every layer in the spec §1 table has exactly one owner. Spec §3 lists twelve rejected
candidates with reasons. Adding anything that overlaps an existing row requires an ADR that
either replaces the incumbent outright or argues that the layer is actually two layers.

"I need one feature from project X" is not sufficient grounds. Either the feature belongs in
the incumbent, or the incumbent is wrong and should be replaced.

**Consequences**

- Some features arrive late or never, because they live in a project that owns a layer
  already owned here.
- Replacing a layer is a project, not an increment. That cost is the point.
- The system stays small enough to hold in your head, which is what makes it fixable at 3am.
- The §1 table is normative. If the running system disagrees with it, the running system is
  wrong.

**Date**: 2026-08-07

---

## ADR-0002: Seven axes, five actions

**Context**

Spec §4. Every incoming signal is scored on seven axes and dispatched to one of five
actions. Both numbers are load-bearing and an earlier draft of this scaffold got both wrong,
which is why they are an ADR rather than a comment.

**Decision**

Axes, exactly these seven:

```
urgency . impact . novelty . risk . confidence . specificity . conflict
```

Actions, exactly these five:

| Action | Meaning |
|---|---|
| `act` | Do it now, report after |
| `ask` | Surface it, wait for you |
| `watch` | Not yet, re-evaluate on new information |
| `ignore` | Below threshold, log and drop |
| `propagate` | Hand to a bounded specialist |

`act` and `propagate` are distinct and collapsing them is the mistake to avoid: `act` is
doing the thing directly; `propagate` is handing it to a bounded specialist with its own
budget and allowlist. A design with four actions has quietly removed one of those.

The scoring runs on the `fast` alias (4B router), because the entire economic argument for
this layer is that it rejects low-value signals **before** the expensive model is invoked.

**Consequences**

- The threshold table is written and maintained by hand. It will be wrong at first, and it
  is correctable, which a model picking actions freeform is not.
- Adding an axis is a schema change touching the scorer, the table, and the tests.
- Every decision names the rule that produced it. A decision with no rule is a bug.
- Spec §10: she will flag your complaining as a brainstorm. Log every correction from day
  one; that is the fine-tuning set.

**Date**: 2026-08-07

---

## ADR-0003: Implement Adaptive Scrutiny rather than run OpenAGI

**Context**

Spec §4. OpenAGI is the only project shipping this pattern, and it is **PolyForm
Noncommercial** — source-available, not open source. For personal use, running it directly
is fine.

The spec also flags the sourcing problem: nearly all coverage praising OpenAGI comes from
one blog that ranks it first in every comparison it publishes. Judge the repo and the
license, not the write-ups.

**Decision**

Implement the pattern rather than take the dependency. It is a scoring prompt, a threshold
table, and a dispatch switch — around 200 lines. The design is the valuable part.

This keeps every license in the §1 table open source, and it keeps the one layer nobody else
ships under our own control, where the threshold table can be tuned against real corrections
rather than against someone else's defaults.

**Consequences**

- 200 lines to write and own, including the tests.
- No upstream to track, and no upstream improvements either.
- The stack stays license-clean, which matters if this ever stops being personal use.
- Copy the design exactly, per the spec. Deviating from seven axes and five actions is not
  an improvement; see ADR-0002.

**Date**: 2026-08-07

---

## ADR-0004: Filesystem-enforced core

**Context**

Spec §9: "Agent runs as `friday`; `agent/core/` owned by the supervisor user. The agent
writes skills, tools, prompts, configs — never the loop that runs them."

She optimizes her own skills (week 8). That is bounded exactly as long as she cannot
optimize the loop doing the optimizing. A process that can rewrite its own orchestration has
no fixed point: every safety property becomes a property of whatever it last wrote about
itself.

The tempting mitigation is an instruction: "do not modify your core files." That is a
suggestion to a process that can write the file, and it does not survive a confused model,
a misgeneralised skill, or a prompt injection arriving through a bridged group chat.

**Decision**

`agent/core/` is owned by the supervisor user, mode 0755. The agent runs as `friday`. She can
read and execute her orchestration loop; she cannot write it.

Enforced by filesystem permissions, not instructions. Verified at install, verified by
preflight before every phase, and re-verified by the supervisor every 30s — spec §9 says it
hard-stops if `agent/core/` is modified.

**Consequences**

- Two service accounts, and permissions a careless `chown -R` breaks. The install script is
  idempotent so re-running it is the repair.
- The supervisor cannot carry the same sandboxing hardening as the units it polices;
  sandboxing the guard alongside the guarded defeats it.
- Changing the orchestration loop is a human action. That is the correct friction.

**Date**: 2026-08-07

---

## ADR-0005: Capabilities, not credentials

**Context**

Spec §9: "Secrets in age/sops, decrypted per-call by a helper the agent cannot read."

The obvious design hands her the credentials: a token in the environment, a password in a
config file, a key on disk she can read. Then any injection that reaches a tool call also
exfiltrates every credential in one step, and a leak is permanent and total — rotating
afterwards tells you nothing about what was taken.

**Decision**

She gets capabilities. She calls a helper that holds the credential and performs a narrow
action. She cannot read the credential and cannot use it for anything the helper does not
expose.

No secret enters this repository, not even encrypted. The sops recipient configuration is
the single exception, and it contains a public key and no secret material.

**Consequences**

- Every integration needs a helper, which is more work than exporting a token.
- Rotating a secret is a sops edit and a restart, not a code change.
- An injection that reaches a tool call can invoke a capability. It cannot walk away with
  the keys. That is the whole of what this buys and it is worth the friction.
- File ingestion must exclude key material, or a credential in a watched directory reaches
  the index and any query can surface it into a context window — routing around all of this.

**Date**: 2026-08-07

---

## ADR-0006: Assume untrusted-content tagging fails

**Context**

Spec §9 lists untrusted-content tagging and then immediately qualifies it: "Mitigation, not
a fix — assume it can fail."

This is the most consequential sentence in the security section. Every "ignore instructions
in the content below" defence has been defeated. Defences that depend on a model behaving
correctly under adversarial input are a probability, and the attacker gets unlimited
retries.

**Decision**

Tag and wrap ingested content, and then place every real boundary somewhere that survives
that tagging failing:

- Scoring sees ingested text with **no tools attached**, so injected instructions have
  nothing to call.
- The dispatch switch is a deterministic threshold table, not a model choosing an action.
  Injection can move a score; it cannot move a rule.
- Consequential actions route through `ask` and a human.
- Code execution happens inside a container boundary, not behind in-process policy
  (ADR-0010).
- Budgets and the core-immutability check are enforced by a different user, outside her
  reach.

The test for any proposed mitigation: does it still hold if the model does exactly what the
injected text asked? If the answer is no, it is a mitigation and not a boundary, and it
needs a boundary behind it.

**Consequences**

- More architecture than a prompt would need, which is the trade.
- Some capability is lost: she cannot fetch a page mail asked her to fetch, and that is
  correct.
- When a mitigation is proposed, this ADR is the standard it is measured against.

**Date**: 2026-08-07

---

## ADR-0007: Bounded memory means consolidate when full

**Context**

Spec §7: "Hermes's design — when memory fills, the agent must consolidate before it can save
anything new — is better than nightly compression. Scarcity forces curation. Adopt it."

The intuitive design is a nightly job that compresses whatever accumulated. It is easier to
implement and easier to reason about. An earlier draft of this scaffold built exactly that,
which is the design the spec explicitly rejects — hence this ADR.

Nightly compression has no pressure in it. Anything can be saved, because compression is
someone else's problem at 03:00. The corpus grows, the compression job grows with it, and
retrieval quality degrades on a curve nobody is watching. Spec §10 names the failure:
retrieval collapse around 10k documents.

**Decision**

Memory is bounded. When it fills, consolidation must run before anything new can be saved.
The write path blocks on it. Scarcity is the forcing function that makes her curate rather
than hoard.

This does not forbid a scheduled consolidation pass as well. It forbids the scheduled pass
being the *only* consolidation, and it forbids an unbounded write path between passes.

**Consequences**

- The write path can block, and that must be handled rather than worked around with a queue
  that grows without limit — a queue is just unbounded memory in a different file.
- The bound is a real number that has to be chosen and tuned against the eval set.
- Retrieval quality degrades slowly rather than collapsing, and the eval set is what tells
  you which is happening.

**Date**: 2026-08-07

---

## ADR-0008: Route by sensitivity first, capability second

**Context**

Spec §8: "Vault, health, messages and finances resolve to local aliases by config, not by
preference."

Routing normally asks "which model can do this?" first. With a vault of personal data that
ordering is backwards, and subtly so: sensitivity is a property of the DATA, and the data
arrives through retrieval, after routing has already happened. Route on the request and you
have routed before knowing what the context will contain.

**Decision**

Sensitivity resolves first, from a fixed table, before any capability consideration. Vault,
health, messages and finances pin local. A more capable non-local model is refused, not
preferred.

Filtering happens inside the retrieval query, not after ranking. Filtering after ranking
means the ranking was computed over rows the caller may not see, which leaks their existence
through result counts and gaps.

Spec §8 also requires LiteLLM bound to 127.0.0.1 with **virtual keys per agent** — Hermes
shipped a hardening release specifically patching a LiteLLM credential exposure. A single
shared master key across agents is not sufficient.

**Consequences**

- Some questions get a worse answer than the hardware could give. That is the trade, made
  deliberately.
- Sensitivity must be assigned at ingestion; a source without a class is a bug.
- Per-agent virtual keys mean key issuance is part of install, not an afterthought.

**Date**: 2026-08-07

---

## ADR-0009: The supervisor gates the known-good tag

**Context**

Spec §9 specifies the supervisor precisely: ~150 lines, different user, outside her reach.
Health-checks every 30s, reverts to last-known-good after three failures, kills over-budget
tasks, hard-stops if `agent/core/` is modified, and **only advances the `known-good` tag
after a full eval pass**.

That last clause is the one worth calling out. Without it, "last-known-good" degrades to
"last thing that started without crashing," and reverting to it restores a system that boots
and retrieves badly. Spec §10 is explicit that retrieval degrades quietly.

**Decision**

`known-good` advances only after a full eval pass. Starting cleanly is not sufficient. The
eval set is therefore not just a development tool; it is part of the rollback mechanism, and
that is a second reason to build it in week 2-3 rather than later.

The supervisor stays small — around 150 lines. A supervisor with enough surface area to have
its own bugs is not a supervisor.

**Consequences**

- The eval must be runnable non-interactively by the supervisor's user.
- A red eval means no new known-good tag, so a bad retrieval change cannot become the
  rollback target.
- Spec §9 frames this correctly: the self-healing is not the agent fixing itself, it is a
  stupid watchdog that reverts.

**Date**: 2026-08-07

---

## ADR-0010: OpenHands keeps the autonomous-coding slot; OpenCode is out

**Context**

OpenCode (`sst/opencode`, MIT, very actively developed) was evaluated as either a
replacement for or an addition to OpenHands. Reviewed at commit `69f2cbaa`.

It is genuinely strong where it is strong:

- Any OpenAI-compatible endpoint via `@ai-sdk/openai-compatible` and a `baseURL`, so LiteLLM
  drops straight in. Cleaner than OpenHands routing through Ollama.
- `opencode serve` is a headless HTTP server with an OpenAPI 3.1 spec, a generated SDK, and
  SSE event streams, binding 127.0.0.1 by default. A better programmatic surface.
- A real permission model: pattern-matched `allow`/`ask`/`deny` per tool and per agent,
  matching on tool input (`"bash": {"rm *": "deny"}`). `deny` is enforced even under
  `--auto`. It ships `external_directory` and `doom_loop` guards, and denies `.env` reads by
  default.

The problem is what kind of thing that permission model is. It is **in-process policy**:
same process, same user, same namespace, no filesystem isolation. OpenHands' contribution to
the §1 table is named in the table itself — "sandboxed Docker."

ADR-0006 is the deciding standard: assume the mitigation fails. If OpenCode's policy layer is
bypassed, nothing is behind it. If a container is bypassed, that is a kernel boundary
failure and a different class of problem.

**Decision**

OpenHands keeps the slot. OpenCode is not adopted, as a replacement or as an addition —
adding it would be a second owner of the autonomous-coding layer, which is exactly ADR-0001.

Spec §3 already cut Open Interpreter here for being "code execution without memory or a
permission model." OpenCode passes that bar, which is why the question was worth asking. It
fails the containment bar, and containment is what §9 actually specifies.

One thing is taken. Spec §5 endorses stealing ideas from projects too small to build on.
OpenCode's permission configuration is the clearest expression of §9's "per-task tool
allowlists — research gets search + read, coding gets git + shell on one branch, never a
global grant." The **shape** of that config is worth copying into the supervisor's allowlist
enforcement. The daemon is not.

**Consequences**

- Coding tasks route to OpenHands, which reaches models through its own provider config
  rather than natively through LiteLLM. That is a known integration cost.
- The allowlist enforcement in the supervisor should support pattern matching on tool input,
  not just tool names. That is strictly more work than a name list and is what makes "shell
  on one branch" expressible.
- If OpenHands is ever replaced, this ADR is superseded rather than edited, and the
  replacement must clear the ADR-0006 bar.

**Date**: 2026-08-07

---

## ADR-0011: pydantic-ai is the agent and tool library; LiteLLM stays transport

**Context**

`friday/` was going to hand-roll the things every agent framework hand-rolls: tool
registration, argument coercion, structured output, retry on a malformed response. That is a
few hundred lines of the least interesting code in the project, and it is code where being
subtly wrong is invisible.

`pydantic-ai` (MIT, `pydantic/pydantic-ai`) does exactly that surface: typed agents, tools as
decorated functions with automatic validation, guaranteed structured output against a model,
durable execution, and model-agnostic providers including any OpenAI-compatible endpoint. The
repository already depends on `pydantic` and `pydantic-settings`.

The deciding argument is `scrutiny/score.py`. Its `parse_score` contract is already written:
strict, and a missing axis, an extra axis, a value out of range or unparseable JSON all raise
rather than being repaired, because "a repaired score is a guess wearing a number." That is
precisely a structured-output problem, it is the one place in the system where sloppy parsing
becomes a security property rather than a bug, and it is better solved by a library that does
nothing else than by us.

**Decision**

Adopt `pydantic-ai` as a **library inside `friday/` and `scrutiny/`**. It is not a layer
owner and it does not take a row in the spec §1 table, so ADR-0001 is untouched: it is not a
daemon, it does not run, and removing it would not require replacing a layer.

LiteLLM remains transport, unchanged. Spec §8 stands: "LiteLLM is transport, the agent
frameworks are policy." pydantic-ai points at `http://127.0.0.1:4000/v1` with a per-agent
virtual key, exactly as anything else does.

The "capability" composition pattern (instructions, tools, model settings and lifecycle hooks
bundled into a reusable unit) is the shape `config/agents.yaml` already describes, so agent
entries load into capabilities rather than being re-expressed.

**Consequences**

- A real dependency in the hot path. It is pinned, and a major version bump is a change to
  review rather than a `-Syu` away.
- **The allowlist stays ours.** pydantic-ai's tool registration is a convenience, not a
  boundary. ADR-0010's pattern matching on tool input, and the rule that a disallowed tool is
  *absent* rather than present-and-refused, are enforced by `friday/tools/allowlist.py`
  before anything is registered. In particular, `scorer` having `tools: []` (ADR-0006) is
  checked by `friday.config`, not delegated.
- **Logfire is not adopted.** pydantic-ai integrates with Pydantic's own Logfire; Langfuse
  owns the tracing row in spec §1 and ADR-0001 forbids a second owner. Logfire is also a
  hosted service by default, which fails spec §9 outright.
- Structured output replaces hand-rolled parsing, and the strictness in `parse_score` becomes
  a schema rather than a set of conditionals. The contract in its docstring does not change.

**Date**: 2026-08-07

---

## ADR-0012: A workflow graph layer: pydantic-graph for typing, ours for state and gates

**This ADR extends spec §1.** It adds a row to the stack table that the spec does not have.
The preamble to this file requires that to be said explicitly rather than arrived at, so:
the spec's table is otherwise unchanged, no existing row is replaced, and the claim is that
§1 has a gap rather than an error. ADR-0001's bar applies to the new row like any other —
one owner, and adding anything that overlaps it needs an ADR.

**Context**

Nothing in the spec §1 table owns **how multi-step work moves**. Scrutiny decides one signal
and stops. OpenJarvis schedules and monitors. OpenHands codes inside a container. Work with
several steps, a check between them, a handoff, a loop, and a human approval had no owner,
which meant it was going to accrete as ad-hoc Python across `friday/loops/*.py`, differently
each time.

The concrete cost is already documented. `docs/weeks/W3.md` lists "the digest is confidently
wrong" as a failure mode, and the reason it happens is that the consolidator writes to the
vault with nothing between it and the index. There is no structural place to put a checker,
so there is no checker.

Two candidates were evaluated.

**Archon** (`coleam00/Archon`, MIT) is a harness builder: YAML DAGs, `depends_on` edges,
`loop … until`, `interactive` human-approval gates, deterministic `bash` nodes beside AI
`prompt` nodes, one git worktree per run, and a Mission Control dashboard. The design is
right and most of it is already built. It is rejected on three grounds: it needs a Claude
Code binary for full function, which is a cloud dependency and fails spec §9; it ships PostHog
telemetry; and its worktree-isolated coding runs overlap OpenHands, so adopting it reopens
ADR-0010 and ADR-0001 rather than filling an empty row. Its **shape** is worth copying, as
OpenCode's permission config was.

Note also that the Archon many people remember — knowledge base, RAG, task management, web
UI — is archived on `archive/v1-task-management-rag`. It is not a dashboard candidate. Spec
§1 already gives the Workspace UI row to Odysseus, which does more of it.

**pydantic-graph** arrives with ADR-0011 at no extra cost, is standalone, and types nodes,
edges and shared state well: edges are inferred from a node's `run()` return annotation. It
has no documented checkpointing, resumption, or human-in-the-loop gate — which are the three
things a graph layer exists to provide. Its own documentation says not to reach for it
unless you need it.

**Decision**

A new row in the stack table: **Workflow graph — `pydantic-graph` + `friday/graph/`**.

`pydantic-graph` owns node and edge typing and the shared state object. `friday/graph/` owns
the three things it does not:

- **Checkpointing** to SQLite after every node, so a run has a resumable position.
- **Resumption**, so a supervisor budget kill (spec §9) resumes rather than restarts. This is
  what makes `keep_branch_on_kill` and `revert_vault_on_kill` coherent rather than a pair of
  flags that leave you re-running an hour of work.
- **The human gate**, which is not a new concept and must not become one: it is scrutiny's
  `ask`. A graph pausing for approval raises an `ask` through the same dispatch, into the same
  inbox, with the same `ask_expires: false`. There is exactly one place a human is asked.

Two rules bind every graph:

1. **The writer is never the checker.** Any node that writes to the vault or the index has a
   distinct checker node in front of it, run by a different agent. See ADR-0013.
2. **The smallest graph that raises quality.** A graph per loop, not a graph per system. An
   oversized graph is harder to reason about than the ad-hoc code it replaced.

**Consequences**

- **Graph definitions live in `agent/core/`.** ADR-0004: she writes skills, tools, prompts
  and configs, never the loop that runs them. A graph *is* a loop that runs things, so it is
  owned by `fridaysup` and she cannot write it. This falls straight out of ADR-0004 and is
  the main reason the layer needed an ADR rather than a directory.
- A second model call per checked write. The checker runs on `fast`; its quality is bounded
  by the extraction schema, not by model size, the same argument `config/agents.yaml` already
  makes for the consolidator.
- Checkpoint state is another thing to back up and another thing that can be corrupt. It
  lives under `db/` and is covered by `make backup`.
- If a graph engine is ever adopted wholesale, this ADR is superseded rather than edited, and
  the replacement must run fully local with no telemetry.

**Date**: 2026-08-07

---

## ADR-0013: The ratchet, and the writer is never the checker

**Context**

Two pieces of harness engineering, arriving at the same conclusion from different directions.

Martin Fowler's framing splits the controls around a model into **guides** (feedforward,
steering before the act) and **sensors** (feedback, observing after), each either
**computational** — linters, tests, type checks, deterministic and in milliseconds — or
**inferential** — probabilistic, semantic, richer judgement.

Measured against that, FRIDAY is almost entirely computational, and deliberately so: the
deterministic dispatch table, the budgets, preflight, the supervisor, the eval set. That is a
strength and it is also a gap, because computational sensors cannot catch a note that is
fluent, well-formed and wrong.

Addy Osmani's **ratchet** is the other half: each agent mistake becomes a permanent rule.
FRIDAY already collects the raw material — spec §10 says to log every correction from day one
and `config/scrutiny.yaml` specifies exactly what a correction contains — and nothing
converts a correction into a rule. The ledger accumulates and is read by a human who may or
may not act on it.

Both sources also say the same thing about self-evaluation: a model grading its own answer
inflates its confidence, and a separate evaluator outperforms it.

**Decision**

Two patterns adopted, one declined.

**1. The ratchet.** A logged correction can be promoted to a rule in the threshold table.
Promotion **proposes a diff to `config/scrutiny.yaml` and never applies it.** ADR-0002 holds:
the threshold table is written and maintained by hand, and that is what makes it correctable
in a way a model picking actions freeform is not. The ratchet does the tedious part — which
rule was wrong, on which scores, how often — and you merge it.

**2. The writer is never the checker.** Any node that writes to the vault or the index is
preceded by a checker node run by a **different agent**. This is the structural fix for
W3's "the digest is confidently wrong" and it is where the inferential sensor belongs.

**3. Declined: a general LLM-judge layer.** The checker above *is* the inferential sensor,
scoped to a write and to a schema. A general judge sitting over the system fails ADR-0006's
test — does it still hold if the model does exactly what the injected text asked? A judge
does not — and it adds non-determinism to the part of the system whose value is that it is
deterministic.

**Consequences**

- Correction rate becomes a first-class metric, which is what `docs/weeks/W8.md` already
  needs and names as the one most often left out.
- A second model call per checked write, on `fast`. See ADR-0012.
- The ratchet must never auto-apply, for the same reason Honcho's profile proposals and the
  Curator's retirements never auto-apply: a system that rewrites its own policy unattended
  eventually rewrites the part you were relying on.
- A `floor` rate that climbs is the signal the ratchet is meant to act on, and it is already
  in `config/scrutiny.yaml` as an explicit rule for exactly this reason.

**Date**: 2026-08-07

---

## ADR-0014: The seventh axis, and whether there is an eighth

**Status: Proposed.** Deliberately not decided. Revisit on the next pass over the docs.

**Context**

Spec §4 gives the seven axes as `urgency · impact · novelty · risk · confidence ·
specificity · conflict`, and ADR-0002 froze them, calling out that an earlier draft got both
numbers wrong.

Checking the source: OpenAGI's own repository (`spshulem/openAGI`) lists its axes as
**urgency, impact, novelty, repetition, risk, confidence, specificity**. Not `conflict`.
`repetition` is the seventh.

The only source that says `conflict` is a single blog — and it is the same blog spec §4's own
sourcing caveat warns about: "Nearly all the coverage praising OpenAGI comes from one blog
that ranks it first in every comparison it publishes. Judge the repo and the license, not the
write-ups." The spec took an axis from the write-up.

This is not a case of a file disagreeing with the spec. The spec chose seven axes and named
them, and the spec is authoritative. It is a case of the spec's own caveat applying to the
spec.

**The argument for `repetition`.** It is what makes her proactive rather than reactive.
OpenAGI's entire pitch is that it "picks up on the things you do over and over" — repetition
is the axis that finds work worth automating, which is the difference between an assistant
that answers and one that notices. It is also the axis with the most direct relationship to
spec §6 week 3's `monitor_operative` and to the skill optimisation in week 8.

**The argument for `conflict`.** It is the axis that stops her overwriting a true memory with
a false one. `conflict_asks` is currently the second guard in the table and it fires before
any permission. Its rationale — "she can know there is a contradiction; she cannot know which
side is true" — is sound regardless of what upstream does.

**The argument against eight.** ADR-0002: adding an axis is a schema change touching the
scorer, this table and the tests. More axes is also more for a 4B model to get wrong, and the
economic case for the whole layer rests on that model being small. And "seven axes, five
actions" is written into the spec, the README, the config, the code and every week guide.

**The argument for eight anyway.** Both axes are load-bearing and they measure genuinely
different things. `conflict` is arguably expressible as a rule over retrieval rather than as
a scored axis, which would keep seven — that is the option worth examining first.

**Recommendation, not a decision**

Examine whether `conflict` can become a rule fed by a deterministic retrieval check rather
than a model-scored axis. It is a boolean today, which is a hint: a signal either contradicts
something recorded or it does not, and that is a question retrieval can answer without a
model. If that holds, adopt `repetition` as the seventh axis and keep the count at seven,
which matches upstream and costs the 4B scorer nothing.

If it does not hold, eight axes is the honest answer and ADR-0002 gets superseded.

**Nothing changes until this is decided.** `config/scrutiny.yaml`, `scrutiny/score.py` and
`tests/test_policy.py` continue to say seven axes with `conflict`.

**Date**: 2026-08-07

---

## ADR-0015: Candidates evaluated and cut, August 2026

**Context**

A review round covering fourteen projects and three articles. Spec §3 exists so that cuts do
not get re-litigated at 2am; this is the same thing for candidates that arrived after the
spec was written. Adopted outcomes are ADR-0011 through ADR-0013.

Recording the reason matters more than recording the verdict, because the reason is what
tells you whether a future version of the project would change the answer.

**Decision**

| Candidate | Verdict | Reason |
|---|---|---|
| **Archon** | Cut | Claude Code binary for full function, so a cloud dependency; PostHog telemetry; and its worktree coding runs overlap OpenHands. See ADR-0012, which takes the shape and not the daemon |
| **Polsia** | Cut | Invokes the Claude CLI as a subprocess with OAuth to Anthropic, and is business-ops focused. Spec §3's Azaris/AgentCore row, and it fails §9 outright |
| **paperclip** | Cut, ideas taken | MIT and self-hosted, and the per-agent budget enforcement, org chart and governance gates are the right ideas — which `config/agents.yaml` and the supervisor already implement. Its purpose is running a business with agent teams |
| **google/agents-cli** | Cut | Apache-2.0, but it builds ADK agents for Google Cloud. Wrong target |
| **GoogleCloudPlatform/knowledge-catalog** | Cut | Enterprise data governance and metadata cataloguing on GCP |
| **buzz.xyz** | Cannot evaluate | Pre-release, no public technical detail, no license stated |
| **coleam00 skills / ai-native-starter-pack / ai-transformation-workshop** | Not stack, adopted for workflow | These describe how you *build* FRIDAY — the plan-implement-validate loop, rules generated from the codebase, hooks, worktree parallelism. Real value for this repository's own development, zero effect on the §1 table |
| **orbit-support-agent** | Reference | The pydantic-ai capability composition pattern, which ADR-0011 adopts |
| **Pipecat** | Open | Voice and multimodal orchestration. It would own the plumbing between Whisper and Kokoro that `docs/weeks/W4.md` and `W5.md` currently hand-roll. Not evaluated in depth; revisit if the 800ms budget proves hard |
| **Odysseus notes/tasks/CalDAV** | Open | Odysseus ships notes, tasks and CalDAV sync, which partially overlaps W2's Radicale. Not evaluated in depth; Radicale stays for now because a dedicated CalDAV server is a smaller thing to depend on than a workspace |

**Consequences**

- The two `Open` rows are genuinely undecided rather than quietly rejected, and each names
  what would decide it.
- The three coleam00 repositories are the first thing adopted here that is about the
  *development process* rather than the running system. That distinction is worth keeping
  sharp: nothing in them may become a runtime dependency.
- ADR-0001's bar was applied to every row above. In no case was "I need one feature from
  project X" treated as sufficient.

**Date**: 2026-08-07

---

## ADR-0016: The ambient dashboard is two layers: Home Assistant and a wall surface

**This ADR extends spec §1** by splitting one row into two. No incumbent is removed.

**Context**

Spec §1 gives one row to Home Assistant and lists four responsibilities on it: "Wall display,
voice satellites, presence, IoT."

Three of those four are device concerns and Home Assistant is unambiguously the right owner:
ESP32 satellites running ESPHome in each room, presence detection, and everything with a
relay in it. That is what Home Assistant is for and nothing else in the stack comes close.

The fourth is not a device concern. Spec §5 says what the wall display is actually for:

> **Reactive status visualization.** [...] Functional progress indication disguised as
> spectacle. Whatever your dashboard looks like, make the visual reflect actual agent state.

That is a view onto **agent** state — which graph is running, which node it is on, what is
waiting at a human gate, what scrutiny decided in the last hour and under which rule. Home
Assistant's dashboard is built to render entities and their states. Expressing a paused graph
node or a `floor`-rate trend as an HA entity is fighting the tool, and the result is the
failure spec §5 names by heart: a display that animates on a timer instead of reflecting
anything, which you stop trusting within a week.

ADR-0001 anticipates this case explicitly. Adding something that overlaps an existing row
needs an ADR that "either replaces the incumbent outright or argues that the layer is
actually two layers." This is the second one.

**Decision**

Split the row.

- **Home Assistant** keeps voice satellites, presence and IoT. ESP32 boards running ESPHome,
  one per room, streaming audio to the server. HA is the device control plane and the only
  thing that talks to hardware.
- **A wall surface** — Next.js, Tailwind, shadcn/ui — owns the display of agent state. It
  reads the state stream (`friday/output/state.py`), renders running graphs, active loops,
  the inbox of `ask` items, and the current mode. Mounted on a wall tablet. It binds
  loopback and is reached over the mesh like everything else.

The layout is a table architecture rather than a card grid, because what is being shown is
rows of things with a status: graph runs, loops, pending gates, recent decisions and the rule
that produced each. Cards are for dashboards where the tiles are unrelated; these are not.

**Consequences**

- One more thing to build and keep running, and it is a frontend, which is the part of a
  system most likely to rot while the daemon underneath keeps working. It stays small.
- The wall surface renders and does not command. Anything consequential initiated from the
  wall goes through scrutiny's `ask` like any other request, and the tablet is not an
  authenticated principal — a tablet on a wall is reachable by anyone in the room, which is
  the same threat model the Resemblyzer gate exists for (spec §5, §9).
- Odysseus keeps the Workspace UI row and does not overlap this. Odysseus is where you sit
  down and work; the wall is what you glance at from the doorway. If they ever converge, one
  of them is wrong and this ADR is superseded rather than edited.
- The state stream becomes an interface with a consumer, so it must be versioned rather than
  changed freely.

**Date**: 2026-08-07

---

## ADR-0017: The vault is Obsidian-compatible

**Context**

Spec §7 makes the vault tier 3: markdown in `daily/ projects/ people/ ideas/`, written by the
consolidation loop and **editable by you**. That last clause is load-bearing and currently
has no tooling behind it. `docs/weeks/W3.md` already relies on it — the stated fix for a
confidently wrong digest is to correct the note by hand — and "open the file in an editor"
is a thin answer for a corpus heading toward thousands of notes.

Obsidian reads a directory of markdown files. It adds nothing to the format, requires no
import, and does not own the data. DataviewJS turns YAML frontmatter into queryable
structure, so "every open question from the last month" or "everything tagged with this
project that has not been touched since March" becomes a query against notes the
consolidation loop already writes.

**Decision**

The vault is Obsidian-compatible. Concretely, and this is the whole of it:

- Every generated note carries YAML frontmatter with at least `source`, `created`, `updated`,
  `tags`, and the provenance fields spec §7 already requires.
- Links between notes use `[[wikilink]]` form, which is what makes the people and projects
  directories navigable rather than just organised.
- Nothing Obsidian-specific is ever *required* to read the vault. No plugin is a dependency,
  no `.obsidian/` directory is authoritative, and the vault remains a directory of plain
  markdown that `cat` and `grep` fully understand.

**Consequences**

- Costs approximately nothing. It is a frontmatter convention plus not fighting a format.
- The frontmatter is useful independently of Obsidian: it is exactly the provenance spec §7
  requires be carried, in a form the indexer can parse without heuristics.
- `.obsidian/` is gitignored. Workspace state is not vault content.
- The file-ingestion source already watches the vault and must not index `.obsidian/`, which
  the existing `exclude_globs` in `config/sources.yaml` needs extended for.
- This does not make Obsidian an owner of anything. If it disappeared tomorrow the vault
  would be unchanged.

**Date**: 2026-08-07

---

## ADR-0018: STT stays large-v3-turbo; the satellites do not transcribe

**Context**

Spec §1 names `faster-whisper large-v3-turbo` and puts it in the always-resident set. A
latency-first reading argues for a much smaller model — `base.en` — on the grounds that CPU
inference is what blows the 800ms budget in spec §6.

The premise is right and it resolves the question in the other direction. The reason to reach
for `base.en` is CPU inference. With the GPU actually in play — which ADR-0016 makes
structural, because ESPHome satellites stream audio to the server and do not transcribe
anything themselves — there is exactly one STT process, it is on the GPU, and `large-v3-turbo`
is already the fast variant. It is not the model that is spending the budget.

`docs/weeks/W4.md` step 8 gives the breakdown, and STT is 100-250ms of an 800ms budget.
End-of-speech detection is the largest line and the most tunable, at 100-300ms of VAD
hangover that is usually set conservatively at 500-800ms. That is where the time is.

What `base.en` costs is precision on proper nouns, and for this system that is not a quality
preference, it is a correctness failure with a tail. Mishearing "Sam" as "Sarah" does not
produce a slightly worse answer; it produces a confident retrieval against the wrong person's
notes. Every downstream layer — retrieval, novelty scoring, the people directory — then works
correctly on a wrong premise, which is the hardest class of bug to see.

**Decision**

`large-v3-turbo` stays the default, on the GPU, resident. `config/friday.toml` keeps
`stt_model` configurable, and the choice is decided by measurement rather than by argument:
W4 step 8 already requires a per-stage benchmark, and if STT is genuinely the line item
blowing the budget, that benchmark says so and this ADR is superseded with a number attached.

Satellites capture and stream. They do not transcribe, do not run wake-word detection that
matters, and hold no model. One STT, one GPU, one place to tune.

**Consequences**

- The 800ms budget is met by fixing VAD hangover, streaming the first TTS sentence, and
  starting retrieval on the partial transcript — all of which W5 step 3 already lists, and
  none of which trade accuracy away.
- Satellites stay cheap and replaceable. An ESP32 that only captures audio can be replaced
  by any other thing that captures audio.
- Every room's audio crosses the network to the server. That network is the mesh and never
  the internet (spec §9), and it is worth being explicit that this is a microphone array in
  your house streaming to one box.
- If a satellite ever needs to run local wake-word detection to cut bandwidth, that is a
  bandwidth decision and not an STT decision, and it does not reopen this.

**Date**: 2026-08-07

---

## ADR-0019: Barge-in: stop acoustically, classify semantically, suspend rather than kill

**Context**

You cannot currently interrupt her. She speaks a full response and you wait, and the absence
of barge-in is the loudest "I am talking to a machine" tell in the whole interaction — louder
than latency, because a slow human is still a human and one that cannot be interrupted is
not.

Spec §5's interaction ideas are all about making the surface feel right and none of them
cover this. Spec §6's 800ms budget measures the wrong edge for it: 800ms is end of speech to
first audio out, and barge-in is measured from **you starting to speak** to **her stopping**.

There are two problems here and conflating them is the mistake. Stopping her is an acoustic,
real-time problem with no model in it. Working out what you meant is a semantic problem that
cannot begin until you have finished the sentence. They have different deadlines by an order
of magnitude and they must not be built as one thing.

The second problem is the one with teeth. When you interrupt, what you said is one of:

| Kind | Example | What must happen |
|---|---|---|
| **Correction** | "no, the *other* Sam" | Same task, amended parameters, resume |
| **Refinement** | "and add the calendar link" | Same task, more scope, resume |
| **Abort** | "stop", "never mind" | Kill the task. Do not resume |
| **New task** | "actually, what's the weather" | Suspend the old one, start a new one |
| **Not addressed to her** | you talking to someone in the room | Resume as if nothing happened |
| **Backchannel** | "mm-hm", "right", "yeah" | Not an interruption. Keep going |

Backchannels are worth naming explicitly. They are extremely common in real speech, and a
system that treats "mm-hm" as an interruption feels twitchy in a way that is hard to
diagnose because each individual instance looks like a reasonable response.

**Decision**

**Two phases, two deadlines.**

*Phase 1, acoustic, under 200ms, no model.* VAD runs during playback. Speech detected while
she is talking **pauses** TTS immediately. This is deterministic and it is the only part
inside the tight deadline. Acoustic echo cancellation is a hard requirement — without it her
own output re-enters the microphone and she interrupts herself, which is the failure that
makes people give up on full-duplex and go back to muting the mic during playback.

*Phase 2, semantic, after end of speech.* Transcribe, then the `router` agent from
`config/agents.yaml` — `fast`, `tools: []`, temperature 0 — classifies the utterance into one
of the six kinds above, against the in-flight task as context. It emits a **kind and a
confidence, never an action**. Python dispatches. This is ADR-0002's separation applied
unchanged, and it needs no new agent, no new axis and no new action.

**Pause, do not kill.** TTS pauses at the interruption point rather than being discarded.
A backchannel or unaddressed speech resumes from exactly there. This is what makes being
wrong cheap, and being wrong is guaranteed.

**Suspend, do not abandon.** A new task checkpoints the in-flight one rather than discarding
it — which is why this is a **graph feature with a voice trigger** and not a voice feature.
ADR-0012 already specifies checkpointing after every node and resumption after a supervisor
kill. A correction resumes the run from its checkpoint with amended state; a new task leaves
the old run checkpointed and resumable; "where were we" comes back to it. None of that
machinery is new.

**Ambiguity resolves to `ask`, never to a guess.** "What about Thursday?" is genuinely
ambiguous between correcting the day and asking a new question, and no amount of prompt
tuning removes that — the utterance is ambiguous, not the classifier. Below a confidence
threshold she asks one short clarifying question. One question is dramatically cheaper than
silently doing the wrong thing to the right task.

**An unverified speaker cannot redirect a task.** Spec §9: the Resemblyzer gate applies to
every voice command, and an interruption is a command. Someone else in the room saying
"actually, delete it instead" pauses her — anyone can pause her, that is fine and physical —
and cannot change what she is doing. This is `unverified_speaker_asks` in
`config/scrutiny.yaml` reused, not a new rule.

**Every classification is a correction candidate.** Logged to the same ledger as scrutiny
corrections, with the utterance, the in-flight task, the kind chosen and the kind you meant.
ADR-0013's ratchet then applies to it directly. Spec §10 already requires logging corrections
from day one, and this is the single best-defined instance of it in the system.

**Built in W6, not W5.** It needs the graph layer from W5 to be solid, W5 is already the
heaviest week in the schedule and marked as likely to split, and barge-in is an
interaction-model concern, which is what W6 is for. The deciding argument is that W6's mode
detection is the *same shape of problem* — same `router` agent, same classify-then-dispatch-
deterministically pattern, same corrections ledger. Building them together is cheaper than
building them apart.

**Consequences**

- **AEC becomes a hardware requirement**, not a nice-to-have. ESP32-S3-BOX-3 has it onboard,
  which is now a reason to prefer it. A bare board with an I2S microphone and no AEC cannot
  do full-duplex, and this is worth knowing before ordering four of them.
- **`clap_exit_phrase = "ok"` collides with the most common English backchannel** and must
  change. "ok" said mid-response is overwhelmingly a backchannel, not a request to return to
  standby, and no classifier should be asked to separate those. Pick an exit phrase that
  nobody says by reflex.
- A pause that never resumes is worse than no barge-in, because she stops mid-sentence and
  simply never finishes. Resume-on-unaddressed needs a timeout and a test.
- The classifier sees in-flight task context, which may contain ingested untrusted text. It
  is wrapped, and it has `tools: []`, so ADR-0006 applies unchanged and nothing here widens
  the injection surface.
- This generalises past voice: "stop" typed into Matrix while an overnight specialist is
  running is the same dispatch against the same checkpoint. That generalisation is free and
  is not built in W6.

**Date**: 2026-08-07

---

## ADR-0020: Vision and IoT defer past W8; ambient means one room first

**This ADR reorders spec §6**, which says in bold: **do not reorder.** That sentence is the
reason this is an ADR and not a scheduling note, and the argument below has to clear it
rather than route around it.

**Context**

The goal for the first working system is text, voice and ambient presence. Vision and the
Home Assistant / IoT layer are wanted *after* she is functional, not before.

Spec §6 currently puts Home Assistant in week 4 as the fourth ingestion source, and ADR-0016
puts ESP32/ESPHome satellites alongside it. Deferring both moves work out of the numbered
weeks.

**What "do not reorder" is actually protecting.** The spec says it once and explains it once,
in the same paragraph: "Voice before memory is the mistake everyone makes. Week 2-3 is the
least exciting and the most load-bearing." The ordering constraint is a **dependency chain** —
memory before voice, memory before tools, memory before scrutiny — and the failure it
prevents is building the exciting layer on an empty vault.

Home Assistant is not on that chain in either direction. As an ingestion source it is a leaf:
nothing retrieves better because home telemetry is indexed, and W4's rule is "eval score holds
after each new source", which holds over three sources exactly as it holds over four. As a
surface it is downstream of everything. Vision is the same: the `vision` alias is one
llama-server env file that nothing calls yet.

So this reorders §6 without touching what §6's warning is about. That is the argument, and it
would not hold for deferring memory, the eval set, or the supervisor.

**Decision**

Vision and Home Assistant / IoT move out of the numbered weeks into a phase after W8.

- **W4 has three sources, not four**: notmuch, files, browser. Its per-source eval gate is
  unchanged and applies to three.
- **Voice satellites defer.** Ambient in the interim means **one room**: a microphone and
  speakers attached to the server, with the wake word, the clap trigger and barge-in all
  working exactly as designed. W4 already specifies desk audio as the pre-satellite path, so
  this is not new work, it is the existing work standing alone for longer.
- **The wall surface stays in W6.** It is Next.js reading the state stream and it does not
  depend on Home Assistant for anything (ADR-0016 split the row precisely so that this is
  true). A wall tablet is optional; the surface is worth having on any screen.
- **The `vision` alias stays configured and unused.** One env file, no weight downloaded, no
  cost. Removing it and adding it back later is more work than leaving it.

**Consequences**

- **The AEC requirement transfers to the desk microphone.** ADR-0019 makes echo cancellation
  a hard requirement for barge-in, and the reason the ESP32-S3-BOX-3 was named is that it has
  it onboard. Without satellites, the desk setup must supply it: a conferencing microphone
  with hardware AEC, or software AEC via `webrtc-audio-processing` / `speexdsp` in the audio
  path. This is the one thing the deferral makes *harder* rather than simply later, and it is
  worth solving before W6 rather than discovering it there.
- Ambient in one room is genuinely ambient and is also genuinely less than the design. She is
  present where the microphone is, and nowhere else.
- `config/sources.yaml` keeps the `homeassistant` entry with `enabled: false` and its `week:`
  marker becomes 9. Deleting it would lose the configuration that was already reasoned about.
- Nothing in the dependency chain moved, so no later week gains a prerequisite it did not
  have. If a future decision wants to defer something that *is* on the chain — memory, the
  eval set, the supervisor — this ADR is not the precedent for it.

**Date**: 2026-08-07

---

## ADR-0021: ADR-0003 re-examined: OpenAGI stays out, for ADR-0001 and not for the licence

**This ADR amends ADR-0003.** Same conclusion, corrected reasoning, and the correction
matters because the reason a decision was made is what tells you whether a future version of
the project would change it.

**Context**

ADR-0003 chose to implement Adaptive Scrutiny rather than take a dependency on OpenAGI, and
leaned on the licence: "This keeps every license in the §1 table open source." Re-examined
against the project as it actually is, that argument is weaker than it was written, and two
findings run the other way.

**The licence is not a blocker.** Spec §1's own preamble says "Every component below is
either open source **or source-available**," and spec §4 says of PolyForm Noncommercial: "For
personal use that's fine and you can run it directly." The spec permits this. ADR-0003 raised
the bar above what the spec set, without saying it was doing so.

**The dispatch is already deterministic.** This is the objection that would have been
decisive and it does not apply. OpenAGI scores, then maps scores to one of five actions in
code; the model does not choose the action. That is the same separation ADR-0006 rests on,
arrived at independently, and it is a point in the project's favour that ADR-0003 never
credited.

So the honest position is that this was closer than ADR-0003 made it sound.

**What actually decides it**

OpenAGI is not a scrutiny library. It is an always-on daemon on `127.0.0.1:43210` that owns:

| OpenAGI owns | Already owned here by |
|---|---|
| Embedded agent runtime (`abi-runtime.js`) | OpenJarvis |
| Gateways: Telegram, Twilio, HTTP, web UI | Hermes, 23 of them |
| Tiered memory: short, medium, long-term "Lava" | The four tiers of spec §7 |
| Cron scheduler | OpenJarvis scheduled agents, systemd timers |
| Skills system | OpenJarvis skills, Hermes Curator |
| MCP registry and execution | `friday/tools/`, per-agent allowlists |
| Dashboard / SSE | Odysseus, and the wall surface (ADR-0016) |
| **Adaptive Scrutiny** | **the one thing we want** |

Adopting it for the scrutiny layer means installing a second agent runtime, a second gateway
process, a second memory system, a second scheduler, a second skills system, a second MCP
registry and a second dashboard, in order to get one component.

That is spec §0, verbatim, and it is the sentence the whole document is organised around:
"The failure mode of this project is installing four things that each do 60% of the job and
spending your weekends reconciling them."

ADR-0001 is the standing rule and it is unambiguous here. This is not one overlapping row, it
is seven.

**On the combination**

Separating just the scrutiny component is "theoretically" possible —
`src/directional-adaptive-scrutiny.js` is a discrete module — but the orchestration that
threads signals through scrutiny, memory and propagation lives in the runtime, not the
module. Extracting it means porting JavaScript into a Python stack and then maintaining a
fork of one file from a project we are not otherwise running. That is strictly more work than
the 200 lines, and it carries an upstream we cannot merge from.

And the cost side has moved since ADR-0003 was written. `scrutiny/policy.py` is implemented
with 45 tests passing. The dispatch switch, the restricted expression evaluator and the rule
table exist. What remains is the scorer and the table loader. The "200 lines to write and
own" that ADR-0003 traded away is now mostly written, so adoption today buys less than it
would have bought at the start.

**Decision**

OpenAGI stays out of the stack, on ADR-0001 grounds. ADR-0003's conclusion stands and its
licence argument is withdrawn — for personal use the licence is fine, and the spec says so.

**Two things are taken.**

**`repetition`.** OpenAGI's source lists its seventh axis as `repetition`, not `conflict`, and
it is the axis that finds work worth automating — which is the entire proactive half of what
this system is for. This is ADR-0014, still Proposed, and this ADR strengthens the case for
resolving it.

Note a detail that sharpens ADR-0014: OpenAGI's own **marketing page** says `conflict` while
its own **source file** says `repetition`. So the spec did not take the axis from a
third-party blog alone — the upstream project's front page says it too. When a project's site
and its code disagree, the code is the project.

**OpenAGI as an oracle, not a dependency.** Running it standalone, outside the stack, fed the
same signals, and comparing its verdicts against our table is a legitimate and cheap way to
tune the thresholds — spec §4 says the design is the valuable part, and this is how you get
the design's judgement without taking the daemon. It is a development tool, in the same
category as the coleam00 repositories in ADR-0015, and it must never become a runtime
dependency.

**Consequences**

- No upstream, and no upstream improvements. That cost is real and was real in ADR-0003; the
  correction period for our threshold table is however long it takes us to notice, and the
  corrections ledger plus the ratchet (ADR-0013) is the whole mitigation.
- If FRIDAY ever stops being personal use, PolyForm NC would have blocked adoption anyway,
  so this decision is also the durable one. That is a consequence rather than the reason.
- If OpenAGI ever ships Adaptive Scrutiny as a standalone library with no daemon, this ADR is
  superseded rather than edited, and the only remaining question would be the licence.

**Date**: 2026-08-07

---

## ADR-0022: OpenAGI does not replace Hermes

**Context**

OpenAGI's own comparison table shows it beating Hermes Agent on six rows. The question is
whether it should take the messaging and user-model slot.

The table is the vendor's marketing page. Spec §4 flagged this pattern about OpenAGI
specifically — "content marketing, same as the Vellum posts" — and a vendor's own comparison
is the strongest form of it, because the rows are selected rather than surveyed.

Checked against what the projects do:

| Row OpenAGI wins | What is actually true |
|---|---|
| Adaptive Scrutiny decision layer | Ours already. `scrutiny/policy.py`, 45 tests passing. Not an argument about Hermes |
| Persistent specialists (propagation) | Ours already. `propagate` plus the graph layer plus per-agent budgets |
| Corrections lock in, never repeat | Ours already. The ratchet, ADR-0013 |
| Watches you, learns patterns | Real and distinctive. Also an always-on process observing the screen of the machine that holds the mail, the messages and the finances |

Three of the four are rows this project fills itself, so they cannot be reasons to change a
different layer's owner.

**The row that decides it is scored as a tie.** "Multi-channel (SMS / Telegram / HTTP)" marks
both ✓. OpenAGI has roughly five channels. Hermes has 23, and that list contains **Matrix,
Signal, WhatsApp, iMessage and email**.

Spec §1 gives Matrix the messages-in row and calls it "the whole answer to 'it knows my
messages'." W1 and W2 route entirely through Conduit and mautrix bridges into Hermes. OpenAGI
ships no Matrix gateway, so adopting it does not swap a messaging layer, it deletes one.

Three further things Hermes carries that the table has no row for:

- **Honcho** produces the `profile.md` proposals. Spec §7, tier 1.
- **ADR-0007 is Hermes's design.** Spec §7 says so in as many words: "Hermes's design — when
  memory fills, the agent must consolidate before it can save anything new — is better than
  nightly compression. Adopt it." Bounded memory is imported from this project.
- **The Curator** is half of W8, and spec §8 configures it by name.

**Decision**

Hermes keeps the messaging and user-model row. OpenAGI does not replace it.

The trade on offer is: lose Matrix, Honcho, the bounded-memory design and the Curator; gain
screen observation and three capabilities already owned. ADR-0001's test — either the feature
belongs in the incumbent, or the incumbent is wrong and should be replaced — is not close to
met.

**One thing is taken.** Pattern detection from observing what you do is the genuinely novel
capability here, and it is the proactive half of what an ambient assistant is for. It enters
as a **source**, not a layer, and since it is screen observation it belongs with the vision
work ADR-0020 deferred past W8. When it is built, it is an ingest module feeding scored
signals like any other source, and it is subject to the same untrusted-content handling.

That is also where `repetition` earns its place as an axis, which is ADR-0014 and still open.

**Consequences**

- A vendor comparison table is not evidence about a layer this project already owns. When one
  argues for a change, the check is which rows are ours already and which rows were left out.
- Screen observation, whenever it arrives, is the largest new attack surface proposed so far.
  It gets an ADR of its own and it is measured against ADR-0006.

**Date**: 2026-08-07

---

## ADR-0023: Pipecat owns the voice pipeline transport; the policy stays ours

**Context**

`friday/voice/` was going to hand-roll real-time audio orchestration: VAD, turn-taking,
streaming buffers, backpressure, and interruption plumbing. That is the category of code that
is easy to write, hard to write correctly, and where being subtly wrong shows up as "it feels
laggy" rather than as an error.

ADR-0019 made it worse by specifying barge-in, which is the hardest part of that surface.

Pipecat (`pipecat-ai/pipecat`, **BSD-2-Clause**, Python 3.11+, installed with `uv`) is a
library for exactly this. It is a library and not a daemon, which is the same shape as
ADR-0011 and ADR-0012, so ADR-0001 is not engaged.

What matters is that its local path is first-class and its picks are already ours: local STT
including Whisper, local TTS including **Kokoro**. It handles VAD, turn-taking, streaming and
interruption natively, and streaming-first-sentence TTS is one of the three fixes W5 step 3
names for getting under 800ms.

**Decision**

Pipecat owns the **transport** of the voice pipeline. `friday/voice/` keeps the **policy**.

| Pipecat | `friday/voice/` |
|---|---|
| VAD, turn-taking, streaming, backpressure | The Resemblyzer speaker gate |
| Audio in and out, device handling | The clap trigger (spec §5) |
| Interruption plumbing — barge-in **phase 1** | Barge-in **phase 2**: the six-kind classification |
| Whisper and Kokoro adapters | Routing into scrutiny and graph checkpoints |

The split falls on a real seam. Phase 1 of barge-in is "speech detected during playback,
pause output" — generic real-time audio, and Pipecat does it. Phase 2 is "is this a
correction or a new task", which is about task semantics, scrutiny's `ask`, and ADR-0012's
checkpoints. No audio library has a concept for that and none should.

**Consequences**

- **Pipecat does not solve the AEC requirement.** Its echo cancellation path is Krisp Viva,
  which is a commercial dependency and fails spec §9. ADR-0019's hard requirement stands and
  is met the way ADR-0020 says: hardware AEC in the microphone, or `webrtc-audio-processing` /
  `speexdsp` in the path. Adopting Pipecat must not be mistaken for having handled this.
- A dependency lands in the latency-critical path. It is pinned, and W4 step 8's per-stage
  benchmark is what says whether it costs anything.
- Pipecat ships adapters for 20+ STT, 30+ TTS and 40+ cloud services. None are installed;
  optional dependencies are selected explicitly, and no cloud adapter may ever be.
- Python 3.11+ against our 3.12 pin: compatible, and the pin does not move for it.
- If Pipecat's pipeline shape ever fights the speaker gate or the clap trigger, the policy
  wins and the transport is replaced. That is the direction of the dependency and it is why
  the split is written down.

**Date**: 2026-08-07

---

## ADR-0024: Radicale and Odysseus do not overlap; ADR-0015 was wrong

**Context**

ADR-0015 left a row open: "Odysseus ships notes, tasks and CalDAV sync, which partially
overlaps W2's Radicale."

That was an error, and the error was mine: I read "CalDAV sync" as a CalDAV server.

Odysseus's calendar is a CalDAV **client**. It syncs *to* a CalDAV server and its own
documentation names the servers it syncs to — Radicale among them, explicitly.

**Decision**

Both stay, because they were never competing. Radicale is the **server**; Odysseus and DAVx5
are both **clients** of it.

```
    phone (DAVx5) ─┐
                   ├─→  Radicale  (127.0.0.1:5232, the CalDAV server)
    Odysseus      ─┘         ↑
                             └─ friday.ingest.caldav reads it (W2)
```

This is the better architecture and not merely the compatible one. A dedicated CalDAV server
is a small always-on thing; a workspace application is a large one. Putting the calendar
server inside the workspace means a restart of the workspace takes the calendar down, and W2
needs CalDAV working well before Odysseus is necessarily installed at all.

**Consequences**

- W2 is unchanged. Radicale stays where it is, in the phase where it is.
- Odysseus gains a calendar view of the same data, for free, by pointing at Radicale.
- ADR-0015's open row is closed. The other open row, Pipecat, is closed by ADR-0023.
- A note on method: that row said "not evaluated in depth" and it was right to say so. The
  cost of the error was one open question carried for a day; the cost of not marking it would
  have been a decision made on a misreading.

**Date**: 2026-08-07

---

## ADR-0014 — RESOLUTION

**Status: Accepted.** Appended rather than rewritten. **This resolution supersedes ADR-0002's
axis list and amends spec §4's.**

**What settled it was already in the config file.**

`config/scrutiny.yaml` declares the axes with types:

```yaml
  urgency:      { type: float }
  impact:       { type: float }
  novelty:      { type: float }
  risk:         { type: float }
  confidence:   { type: float }
  specificity:  { type: float }
  conflict:     { type: bool }     # <- not like the others
```

And the rule table uses it exactly once, alone, with no threshold:

```yaml
  - name: conflict_asks
    when: "conflict"
    action: ask
```

Every other axis is a graded 0.0-1.0 float compared against a tunable threshold. `conflict` is
a bare boolean guard. **It is a flag, not an axis**, and the file has been saying so from the
day it was written — the `type: bool` line is the tell, and the single thresholdless rule is
the confirmation.

That reframes the question. It was never "seven or eight axes." It was that one of the seven
was a different kind of thing wearing the same label.

**Decision**

`conflict` moves out of the axes and into `context`, where flags already live —
`context.speaker_verified` is the existing precedent and the same shape of thing: a fact about
the signal rather than a judgement about its content.

`repetition` takes the seventh axis slot, as a float, matching OpenAGI's source.

```
urgency . impact . novelty . repetition . risk . confidence . specificity
```

Seven axes, all floats, all thresholded. The rule table changes by one word:

```yaml
  - name: conflict_asks
    when: "context.conflict"      # was: "conflict"
    action: ask
```

**Why this is better than eight, beyond the bookkeeping.** The scorer is a 4B model
(spec §4), and asking it for seven homogeneous graded judgements is a materially easier task
than six graded judgements plus one boolean of a different kind. Homogeneity is worth real
accuracy at that model size, and the entire economics of the layer depend on the small model
being good enough.

**Why `repetition` is worth the slot.** It is the axis that finds work worth automating, which
is the proactive half of what an ambient assistant is for — spec §6 week 3's
`monitor_operative` and week 8's skill optimisation both want it, and neither has a signal to
key on today. It also gives ADR-0022's deferred pattern-detection source somewhere to land
when it arrives.

**One consequence that must be handled in the implementation, not left to care.**
`scrutiny/policy.py` resolves missing `context.*` keys to `False` rather than raising — which
is correct for `speaker_verified` on a Matrix message, where there is no speaker at all. For
`conflict` that default would **silently disable a guard**, which is precisely the failure the
module's own comments call the worst this table can have.

So: the daemon must always set `context.conflict` for any signal that passed through
retrieval, and `policy.decide` must reject a signal that reaches `conflict_asks` without the
key present. A guard that fails open is not a guard.

**What changes when coding resumes**

```
config/scrutiny.yaml    axes: conflict -> repetition (float, with a describe)
                        rule conflict_asks: when -> "context.conflict"
scrutiny/score.py       AXES tuple; Score.conflict:bool -> Score.repetition:float;
                        __post_init__ loses the bool special case - all seven validate
                        identically, which is the simplification this buys
scrutiny/policy.py      required-context check so conflict_asks cannot fail open
scrutiny/daemon.py      compute and always set context.conflict from the retrieval
                        that novelty already performs - no extra lookup
tests/test_policy.py    the conflict cases move from score to context
docs/                   spec §4 quote annotated; README, W7, ADR-0002 cross-referenced
```

Nothing above is done yet.

**Date**: 2026-08-07

---

## ADR-0025: Hardware profiles; nothing in the architecture depends on the box

**Context**

The box this is developed and tested on is not the box it will run on. The development box
has a weak GPU; the target has 24 GB and spec §1's model table assumes it.

The failure to avoid is obvious once stated and easy to walk into: writing the system against
the target and being unable to run any of it until the target exists, or writing it against
the dev box and hard-coding a small model somewhere that has to be found later.

The mechanism to avoid both is already in the stack and did not need inventing. Spec §8:
"LiteLLM is transport, the agent frameworks are policy." Aliases are indirection. Nothing in
`friday/` names a model — it names `daily`, `fast`, `embed`, `rerank`. A profile changes what
those resolve to and touches no calling code.

**Decision**

Two profiles in `config/profiles.yaml`, selected by `FRIDAY_PROFILE` or `/etc/friday/profile`,
defaulting to `target`. The default matters: a forgotten setting must degrade toward the
correct system, not away from it.

| | `dev` | `target` |
|---|---|---|
| VRAM floor | 0 — CPU-only permitted | 23000 MB |
| `daily` | the small model | Qwen 3.6 27B @ Q4 |
| `fast` | the small model | 4B router |
| `embed` / `rerank` | **bge-m3 / bge-reranker-v2-m3** | **identical** |
| Resident | fast, embed, rerank | + whisper, kokoro |

In `dev`, `daily` and `fast` deliberately resolve to the same model. On a small box a
separate 27B is not weaker, it is absent, and pretending otherwise produces something that
swaps to disk and looks broken rather than slow.

**A profile may change what runs. It may never change what is true.** `config/profiles.yaml`
carries both lists explicitly. The second one — the scorer's empty tool list, `agent/core`
ownership, allowlists and budgets, sensitivity routing, the bounded-memory block, the
writer/checker split, the speaker-gate floor, loopback-only binding — is not profile-scoped,
because a profile that could relax any of those would be a way to disable a security property
by choosing a config file.

**The part that makes dev genuinely useful, rather than a consolation.**

`bge-m3` and `bge-reranker-v2-m3` are small and identical across both profiles. Retrieval
quality is a property of those two models plus the pipeline, and both are the same on either
box. So:

- **Retrieval is comparable across profiles.** A chunking, expansion, fusion or rerank change
  that helps on dev helps on target. W3 — the long pole, the least exciting and most
  load-bearing week — is fully testable on a weak GPU.
- **Answer quality is not.** A 4B answering from perfect context is not a 27B answering from
  perfect context, and that difference is invisible in a retrieval score.

Therefore the 20/25 gate in spec §6 is a **target-profile gate**. Passing it on dev means
retrieval works; it does not mean the system is ready. Eval results record the profile that
produced them, and comparing a dev score against a target score is a bug in the report rather
than a finding.

**Consequences**

- Almost everything is buildable and testable before the target box exists: ingestion,
  chunking, the retrieval pipeline, the rule table, the graph engine, the supervisor, the
  tool allowlists, the voice path. What cannot be judged early is how good her answers are.
- Preflight reads the profile instead of a fixed floor, so `MIN_VRAM_MB` stops being an
  override people set to silence it and becomes a property of a named profile.
- `install/03-models.sh` downloads the profile's set. On dev that is a few GB rather than
  forty, which is most of W1's wall-clock time.
- Two profiles and not five. A profile per GPU tier would put spec §1's model table in a
  second place where it can drift. The table stays the source; a profile picks a row.
- Moving to the target box is: set the profile, run `install/03-models.sh`, restart. The
  vault, the index, the eval set and every config file move unchanged.

**Date**: 2026-08-07

---

## ADR-0026: MCP in both directions, and each is a different risk

**Context**

MCP is already the tool layer. `config/agents.yaml` carries the `tool_catalog`,
`friday/tools/serve.py` serves per-agent lists, and W5 builds it. What was never decided is
the two directions FRIDAY can face.

**Outbound** — FRIDAY *consumes* third-party MCP servers: filesystem, git, fetch, a database,
whatever someone publishes. This is the tempting one and it is a **supply-chain surface**.
An MCP server is code you did not write, running as a process, holding whatever access it was
given. ADR-0006's test applies without modification: does the boundary hold if the server
does exactly what an attacker wants? For a server that reads your mail, it does not.

**Inbound** — FRIDAY *exposes* herself as an MCP server, so Odysseus, a coding agent, or
anything else can call her memory and her calendar. Much lower risk: it is a read path into
data the caller is already trusted with, over loopback.

**Decision**

Both, with different rules.

**Outbound.** Third-party MCP servers are treated as untrusted code, not as tools:

- Each one is a `tool_catalog` entry with its own allowlist, matched on **name and input
  pattern** (ADR-0010), never a wildcard grant of everything a server advertises.
- A server's advertised tool list is **data, not configuration**. It is compared against the
  allowlist at registration; new tools appearing after an upgrade are refused rather than
  adopted, because a server that grows a capability is indistinguishable from one that was
  replaced.
- Anything touching the network or the filesystem runs in the OpenHands container boundary
  or not at all. In-process policy is what ADR-0010 rejected OpenCode for.
- `scorer` never gets one. `tools: []` is the narrow point the security model rests on
  (ADR-0006) and it stays empty forever.

**Inbound.** A read-only MCP server over `memory_read`, `calendar_read` and the inbox, bound
to loopback, one virtual key per consumer. No `vault_write`, no `shell`, no `git`. A caller
that wants FRIDAY to *do* something goes through scrutiny like any other signal, which is the
whole point of having a triage layer.

**Consequences**

- The allowlist gains a registration-time check it did not need when every tool was ours.
- Adding an outbound server is a config change plus an ADR if it reaches anything sensitive,
  and "it is just an MCP server" is not an argument — it is a process with your data.
- The inbound server means Odysseus can query the vault without a second retrieval stack,
  which is ADR-0001 working in our favour for once.
- Built in W5 with the rest of the tool layer. Nothing is needed before then.

**Date**: 2026-08-07

---

## ADR-0027: No Supabase; SQLite and Qdrant stay

**Context**

Whether the storage layer wants something Supabase-shaped, self-hosted: Postgres, auth,
realtime, storage, REST, and pgvector in one box.

Taken at face value the answer is immediate — Supabase would replace **two** rows of the
spec §1 table (SQLite+FTS5, Qdrant) and add three things this system does not have a use
for. Auth is a single user gated by a voiceprint and a mesh. Storage is a markdown vault.
A REST API to your own data on your own machine is a layer between you and a file.

The question worth actually asking is the smaller one hiding inside it: **would Postgres with
pgvector beat SQLite plus Qdrant?** That is a fair question and the answer is still no, for
reasons that are about operations rather than features:

- SQLite is one file. `make backup` is a `tar`, and a consistent snapshot is a file copy.
  Postgres is a daemon with a dump procedure, a WAL, a version upgrade path, and a tuning
  surface — on a box whose entire premise is being fixable at 3am by one person.
- Zero ops is a feature here, not a limitation. Spec §0's whole argument is against
  accreting things that need weekend attention.
- pgvector's real advantage is transactional consistency between vectors and rows. Our
  vectors are *derived*: the episodic log and the vault are the sources of truth, and the
  index is rebuildable from them. A rebuildable derivative does not need a transaction.

**Decision**

Storage stays as spec §1 has it: SQLite + FTS5 for structured and keyword, Qdrant for
vectors, markdown for the vault. No Postgres, no Supabase.

**One real problem is acknowledged rather than dismissed.** The SQLite files have multiplied:
`episodic.db`, `sources.db`, `scrutiny.db`, `litellm.db`, the graph checkpoints, `skills.db`.
That is sprawl, and it arrived one reasonable decision at a time.

The rule going forward: **a new `.db` file needs a reason that is not "it is a different
concern."** Files split when they have different *lifecycles* — `episodic.db` is durable and
`sources.db` is a 30-day landing zone, which is a real difference. `scrutiny.db` and a future
`skills.db` are both append-only ledgers with the same lifecycle and belong together.
Consolidating them is a W7 cleanup, not a W1 one.

**Consequences**

- No auth layer, ever, on the storage tier. The boundaries are the mesh, the voiceprint and
  the filesystem, and adding a third would be a fourth thing doing 60% of a job.
- The realtime need — the wall surface watching agent state — is served by
  `friday/output/state.py` as a stream, not by a database subscription.
- If the corpus ever genuinely outgrows SQLite, that is a measurement and this ADR is
  superseded with the number attached. Spec §10 predicts trouble at 10k *documents*, which is
  a retrieval problem the reranker addresses, not a storage-engine problem.

**Date**: 2026-08-07

---

## ADR-0028: The repository is forkable; personal data never enters it

**Context**

Whether this repo should be structured so someone else can fork it, or whether it is one
person's install.

It was already close, by accident rather than design: `.gitignore` keeps out
`vault/`, `db/`, `eval/questions.yaml`, `eval/results/`, secrets and agent-written files. The
two things that survive are the ones that matter most — `eval/questions.yaml` is 25 questions
about your life, and the vault is your life.

But two tracked files carried personal values: `principal = "ak"` in `config/friday.toml` and
`/home/ak/documents` in `config/sources.yaml`. Small, and exactly the kind of thing that makes
a fork start with a confusing diff.

**Decision**

The repository is forkable. Concretely:

- **Tracked config ships generic.** `principal = "CHANGEME"`, and `sources.yaml` watches only
  the vault. `install.sh` has a "Make it mine" step that fills in the name and offers the
  system timezone.
- **`timezone` is prompted for, not defaulted quietly.** UTC left in place makes every
  calendar answer wrong by a fixed offset, and it reads as a retrieval problem for about two
  days. The dashboard flags it as `warn` rather than `done`.
- **No personal data enters the repository, ever** — not in a config, not in an example, not
  in a test fixture. `eval/questions.example.yaml` is generic and gates nothing.
- **The spec and the ADR log are the fork's real value.** Someone forking this gets the
  reasoning, which is the part that took the time. The code is downstream of it.

**Consequences**

- A fork's first run is `bash install.sh`, and the personalisation step is a dashboard row
  rather than a README instruction someone skips.
- `principal = "CHANGEME"` fails nothing at load, deliberately: the system works without a
  name and is slightly generic, which is the right amount of consequence.
- ADRs referring to "you" and "your mail" read fine in a fork, because the reader is the
  operator either way.
- This does not make it a product. There is no support, no compatibility promise, and every
  `# VERIFY:` marker is still the fork's problem to check.

**Date**: 2026-08-07

---

## ADR-0029: Prompt assembly order is frozen-then-volatile

**Context**

Spec §7 requires three things be present on every turn: `profile.md`, the current date and
time, and today's calendar. Assembled naively — in the order the spec lists them — that
places a value that changes every second in front of everything else.

KV-cache reuse is a **prefix match**. Any byte change invalidates everything after it, so a
datetime at the front means every prompt is a cold prefix, forever. This is a named
anti-pattern in Anthropic's caching guidance (`datetime.now()` in the system prompt) and
llama.cpp's prefix cache behaves the same way.

W5 has to find 400ms. This is some of it, for free.

**Decision**

Prompt assembly is ordered by **rate of change**, not by the order spec §7 lists things:

```
  frozen        system preamble, profile.md, tool definitions      <- cache breakpoint
  ------------------------------------------------------------
  volatile      current datetime . today's calendar
                retrieved chunks . the question
```

`friday.memory.retrieve.build_context` owns this and it is the only place the order is
decided. The rule for anything added later: if it changes between two consecutive turns, it
goes below the line.

**Consequences**

- The tool list must be **deterministic** — sorted, and stable across turns. A per-turn tool
  set is a cache miss dressed as a feature, which is also why ADR-0026 refuses to adopt a
  server's advertised tools dynamically.
- `profile.md` being frozen is now a performance property as well as a design one. An
  auto-updating profile would invalidate the prefix on every edit; ADR-0007's
  `auto_apply_proposals: false` already forbids that for a different reason.
- Verification is a number, not a belief: llama-server reports cache reuse, and a hit rate
  near zero across identical-prefix turns means something volatile crept above the line.
- Sensitivity filtering happens inside the retrieval query (ADR-0008), so the frozen prefix
  never varies by what the caller is allowed to see.

**Date**: 2026-08-07

---

## ADR-0030: Context management within a run, distinct from memory across runs

**Context**

FRIDAY has four tiers of memory and all four are about persistence *across* sessions. Nothing
handles a single run growing past its window.

W7's researcher has a 150,000-token budget and a tool allowlist that reads mail, files and
the index. It will fill its context and then fail — and the supervisor will record a budget
kill, which is technically correct and diagnostically useless.

Three mechanisms are usually collapsed into one word. They are not the same thing:

| | What it does | Loses |
|---|---|---|
| **Clear** | Drops stale tool results and intermediate output | The detail, deliberately |
| **Compact** | Summarises earlier context into a shorter form | Fidelity, gradually |
| **Memory** | Persists across runs entirely | Nothing — different axis |

**Decision**

`friday/graph/` owns clear and compact; the memory tiers keep owning persistence.

**Clear first, compact second.** Clearing is deterministic and lossless in the way that
matters — a tool result already consumed is dead weight, and dropping it costs nothing.
Compaction is a model call that loses fidelity, so it runs only when clearing was not enough.

**A compaction is a graph node like any other**, which means it checkpoints (ADR-0012) and
is subject to the writer/checker rule if it writes anything. A run that compacts and then
dies is resumable from after the compaction.

**Never compact `profile.md` or the injected datetime.** They live above the cache line
(ADR-0029) and are re-injected whole every turn regardless.

**Consequences**

- The graph state carries a token estimate per node, which the supervisor already needs for
  budgets — one counter serves both.
- Compaction is lossy and will occasionally lose the thing that mattered. The mitigation is
  that the episodic log is untouched: a compacted run can be reconstructed from tier 2.
- W7's overnight run stops being "it died" and becomes "it compacted twice and finished."

**Date**: 2026-08-07

---

## ADR-0031: Progressive disclosure for skills and tools

**Context**

W8's stated failure is a library of four hundred skills where nobody can say whether any of
them got better. There is a second failure underneath it that arrives sooner: every skill
description loaded into every prompt.

At thirty skills that is a nuisance. At three hundred it is the whole context window, and it
lands on the frozen side of ADR-0029's cache line, so it is paid on every turn.

**Decision**

Skills and tools load in two stages. **Names and one-line descriptions** are in context;
**bodies load on demand** when the description matches the task.

This is the same shape as the `SKILL.md` convention — the description sits in context by
default, the full file is read when the task calls for it — and it is why `agent/skills/` is
a directory of folders rather than one file.

Two rules that make it work rather than just sound good:

**Descriptions are the interface.** A skill whose description does not say *when* to use it
cannot be selected without loading it, which defeats the mechanism. This is the same
requirement ADR-0026 puts on MCP tool descriptions and it is the part that rots first.

**Loading appends; it never rewrites the prefix.** A loaded skill body goes below the cache
line with the retrieved chunks. Rewriting the frozen prefix to insert a skill would invalidate
the cache — the exact thing ADR-0029 exists to prevent.

**Consequences**

- The Curator's job (W8) gains a measurable target: a description that never causes a load
  is either wrong or the skill is dead.
- Skill selection becomes a retrieval problem over descriptions, which means it can be wrong,
  which means it belongs in the corrections ledger like every other classification.

**Date**: 2026-08-07

---

## ADR-0032: A secret in the vault outlives the fix

**Context**

`docs/weeks/W4.md` handles a credential reaching the index: purge the episodic log, purge
Qdrant, fix `exclude_globs`, re-run. That is right and it is incomplete.

**The vault is a git repository.** A secret consolidated into a note and committed is in the
history. `git revert` adds a commit that removes it from the working tree and changes nothing
about the object that still contains it. Every clone and every backup carries it. Rotating
the credential is necessary and does not undo the disclosure.

ADR-0005 spends real design effort keeping credentials away from her — root-owned secrets, a
helper she cannot read, one key per unit. A secret that arrives by the front door and is then
preserved forever by our own revision control defeats all of it.

**Decision**

`friday.memory.vault` gains a **redact** operation, distinct from delete:

- Removes the content from the working tree **and** rewrites history so the object does not
  survive in the repository.
- Preserves an audit record — when it was redacted, which note, which run wrote it — because
  the fact that a secret was disclosed is exactly what you must not lose.
- Force-pushes to the Forgejo remote, and the runbook says to treat every clone and every
  snapshot in `backups/` as compromised until re-taken.

Redaction is a **human action**. She does not redact her own vault: a process that can
rewrite its own history can hide what it did, which is the same argument as ADR-0004 applied
to the record rather than the loop.

**Consequences**

- History rewriting breaks the supervisor's revert-to-pre-run-commit if it happens mid-run.
  Redaction requires the managed units stopped, which the runbook states.
- `make backup` snapshots contain the pre-redaction history. The tarballs are the reason the
  runbook says to re-take them, and the reason it says an untested backup is a belief.
- This is a real capability she does not have and a human does. That asymmetry is the point.

**Date**: 2026-08-07

---

## ADR-0033: Scheduled work keeps run records and pauses itself

**Context**

The digest, consolidation and ingest are systemd timers. A timer tells you a unit ran and
what its exit code was. It does not tell you what the run *did*, and a timer that fails every
night at 03:00 fails every night at 03:00 forever.

Spec §10 warns that retrieval degrades quietly. A scheduled job degrading quietly is the same
failure with a schedule attached.

**Decision**

Every scheduled run writes a **run record**: what fired it, when, what it produced — notes
written, rows consolidated, the resulting graph run id — or a typed error if it produced
nothing. The record is durable and independent of the journal, because the journal rotates
and the question "when did the digest last actually work" outlives it.

**Repeated non-recoverable failure pauses the timer** rather than retrying nightly. A missing
model, a config that no longer validates, a vault that will not commit — none of those fix
themselves, and the pause goes to the inbox as an `ask`.

Recoverable failures — a locked database, a model still loading — retry on the next tick and
do not count toward the pause.

**A manual run must be possible while paused.** Testing the fix is the entire point of
pausing, and a pause you cannot test out of is an outage.

**Consequences**

- One more table, in `scrutiny.db` alongside the decisions ledger — same lifecycle, same
  append-only shape, and ADR-0027's rule says that is where it belongs rather than in a new
  file.
- The distinction between recoverable and non-recoverable has to be made per error, and
  getting it wrong in the safe direction means retrying forever. Default to recoverable and
  promote errors to non-recoverable as you meet them.
- W3's "the vault grows without you writing in it" becomes checkable from a table instead of
  inferred from `git log`.

**Date**: 2026-08-07

---

## ADR-0034: Rubrics for tasks, and the grader is not the writer

**Context**

ADR-0013 established that a writer never checks its own work. It did not say what the checker
checks *against*, and for the consolidator the answer was implicit: does every claim appear
in the source rows.

That does not generalise. When `propagate` hands a task to the researcher, "done" is
undefined — the specialist decides for itself when it has finished, which is the same
inflation ADR-0013 rejects, moved from output quality to completion.

**Decision**

A propagated task carries a **rubric**: explicit criteria, gradeable independently.

The bar is concrete versus vague, and it is the whole difference between a rubric and a
wish. "A comparison of the March quote against two current ones, with dates and totals" is
gradeable. "A good summary of the roof situation" is not — and a grader scoring vague
criteria produces noise that looks like signal.

A **separate grader**, different agent, scores each attempt and returns per-criterion gaps.
Failing criteria go back as specific work, not as "try again". Bounded iterations, and
exhausting them ends in `ask` — never in a quiet declaration of success.

**Consequences**

- Writing a rubric is work, and it front-loads thinking that would otherwise happen while
  reading a disappointing result. That trade is the point.
- The eval set is the same idea one level up: 25 questions with known answers is a rubric for
  retrieval, and it is already the model for this.
- A task with no writable rubric is a signal that it should be `ask` rather than `propagate` —
  which is what `urgent_and_undetermined_asks` already says from the other direction.

**Date**: 2026-08-07

---

## ADR-0035: Answers cite their sources inline

**Context**

Spec §7 requires provenance be carried "so she can say 'you told me this in March, it may be
stale'". `carry_provenance: true` carries it as far as the context window and then it stops:
the answer is prose, the sources are a list underneath it, and nothing connects a specific
claim to a specific note.

That gap is where the week-6 novelty cliff lives. "You notice how often she's subtly wrong"
is hard to act on when checking one claim means re-reading eight chunks to find which one it
came from.

**Decision**

Claims carry their source inline. A retrieved chunk that produced a claim is named at that
claim, with its note and its date — not collected in a footer.

Three consequences follow that are worth stating as rules:

- **A claim with no citable source is stated as inference, not as fact.** She knows which
  chunks she was given; a sentence traceable to none of them is her reasoning, and saying so
  is the difference between a wrong answer you can catch and one you cannot.
- **A source older than `stale_after_days` is qualified where it is used.** That is spec §7's
  sentence, applied at the claim rather than at the response.
- **Citations are how corrections get cheap.** The path from "that's wrong" to the note that
  caused it becomes one click, which is what makes W6's maintenance half tractable.

**Consequences**

- More verbose answers. Voice turns suppress inline citation and surface it on request,
  because reading identifiers aloud is unusable.
- A model can attribute a claim to the wrong chunk. A citation is a claim about provenance
  and can be wrong like any other, so it is checkable rather than trusted.

**Date**: 2026-08-07

---

## ADR-0036: The knowledge graph is derived from the vault, not authored beside it

**Not to be confused with ADR-0012.** That is the **agent** graph — how work moves. This is
the **knowledge** graph — how facts relate. Same word, different layer, and conflating them
is the reason this ADR says so in its first line.

**Context**

Spec §7's retrieval is vector plus keyword, fused and reranked. That answers "what did I say
about the roof" well and hits a ceiling on anything requiring a hop:

> "What did the person who quoted the roof say about timing?"

Vector search finds notes similar to the sentence. It has no representation of *Sam quoted
the roof*, so it cannot get from the roof project to Sam to what Sam said. It retrieves
roof-shaped text and hopes the answer is in it. That failure is quiet — the answer looks
plausible and is assembled from the wrong notes.

The 2026 consensus in the retrieval literature is hybrid: vectors for breadth, graph for
depth, memory for continuity. Reported gains are material — precision improvements around a
third, and large token reductions from retrieving a few connected facts instead of many
similar paragraphs. Treat those numbers as directional; the mechanism is the part to trust.

**What makes this cheap here, and it is the whole decision.**

ADR-0017 already requires `[[wikilinks]]` in every generated note. **Those links are edges.**
`people/sam.md` linking `projects/roof.md` is an assertion that the two are related, written
by the consolidation loop as a side effect of a convention adopted for a different reason.

So the graph is not a new corpus to author, a new database to run, or a new thing for her to
maintain. It is a **projection of the vault** — derived on consolidation, rebuildable from
scratch at any time, and correct by construction if the vault is correct.

**Decision**

A knowledge graph, **derived** from the vault, never authored independently.

- **Nodes** are vault notes. `people/`, `projects/`, `ideas/`, `daily/` — the four directories
  spec §7 already names are the node types.
- **Edges** are wikilinks, plus a small typed set the consolidator can assert explicitly
  (`mentioned_in`, `attended`, `owns`, `superseded_by`) when the relationship is stronger
  than "these are related".
- **Retrieval gains one stage**, inserted where it belongs in spec §7's pipeline:

```
  expand -> keyword + vector (30 each) -> dedupe
         -> GRAPH EXPANSION: follow edges 1-2 hops from the entry points
         -> rerank to 8 -> recency boost
```

Vector search finds the entry points; the graph reaches what is connected to them. Depth
capped at two hops — three pulls in the entire vault, because everything in a personal corpus
is eventually connected to everything.

- **Storage is SQLite**, two tables beside the FTS5 index. ADR-0027 asked for a reason beyond
  "different concern" before adding a file; this shares the episodic lifecycle and does not
  get its own. No graph database — a personal vault is thousands of nodes, and a second
  daemon for a join is ADR-0001.
- **Rebuildable.** `--rebuild-graph` drops and re-derives from the vault. A corrupt graph is
  never a data-loss event, which is what makes the whole thing safe to be wrong.

**Timing: W3, and it is gated.** It goes in after the retrieval pipeline is measured, not
beside it. Build the pipeline, get the eval to 20/25, record that number — *then* add graph
expansion and re-run. If it does not move the score it comes out. The eval set exists to make
exactly this decision, and adding two retrieval changes at once means neither can be
attributed.

**Consequences**

- No new authoring burden and no new daemon. The cost is the expansion stage and a derivation
  pass on consolidation.
- Graph expansion widens the candidate set, which the reranker then has to cut back down.
  `min_rerank_score` is the guard and it matters more with this on, not less.
- A wrong edge produces a confidently wrong multi-hop answer, and ADR-0035's inline citations
  are what make that catchable — the answer names the notes it traversed.
- Sensitivity filtering must apply to traversal, not just to the initial query. An edge from
  a permitted note to a restricted one is a path around ADR-0008, and filtering after
  traversal leaks existence through the shape of the result.

**Date**: 2026-08-07

---

## ADR-0037: The vault is OKF-shaped; the schema is ours

**Context**

The Open Knowledge Format is a specification for storing knowledge as a directory of markdown
files with YAML frontmatter and explicit links between concepts, git-versioned and
tool-agnostic. It formalises the "LLM wiki" pattern — an agent maintaining a curated
knowledge base it continuously reads and improves, rather than re-retrieving raw documents
every time.

That is spec §7's tier 3 and the consolidation loop, described by someone else. The
convergence is worth noting because it was independent: the spec did not borrow this.

Two things counsel against depending on it, and both are the same caution spec §4 applies to
OpenAGI. **The published descriptions disagree with each other** — one source gives the
required frontmatter as `type` and `title`, another as `id` and `category`. And **the
canonical specification is not locatable**: the available material is secondary coverage and
one community tool, not a normative document. A format whose required fields differ by
write-up is not a format to hard-depend on yet.

**Decision**

Adopt the **shape**; own the **schema**.

The vault stays what ADR-0017 made it — plain markdown, YAML frontmatter, `[[wikilinks]]`,
git-versioned, readable by `cat` and `grep`. That is already OKF-shaped, and staying
deliberately close to the convention costs nothing:

- One concept per note, atomic and self-contained.
- Frontmatter carries a stable identifier, a type, timestamps and provenance — the fields
  every version of the description agrees on, under the names spec §7 already requires.
- Links are explicit and bidirectional where the consolidator can determine it, which is what
  ADR-0036 derives the graph from.

What is **not** adopted: any dependency, any tool, any required field we would have to keep
in step with a moving specification. If OKF stabilises and a canonical schema appears,
conforming is a frontmatter migration over a directory of markdown files — a morning's work,
which is the point of not depending on it now.

**Consequences**

- If OKF becomes the interchange format it intends to be, the vault is portable into it
  cheaply, and someone else's knowledge base is importable.
- The vault remains readable with no tooling at all. That property is worth more than
  conformance and is the reason ADR-0017 refused to require Obsidian either.
- A third external convention now shapes the vault — Obsidian, OKF, and our own provenance
  requirement. They agree today. If they diverge, **ours wins**, and the reason is that spec
  §7 requires provenance and neither of the other two does.

**Date**: 2026-08-07
