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
