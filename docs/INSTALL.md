# What to install

Everything FRIDAY needs, in one place: hardware first, then every package, then what is
deliberately absent.

**This is a bill of materials, not a procedure.** The order things get installed in is spec
§6's build order, and it is in [`docs/weeks/`](weeks/). Installing from this page top to
bottom will give you a box with everything on it and nothing working, which is the failure
mode the phase guides exist to prevent. Use this to buy hardware, to check what a week needs
before you start it, and to answer "did I ever install that."

Arch Linux. `pacman` for the repositories, `paru` for the AUR, `uv` for Python, Docker for
the three things that genuinely want a container. Never `apt`, never `sudo pip`.

---

## 1. Hardware

### The server

One machine, on all the time. This is the whole system; everything else is a peripheral.

| Part | Minimum | Recommended | Why |
|---|---|---|---|
| GPU | 12 GB VRAM | **24 GB** | Spec §1's table. 24 GB is the sweet spot: Qwen 3.6 27B @ Q4 plus ~6 GB resident |
| System RAM | 32 GB | 64 GB | Qdrant, Docker, the bridges and the indexer all want room |
| Disk | 250 GB NVMe | 1 TB NVMe | Weights are ~40 GB, the index and mail grow without bound until consolidation bounds them |
| Network | Wired | Wired | Satellites stream audio continuously. Wifi jitter is latency you cannot get back |

**Full-disk encryption is not optional and cannot be added later.** Spec §9 lists it, and it
is an install-time decision. This box will hold your mail, your messages, your calendar and a
vector index of your life. Set it up when you install Arch or accept that you never will.

VRAM decides the daily driver, from spec §1:

| VRAM | Daily driver |
|---|---|
| 12-16 GB | Gemma 4 12B @ Q4 |
| 16 GB | Devstral-2 22B @ Q4 |
| **24 GB** | **Qwen 3.6 27B @ Q4** |
| 32 GB | Qwen3.6-35B-A3B |
| 48 GB | Qwen3-Coder-Next |
| 128 GB | gpt-oss-120b |

Below 24 GB, set `MIN_VRAM_MB` so preflight stops arguing with you:

```bash
echo 'MIN_VRAM_MB=15000' | sudo tee /etc/friday/preflight.env
```

### Voice satellites

One per room you want to talk in. ADR-0018: **satellites capture and stream, they do not
transcribe.** There is one STT process and it is on the server's GPU. That keeps satellites
cheap and replaceable — anything that captures audio and speaks ESPHome will do.

| Part | Notes |
|---|---|
| ESP32-S3 board with PSRAM | **ESP32-S3-BOX-3** is the one to buy: it has onboard acoustic echo cancellation, which ADR-0019 makes a hard requirement for barge-in |
| I2S microphone | Onboard on the S3-BOX. A bare ESP32-S3 with an INMP441 works, but has no AEC, so she will interrupt herself and barge-in is unusable |
| Small speaker | For her half of the conversation. Onboard on the S3-BOX |
| USB-C power | Permanently powered. These are not battery devices |

They join Home Assistant over ESPHome, and HA is the only thing that talks to them. W4 and W5.

### The wall

| Part | Notes |
|---|---|
| Tablet, 8-10 inch | Wall-mounted, permanently powered, kiosk browser at the wall surface |
| A wall mount and a cable route | The part everyone underestimates |

ADR-0016: the wall renders agent state and never commands. A tablet on a wall is reachable by
anyone in the room, so it is not an authenticated principal and nothing consequential starts
there.

### Desk audio

For W4, before the satellites exist. Any USB microphone and any speakers. `arecord -l` and
`aplay -l` must list them.

### Kill switch

Spec §9: from your phone plus a physical button.

| Part | Notes |
|---|---|
| A momentary button | Wired to a GPIO pin, or a USB button that presents as a key event |
| Phone | Over the mesh. It must not depend on Hermes, OpenJarvis, or a model being healthy |

---

## 2. Repository packages

`install/00-arch-packages.sh` runs this. `--needed` on everything, so a re-run is a no-op.

```bash
sudo pacman -Syu --needed --noconfirm \
  base-devel git cmake ninja pkgconf \
  cuda cudnn nvidia-utils \
  uv python \
  age sops \
  jq sqlite ripgrep rsync \
  docker docker-compose docker-buildx \
  iproute2 nftables wireguard-tools \
  ffmpeg sox alsa-utils \
  radicale python-passlib python-bcrypt \
  isync notmuch python-notmuch \
  nodejs npm \
  polkit
```

What each group is for:

| Group | Week | Purpose |
|---|---|---|
| `base-devel cmake ninja pkgconf` | W1 | Building llama.cpp and AUR packages |
| `cuda cudnn nvidia-utils` | W1 | GPU. Without these everything runs on CPU and looks fine |
| `uv python` | W1 | Python, pinned to 3.12. Never the system interpreter directly |
| `age sops` | W1 | Secrets. ADR-0005: capabilities, not credentials |
| `jq sqlite ripgrep` | W1 | Every verification block in every week guide |
| `docker docker-compose` | W1 | Qdrant, Langfuse, OpenHands |
| `iproute2 nftables wireguard-tools` | W1 | The mesh, and `ss` for preflight's port checks |
| `ffmpeg sox alsa-utils` | W4 | Audio capture and playback |
| `radicale python-passlib python-bcrypt` | W2 | CalDAV |
| `isync notmuch python-notmuch` | W4 | Mail. mbsync syncs, notmuch indexes |
| `nodejs npm` | W6 | The wall surface |
| `polkit` | W1 | The supervisor's narrow privilege grant |

---

## 3. AUR packages

Bootstrap `paru` once, guarded so it is safe to re-run:

```bash
command -v paru >/dev/null || {
  tmp=$(mktemp -d) && git clone --depth 1 https://aur.archlinux.org/paru-bin.git "$tmp/paru-bin" \
    && (cd "$tmp/paru-bin" && makepkg -si --noconfirm) && rm -rf "$tmp"
}
```

```bash
paru -S --needed --noconfirm \
  llama.cpp-cuda \
  matrix-conduit \
  mautrix-whatsapp \
  forgejo \
  headscale
```

| Package | Week | `# VERIFY:` |
|---|---|---|
| `llama.cpp-cuda` | W1 | Check `pacman -Ss '^llama.cpp'` first — this has moved between the repositories and the AUR |
| `matrix-conduit` | W1 | conduwuit is the actively maintained fork; check which is current |
| `mautrix-*` | W1 | **One bridge only** until it has survived a week. Spec §10: bridge instability, WhatsApp especially |
| `forgejo` | W5 | Where agent branches go for you to merge |
| `headscale` | W1 | Optional — plain WireGuard is the smaller thing that works |

---

## 4. Python

Pinned to 3.12. Arch's `python` rolls forward, and a venv tracking it breaks on an unrelated
`-Syu` — at which point every service fails to start at once, on a day you changed nothing.

```bash
uv python install 3.12
uv python pin 3.12
uv sync --extra dev
```

The voice extra is heavy and is not needed before W4:

```bash
uv sync --extra voice
```

Standalone tools, installed as tools rather than into the project environment:

```bash
uv tool install 'litellm[proxy]'
uv tool install "huggingface_hub[cli]"
```

Notable dependencies and why they are there:

| Package | Role |
|---|---|
| `pydantic-ai` | The agent and tool library. ADR-0011. Not a layer owner; LiteLLM stays transport |
| `pydantic-graph` | Node, edge and state typing for the graph layer. ADR-0012 |
| `pydantic` / `pydantic-settings` | Config validation. An unknown key is a load error |
| `qdrant-client` | Tier 4 vectors |
| `caldav` / `icalendar` / `matrix-nio` | W2 senses |
| `langfuse` | Tracing, self-hosted. "You will need this at 3am" |
| `faster-whisper` | STT, large-v3-turbo, GPU, resident. ADR-0018 |
| `openwakeword` / `resemblyzer` / `sounddevice` | W5 wake path and speaker gate |
| `kokoro` | TTS. `# VERIFY:` the install path; use git rather than unpinning Python |

**Not installed via pip, deliberately:** `python-notmuch` comes from `pacman`, because pip
cannot install the C library it binds to.

---

## 5. Containers

Three things run in Docker. Everything else is a systemd unit, because a container in front
of a GPU inference server is latency for nothing.

```bash
sudo systemctl enable --now docker.service
```

| Container | Week | Bind |
|---|---|---|
| Qdrant | W3 | `-p 127.0.0.1:6333:6333` |
| Langfuse | W1 | `127.0.0.1:3000` |
| OpenHands | W5 | `127.0.0.1:3001`, `--network none`, `--read-only`, `--cap-drop ALL` |

**Always `-p 127.0.0.1:<port>:<port>`, never `-p <port>:<port>`.** Docker's default publish
binds every interface and writes an iptables rule that a host firewall does not filter.
Preflight catches it, and the container is easier to fix than the afternoon spent wondering
why the box is exposed.

The OpenHands flags are the security boundary, not tuning. ADR-0010 gives OpenHands the
autonomous-coding slot **because of the container**, so removing `--network none` to let it
reach LiteLLM deletes the reason it holds the slot. Bridge it to `127.0.0.1:4000` and nothing
else. W5 step 7.

---

## 6. Upstream projects

Not packaged, installed from their own instructions.

| Project | Week | How |
|---|---|---|
| OpenJarvis | W1 | `curl -fsSL https://open-jarvis.github.io/OpenJarvis/install.sh \| bash`, then `jarvis init --preset chat-simple`. Spec §11 gives this verbatim. **Read the script first** — it is the only place in the whole build where a remote script is piped to a shell |
| Hermes Agent | W1 | `# VERIFY:` against the NousResearch repository. Then `hermes model set primary daily` |
| Odysseus | W1+ | AGPL-3.0. Workspace UI and the hardware Cookbook |
| Home Assistant | W4 | Container or supervised, bound to `127.0.0.1:8123` |
| ESPHome | W4 | Flashes the satellites; runs as an HA add-on or standalone |
| Obsidian | W3 | Optional and never required. ADR-0017: the vault is plain markdown that `grep` fully understands |

---

## 7. Weights

Spec §1: **verify current picks before downloading.** Model names move and quantisations get
re-cut. `install/03-models.sh` reads its repository ids from a table at the top of the script
so there is exactly one place to correct them.

| Alias | Pick at 24 GB | Port | Resident |
|---|---|---|---|
| `daily` | Qwen 3.6 27B @ Q4 | 8080 | yes |
| `fast` | 4B router | 8081 | yes |
| `embed` | bge-m3 | 8082 | yes |
| `rerank` | bge-reranker-v2-m3 | 8085 | yes |
| `coder` | Devstral-2 22B @ Q4 | 8083 | on demand, evicts `daily` |
| `vision` | Qwen3-VL | 8084 | on demand, evicts `daily` |

Plus faster-whisper large-v3-turbo and Kokoro, also resident. The resident set is about 6 GB
and that is a **latency budget**, not a memory note — anything loaded per utterance costs
more than the entire 800ms budget.

```bash
sudo -u friday hf download <REPO_ID> <FILENAME.gguf> --local-dir /srv/friday/models
```

---

## 8. What is not installed, and why

Reading this list is cheaper than re-litigating it at 2am. Spec §3 cut twelve candidates;
[ADR-0015](DECISIONS.md) cut ten more after the spec was written.

| Not installed | Because |
|---|---|
| Khoj | Document RAG. OpenJarvis `deep_research` plus the vault covers it |
| Jan, AnythingLLM, LibreChat, Open WebUI | Chat frontends. Odysseus is one and does more |
| Open Interpreter, Self-Operating Computer | Code execution with no memory and no permission model |
| OpenClaw, PicoClaw | Redundant with Hermes, which has the better memory architecture |
| OpenCode | Real permission model, but it is in-process policy with no filesystem isolation. ADR-0010 |
| Archon | Cloud dependency on a Claude Code binary, PostHog telemetry, and it overlaps OpenHands. ADR-0015 |
| Polsia | Claude CLI subprocess with OAuth to Anthropic. Fails §9 |
| Logfire | pydantic-ai integrates with it; Langfuse owns tracing and a second owner is ADR-0001 |
| LangGraph | Better persistence story than pydantic-graph, and a second graph engine. ADR-0012 takes the small path |

If you are about to install something that overlaps a row in the stack table, the rule is
ADR-0001: either the feature belongs in the incumbent, or the incumbent is wrong and should
be replaced. "I need one feature from project X" is not sufficient grounds.

---

## 9. Checking

```bash
make preflight
```

Reads everything, changes nothing, and is fast enough that the supervisor runs it every 30
seconds as a health check. Its failures are the entry condition for whichever phase you are
about to start; each week guide's Prerequisites section says which failures are expected at
that point.

```bash
uv run python -m friday.config --check
```

Validates every configuration file and cross-checks them against each other. A config error
found here costs a second; the same error found by a systemd unit costs a journal read.
