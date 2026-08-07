# Phase guides

One file per phase of spec section 6's build order. They are the operational form of that
table: the spec says *what* is done and *when it is done*, these say *how*.

**Do not reorder.** Spec section 6 says it in bold and it is the single most ignored line in
the document. Voice before memory is the mistake everyone makes, because voice demos well in
week one and memory does not demo at all until it works. Week 2-3 is the least exciting and
the most load-bearing.

| Guide | Spec section 6 rows | Done when |
|---|---|---|
| [W1](W1.md) | week 1, both rows | You chat locally, and you text FRIDAY from your phone |
| [W2](W2.md) | week 2 | She answers "what's my week look like" |
| [W3](W3.md) | week 2-3, week 3 | 20/25 on your own eval questions; the vault grows without you writing in it |
| [W4](W4.md) | week 4, first half of 4-5 | Eval score holds after each new source; you hear her speak |
| [W5](W5.md) | second half of 4-5, week 5 | Under 800ms, hands-free, voice-gated. She can act, and you can kill her |
| [W6](W6.md) | week 6 | She shuts up and takes notes on command |
| [W7](W7.md) | week 7 | She works overnight and reports at breakfast |
| [W8](W8.md) | week 8+ | Her skills improve measurably, not just numerously |

Spec section 6 spans two weeks twice, at 2-3 and at 4-5. The split used here:

- **2-3.** W2 is the eval set and the two week-2 sources. W3 is the index, the retrieval
  pipeline and the consolidation loop, which is where the 20/25 gate actually lands.
- **4-5.** W4 is the four new sources plus speech in and speech out. W5 is the wake path,
  the speaker gate, tools, the sandbox and the supervisor. W5 is the heaviest week in the
  schedule and the natural place to slip; the split point inside it is after the voice
  section.

## Conventions

Every guide has the same eight sections, in this order: Goal, Done when, Prerequisites,
Steps, Files touched, Verification, Failure modes, Do not do yet.

**Every command is copy-pasteable and idempotent.** Running a whole guide twice must leave
the box in the same state as running it once, and must not fail partway through the second
run. This is not a nicety. Half of these steps are first performed at 1am, interrupted, and
resumed the next evening from a state nobody wrote down. `pacman -S --needed`,
`install -d`, `systemctl enable --now`, and `tee` of a whole file are idempotent;
`>>` into a config, `useradd` without a guard, and `git clone` without a check are not.

**Arch only.** `pacman` for the repositories, `paru` for the AUR, `uv` for Python. Never
`apt`, never `pip install` outside a uv-managed environment, never `sudo pip`.

**`# VERIFY:`** marks a value this document cannot be authoritative about — an upstream
repository name, a model file, a CLI flag belonging to a project that is not ours. Spec
section 1 says it directly: "Verify current picks before downloading." A guide that
confidently states a Hugging Face repository id that turns out not to exist wastes more of
your evening than one that tells you to go and look. Check it, then write down what you
found in the guide, and the marker goes away.

**Preflight gates every phase.** `make preflight` before you start and again before you call
a phase done. It reads and never changes anything, so running it is free.

```bash
make preflight
```

Its failures are the entry condition for the phase you are about to start, and its warnings
are things to notice rather than things to fix now. A `FAIL` on a service that phase has not
installed yet is expected; each guide's Prerequisites section says which.

## Port map

Fixed across every phase, and checked by preflight. Everything binds `127.0.0.1`. Spec
section 9: no port forwarding, ever, and preflight fails on anything listening off-loopback.

| Port | Owner | Phase |
|---|---|---|
| 3000 | Langfuse | W1 |
| 4000 | LiteLLM | W1 |
| 5232 | Radicale | W2 |
| 6333 | Qdrant | W3 |
| 7424 | Conduit | W1 |
| 8080 | llama-server, `daily` | W1 |
| 8081 | llama-server, `fast` | W1 |
| 8082 | llama-server, `embed` | W1 |
| 8083 | llama-server, `coder`, on demand | W5 |
| 8084 | llama-server, `vision`, on demand | W4 |
| 8085 | llama-server, `rerank` | W1 |
| 8123 | Home Assistant | W4 |

## If a phase will not go green

The rule is to stop, not to skip forward. Each guide's Failure modes section covers what
actually goes wrong; spec section 10 covers what goes wrong later. Phases depend on the ones
before them in ways that are not always obvious from the file list — `novelty` in week 7 is
meaningless against an empty vault, and the week 5 supervisor cannot gate the known-good tag
without the week 3 eval.
