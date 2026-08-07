# Why everything is here

Every component, every package, and the reason it earned its place.

Three documents cover different questions and this is the third:

| Question | Document |
|---|---|
| What do I install, and in what order? | [`INSTALL.md`](INSTALL.md), [`weeks/`](weeks/) |
| Why was this *decided*, and what was the argument? | [`DECISIONS.md`](DECISIONS.md) |
| **Why is this specific thing on my system?** | **this file** |

The rule underneath all of it is spec §0: **one owner per layer.** "The failure mode of this
project is installing four things that each do 60% of the job and spending your weekends
reconciling them." Nothing below overlaps anything else below. Where two candidates were
close, the loser is named, because knowing what was rejected is what stops it being
re-installed at 2am.

---

## 1. The stack

| Layer | Choice | Why it won | Runner-up, and why not |
|---|---|---|---|
| Inference | **llama.cpp** | The standard. GGUF, CPU fallback, one binary per model, no framework | vLLM — better throughput, worse single-user latency and much heavier. Spec §1: "only when you need throughput" |
| Model routing | **LiteLLM** | One endpoint, aliases, fallback, per-key spend caps. Aliases are what make ADR-0025's profiles free | Talking to llama-server directly — then every caller hard-codes a port and a profile is impossible |
| Agent runtime | **OpenJarvis** | Local-first by design, DSPy skill optimisation, scheduled *and* continuous agents. Stanford Scaling Intelligence Lab | AutoGPT-lineage runners — cloud-shaped, no local trace-learning loop |
| Messaging + user model | **Hermes Agent** | 23 gateways from one process including Matrix. Honcho user modelling. Bounded memory — which ADR-0007 is *imported from* | OpenAGI (ADR-0022): ~5 channels, no Matrix, and adopting it drags in six overlapping layers |
| Agent/tool library | **pydantic-ai** | Typed tools, validated args, strict structured output — exactly `parse_score`'s contract. A library, not a layer (ADR-0011) | Hand-rolled — several hundred lines of the least interesting code, where being subtly wrong is invisible |
| Proactive triage | **ours** (`scrutiny/`) | ~200 lines, and the threshold table is tunable against *your* corrections rather than someone's defaults (ADR-0021) | OpenAGI — right design, but it is a daemon owning seven layers to get one |
| Workflow graph | **pydantic-graph + `friday/graph/`** | Typed nodes and edges free with pydantic-ai; we add checkpoints, resumption and the human gate (ADR-0012) | Archon — needs a Claude Code binary (cloud), ships PostHog telemetry, overlaps OpenHands. LangGraph — better persistence, second graph engine |
| Autonomous coding | **OpenHands** | The container. ADR-0010 gave it the slot for the Docker boundary, not the permission model | OpenCode — genuinely better permission config, but in-process policy with no filesystem isolation |
| Workspace UI | **Odysseus** | Chat, agents, deep research, email, notes, CalDAV *client*, hardware Cookbook | Any chat frontend — spec §3 cut them all; Odysseus is one and does more |
| Wall surface | **Next.js + Tailwind + shadcn** | Renders *agent* state — running graphs, pending gates. Not entities (ADR-0016) | Home Assistant dashboards — built for entities; a paused graph node is not an entity |
| Voice transport | **Pipecat** | VAD, turn-taking, streaming, barge-in phase 1. BSD-2, Python, local Whisper and Kokoro first-class (ADR-0023) | Hand-rolled — real-time audio is easy to write and hard to write correctly |
| STT | **faster-whisper large-v3-turbo** | Already the fast variant. One process on the GPU (ADR-0018) | `base.en` — faster, and loses proper nouns. Mishearing "Sam" as "Sarah" is a confident retrieval against the wrong person |
| Wake | **openWakeWord + clap** | Two triggers that fail differently. A clap *physically cannot* false-trigger from speech | Wake word alone — false-fires all evening with a television on |
| Speaker auth | **Resemblyzer** | Voice as an auth factor. Without it anyone in earshot commands a system with shell access | Nothing — spec §5 is explicit this is a real security control |
| TTS | **Kokoro-82M** | Fast, local, natural, small enough to stay resident | Larger TTS — the resident set is a latency budget, not a memory note |
| Vectors | **Qdrant** | Payload filtering *inside* the query, which ADR-0008 requires | pgvector — see ADR-0027; our vectors are derived and rebuildable |
| Structured + keyword | **SQLite + FTS5** | One file, zero ops, backup is a `tar`. Public domain | Postgres — a daemon to tune, back up and upgrade, on a box whose premise is being fixable at 3am by one person |
| Messages in | **Matrix (Conduit) + mautrix** | Spec §1: "the whole answer to 'it knows my messages'" | Per-platform APIs — one integration per service, each breaking separately |
| Calendar | **Radicale** | A dedicated CalDAV *server*, ~one systemd unit. Odysseus and DAVx5 are both clients of it (ADR-0024) | Calendar inside the workspace — restarting the workspace takes the calendar down |
| Mail | **mbsync + notmuch** | Network handling and credentials stay entirely outside the agent process. ADR-0005 applied to mail | An IMAP client in-process — puts credentials and a network stack inside the thing reading hostile input |
| Tracing | **Langfuse** | Self-hosted. Spec §1: "you will need this at 3am" | Logfire — pydantic-ai integrates with it and it is hosted by default. ADR-0011 declines it |
| Git | **Forgejo** | Branch only, human merge. Somewhere to review before merging | Bare remote — no review surface |
| Secrets | **age + sops** | Small, auditable, file-based. No daemon, no server | Vault — a service to run and unseal to hold four secrets |
| Network | **WireGuard / Headscale** | Spec §9: never a port forward | Reverse proxy + TLS — an open port on a box holding your entire life |
| Supervisor | **ours**, ~150 lines | Different user, outside her reach. A supervisor with enough surface to have its own bugs is not one | systemd alone — restarts things; does not eval-gate a rollback tag |

---

## 2. Arch packages

`install/00-arch-packages.sh`. Every one, with what actually breaks if it is missing.

### Toolchain

| Package | Why it is here | Without it |
|---|---|---|
| `base-devel` | `makepkg` needs it for every AUR build | No AUR at all — no llama.cpp, no Conduit, no bridge |
| `git` | Cloning, and the vault and `work/` are git repositories | Consolidation cannot commit, so the supervisor cannot revert a bad run |
| `cmake` `ninja` `pkgconf` | Building llama.cpp from source when the AUR package builds rather than downloads | The llama.cpp build fails partway |

### GPU

| Package | Why it is here | Without it |
|---|---|---|
| `cuda` | `nvcc` and the runtime libraries llama.cpp links against | Everything runs on CPU **and looks fine** — thirty times too slow, and you will not notice for two days |
| `cudnn` | Deep-learning primitives. CTranslate2, under faster-whisper, wants it | STT falls back to a slower path or refuses to load |
| `nvidia-utils` | `nvidia-smi` and driver userspace | Preflight cannot measure VRAM; you are flying blind on the resident set |

Installed even on the `dev` profile. A few hundred MB, and it means dropping a card into the box later does not need a second install pass.

### Python

| Package | Why it is here | Without it |
|---|---|---|
| `uv` | Interpreter management, the venv, and the lock. Never `pip` outside it | No reproducible environment |
| `python` | The *system* interpreter, for install scripts that run **before the venv exists** | `install/lib.sh` cannot resolve the profile, so no script knows which box it is on |
| `python-yaml` | `profile_get()` in `lib.sh` parses `config/profiles.yaml` **before** the venv exists | Same. Deliberately not `yq` — adding a tool to read one number is what makes an install fail on a fresh box |
| `python-notmuch` | notmuch's bindings ship with the C library | `pip` **cannot** install this — it binds a library pip does not have |

### Secrets

| Package | Why it is here | Without it |
|---|---|---|
| `age` | The encryption backend, and the identity at `secrets/age.key` | Nothing can be encrypted; the master key would sit in cleartext |
| `sops` | Encrypts *values*, so an encrypted file still diffs sensibly | You would encrypt whole files and lose reviewable config |

### Operational

| Package | Why it is here | Without it |
|---|---|---|
| `jq` | Every verification block in every week guide parses JSON with it | Verification steps become unreadable |
| `sqlite` | The `sqlite3` CLI, for the verification queries in W2–W8 | You cannot check whether ingestion actually landed |
| `ripgrep` | Fast search across the vault and the repo | Slower, works |
| `rsync` | `make backup` | Backups become a `cp` with no incremental path |
| `gum` | The installer UI (`install/ui.sh`) | The installer still runs — every function degrades to plain output, which is deliberate, because gum is installed *by* the installer |

### Containers

| Package | Why it is here | Without it |
|---|---|---|
| `docker` | Qdrant, Langfuse, and the OpenHands sandbox | No vector index in W3; **no container boundary in W5**, which is the entire reason OpenHands holds its slot |
| `docker-compose` | Langfuse ships a compose file | Hand-translating it to `docker run` |
| `docker-buildx` | Modern image builds | Some pulls fail on newer manifests |

### Network

| Package | Why it is here | Without it |
|---|---|---|
| `iproute2` | `ss`, which preflight uses for the port check **and the off-loopback check** | Preflight cannot verify spec §9's "nothing listening on a routable address" |
| `nftables` | Host firewall | Docker's published-port iptables rules go unfiltered |
| `wireguard-tools` | The mesh. Spec §9: the phone reaches Conduit over it or not at all | No phone access without a port forward, which is forbidden |

### Audio (W4+)

| Package | Why it is here | Without it |
|---|---|---|
| `ffmpeg` | Format conversion and resampling in the voice path | Whisper gets audio at the wrong sample rate |
| `sox` | Processing and the AEC path | No software echo cancellation, so barge-in is unusable (ADR-0019) |
| `alsa-utils` | `arecord -l` / `aplay -l` — how you find out which device is which | You debug a silent microphone blind |

### Services

| Package | Why it is here | Without it |
|---|---|---|
| `radicale` | The CalDAV server | W2 has no calendar, so "what's my week look like" has nothing to answer from |
| `python-passlib` `python-bcrypt` | Radicale's `htpasswd_encryption = bcrypt` | Radicale refuses to start, or falls back to a weaker hash |
| `isync` | `mbsync`, which syncs mail | No mail in W4 |
| `notmuch` | Indexes the maildir. We read the index, never the network | Mail is a pile of files with no query surface |
| `nodejs` `npm` | The wall surface (W6) | No wall display |
| `polkit` | The supervisor's narrow privilege rule from `install/01-users.sh` | `fridaysup` cannot manage `friday-*` units, so it cannot revert or kill — the supervisor becomes decorative |

---

## 3. AUR packages

| Package | Why | Note |
|---|---|---|
| `llama.cpp-cuda` | Inference with CUDA | `install/00` checks the **repositories first** — this package has moved between them |
| `matrix-conduit` | The homeserver, loopback, federation off | `# VERIFY:` conduwuit is the actively maintained fork |
| `mautrix-whatsapp` | One bridge | **One.** Spec §10 names bridge instability as the first thing that breaks. Add a second only after the first survives a week |
| `forgejo` | Where agent branches go for you to merge (W5) | Loopback, reached over the mesh |
| `headscale` | Mesh coordination | Optional — plain WireGuard is the smaller thing that works |

A failed AUR build is a **warning, not fatal**. A package can fail for reasons unrelated to FRIDAY, and one missing bridge should not stop an install.

---

## 4. Python dependencies

| Package | Why | Pinned because |
|---|---|---|
| `pydantic` `pydantic-settings` | Config validation. An unknown key is a **load error**, so a typo cannot silently grant an unbounded budget | v2 API |
| `pydantic-ai` | The agent and tool library (ADR-0011) | Major versions change the agent API |
| `pydantic-graph` | Node, edge and state typing (ADR-0012) | Ships with pydantic-ai; named because `friday/graph/` imports it directly |
| `litellm[proxy]` | The proxy itself. **In the venv**, because `friday-litellm.service` runs `/srv/friday/.venv/bin/litellm` | A `uv tool` lands in *your* `~/.local/bin`, a path `friday` does not have |
| `openai` `httpx` | The wire format to LiteLLM on loopback — not a cloud dependency | |
| `qdrant-client` | Tier 4 vectors | |
| `caldav` `icalendar` | W2 calendar ingest, including recurrence expansion | An index cannot match "Thursday" against an RRULE |
| `matrix-nio` | Matrix types | We read Conduit's database, not the C-S API — two consumers sharing one sync token means one silently misses messages |
| `pipecat-ai` | Voice transport (ADR-0023) | |
| `langfuse` | Tracing, pointed at a local instance | |
| `pyyaml` | Config parsing | |
| `structlog` `typer` `rich` | Logging and CLI | |

**Python is pinned to 3.12** (`>=3.12,<3.13`). Arch's `python` rolls forward, and a venv tracking it breaks on an unrelated `-Syu` — at which point every service fails to start at once, on a day you changed nothing.

**`kokoro` may need a git install.** If the wheel is not on PyPI for 3.12, install from git. **Do not unpin Python** to satisfy one TTS package.

---

## 5. Containers

Three things run in Docker. Everything else is a systemd unit, because a container in front of a GPU inference server is latency for nothing.

| Container | Why a container | Bind |
|---|---|---|
| Qdrant | Ships as one, no packaging value in unpacking it | `127.0.0.1:6333:6333` |
| Langfuse | Multi-service compose | `127.0.0.1:3000` |
| **OpenHands** | **The container IS the reason it holds the slot** (ADR-0010) | `127.0.0.1:3001`, `--network none`, `--read-only`, `--cap-drop ALL` |

Always `-p 127.0.0.1:<port>:<port>`, never `-p <port>:<port>`. Docker's default publish binds every interface *and* writes an iptables rule a host firewall does not filter.

---

## 6. Deliberately absent

| Not installed | Why |
|---|---|
| Khoj | Document RAG. OpenJarvis `deep_research` plus the vault covers it |
| Jan, AnythingLLM, LibreChat, Open WebUI | Chat frontends. Odysseus is one and does more |
| Open Interpreter, Self-Operating Computer | Code execution with no memory and no permission model |
| OpenClaw, PicoClaw | Redundant with Hermes, which has the better memory architecture |
| OpenCode | In-process policy, no filesystem isolation (ADR-0010) |
| Archon | Cloud dependency, telemetry, overlaps OpenHands (ADR-0015) |
| OpenAGI | Seven overlapping layers to get one (ADR-0021, ADR-0022) |
| Logfire | Langfuse owns tracing; hosted by default (ADR-0011) |
| Supabase / Postgres | Replaces two rows, adds three we have no use for (ADR-0027) |
| LangGraph | Better persistence, second graph engine (ADR-0012) |
| `pip` | Every install goes through `uv`. Never `sudo pip` |

---

## 7. Version pins, and what they protect

| Pin | Protects against |
|---|---|
| Python `>=3.12,<3.13` | An unrelated `-Syu` breaking every service at once |
| `embed_dim: 1024` (bge-m3) | Changing the embedding model is not a re-embed, it is a **rebuild** — every existing vector is in a different space |
| `chunk_tokens: 512` / overlap 64 | Bad chunk boundaries cause more eval failures than bad ranking |
| `min_rerank_score: 0.15` | Padding context to fill the budget is how retrieval degrades invisibly |
| `max_live_events: 8000` | Below spec §10's ~10k collapse point, with room |
| `speaker_threshold: 0.75`, floor 0.65 | Tuning it down until it stops being annoying deletes the control (ADR-0019) |
| `allowed_fails: 2` (LiteLLM) | A single failure against a stopped backend should not cool an alias down |
| **No fallback on `embed`/`rerank`** | Answering with a different embedding model produces vectors from a different space — degrades quietly, very hard to diagnose |
