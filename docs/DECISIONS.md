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
| 0014 | The seventh axis, and whether there is an eighth | spec §4 | **Proposed** |
| 0015 | Candidates evaluated and cut, August 2026 | spec §3 | Accepted |

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
