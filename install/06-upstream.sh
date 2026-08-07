#!/usr/bin/env bash
# Upstream projects that are not packaged: OpenJarvis, Hermes, Langfuse, Qdrant.
#
# These are the components spec section 1 names that no Arch package provides. Each has its
# own install path and its own opinions, so this script does the parts that can be automated
# and REPORTS the parts that cannot, rather than pretending.
#
# That reporting is the point. An installer that silently skips half the stack leaves you
# with a green run and a system that does not work; one that says "these four things need
# you" is doing its job.
#
#   sudo bash install/06-upstream.sh

set -uo pipefail    # not -e: every component is attempted, then the gaps are reported
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

need_root
need_users
banner_profile

MANUAL=()   # things this script could not finish, reported at the end

# --- OpenJarvis ---------------------------------------------------------------
# Spec section 11 gives the install verbatim. Worth being honest about what it is: you are
# executing whatever that URL serves today, as your user. It is the only place in the whole
# build where that happens.
log "OpenJarvis"
if command -v jarvis >/dev/null 2>&1; then
  info "jarvis present: $(jarvis --version 2>/dev/null | head -n1 || echo installed)"
else
  script="$(mktemp)"
  if curl -fsSL https://open-jarvis.github.io/OpenJarvis/install.sh -o "$script" 2>/dev/null; then
    ui_warn "About to execute a remote install script as ${SUDO_USER}."
    ui_note "Spec section 11 specifies this command. Read it first - it is a one-time cost."
    if ui_confirm "Review the script before running it?"; then
      if [[ $UI_HAS_GUM -eq 1 ]]; then gum pager < "$script"; else "${PAGER:-less}" "$script"; fi
    fi
    if ui_confirm "Run the OpenJarvis installer?"; then
      sudo -u "$SUDO_USER" bash "$script" && info "OpenJarvis installed" \
        || MANUAL+=("OpenJarvis installer failed. See docs/weeks/W1.md step 9.")
    else
      MANUAL+=("OpenJarvis declined. Run: curl -fsSL https://open-jarvis.github.io/OpenJarvis/install.sh | bash")
    fi
  else
    MANUAL+=("Could not fetch the OpenJarvis installer. Check the URL in docs/weeks/W1.md step 9.")
  fi
  rm -f "$script"
fi

# `jarvis init` writes per-user state, so it runs as the invoking user and not as root.
if command -v jarvis >/dev/null 2>&1; then
  if [[ -d "/home/$SUDO_USER/.openjarvis" ]]; then
    info "jarvis already initialised"
  else
    ui_spin "jarvis init --preset chat-simple" -- \
      sudo -u "$SUDO_USER" jarvis init --preset chat-simple \
      || MANUAL+=("jarvis init failed. Run: jarvis init --preset chat-simple")
  fi
  MANUAL+=("Point OpenJarvis at LiteLLM: base URL http://127.0.0.1:4000/v1 with the 'conversation' virtual key, NEVER the master key and never a direct llama-server port. VERIFY the config key name against OpenJarvis's docs.")
fi

# --- Hermes Agent -------------------------------------------------------------
log "Hermes Agent"
if [[ -x "$ROOT/.venv/bin/hermes" ]]; then
  info "hermes present in the venv"
else
  # VERIFY: install method against github.com/NousResearch/hermes-agent. It is listed here
  # rather than guessed at, because a wrong pip name installs someone else's package.
  MANUAL+=("Hermes Agent is not installed. VERIFY the method at github.com/NousResearch/hermes-agent, then install into $ROOT/.venv so systemd/friday-hermes.service finds it.")
fi
MANUAL+=("Hermes model routing, verbatim from spec section 8:  hermes model set primary daily  /  hermes model set auxiliary.curator fast  /  hermes model set auxiliary.summarizer fast")

# --- Langfuse -----------------------------------------------------------------
# Spec section 1: "You will need this at 3am." Install it now, while nothing is wrong.
log "Langfuse"
install -d -m 0750 -o friday -g friday "$ROOT/langfuse"
if docker ps --filter 'name=langfuse' --format '{{.Names}}' 2>/dev/null | grep -q .; then
  info "langfuse running"
elif [[ -f "$ROOT/langfuse/docker-compose.yml" ]]; then
  ui_spin "Starting Langfuse" -- docker compose -f "$ROOT/langfuse/docker-compose.yml" up -d \
    || MANUAL+=("Langfuse failed to start. docker compose -f $ROOT/langfuse/docker-compose.yml logs")
else
  MANUAL+=("Langfuse needs its compose file at $ROOT/langfuse/docker-compose.yml. Take the current one from the Langfuse repository, and bind published ports to 127.0.0.1 ONLY - \"3000:3000\" listens on every interface and preflight will fail the box.")
fi

# --- Qdrant -------------------------------------------------------------------
# W3, not W1. Started here because it is one idempotent command and having it running early
# costs nothing.
log "Qdrant (W3)"
if docker ps -a --filter 'name=^friday-qdrant$' --format '{{.Names}}' 2>/dev/null | grep -q .; then
  info "friday-qdrant container exists"
  docker start friday-qdrant >/dev/null 2>&1 || true
else
  install -d -m 0750 -o friday -g friday "$ROOT/db/qdrant"
  # -p 127.0.0.1:6333:6333 and NOT -p 6333:6333. Docker's default publish binds every
  # interface and writes an iptables rule a host firewall does not filter.
  ui_spin "Starting Qdrant" -- docker run -d --name friday-qdrant --restart unless-stopped \
    -p 127.0.0.1:6333:6333 -v "$ROOT/db/qdrant:/qdrant/storage" qdrant/qdrant:latest \
    || MANUAL+=("Qdrant failed to start. It is not needed until W3.")
fi

# --- Deferred, on purpose -----------------------------------------------------
ui_note "Not installed here, by design:"
ui_note "  Odysseus     workspace UI, install when you want it (AGPL-3.0)"
ui_note "  OpenHands    W5, and it wants a sandbox that does not exist yet"
ui_note "  Home Assistant + ESP32 satellites   deferred past W8 (ADR-0020)"

# --- Report -------------------------------------------------------------------
if [[ ${#MANUAL[@]} -eq 0 ]]; then
  ui_summary "Upstream complete" "Nothing needs manual intervention."
else
  printf '%s\n' "${MANUAL[@]}" > /tmp/friday-manual-steps.txt
  ui_summary "Manual intervention needed (${#MANUAL[@]})" "${MANUAL[@]}"
  ui_note "Also written to /tmp/friday-manual-steps.txt"
fi
