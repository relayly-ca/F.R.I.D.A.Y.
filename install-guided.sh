#!/usr/bin/env bash
# FRIDAY guided installer. A linear walkthrough, one step at a time.
#
#   bash install-guided.sh
#
# The other one is install.sh - a dashboard and a menu, better once the box is partly built
# and you want to run one thing. This one is better on a fresh box: it explains each step
# before running it, shows where you are, and offers a way out when something fails.
#
# Both share install/steps.sh, so they run identical code and cannot drift apart.
#
#   FRIDAY_PROFILE=dev bash install-guided.sh    choose the profile up front
#   FRIDAY_YES=1       bash install-guided.sh    accept every prompt
#   FRIDAY_FROM=venv   bash install-guided.sh    resume from a named step

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT=${ROOT:-/srv/friday}

source "$REPO/install/ui.sh"

if [[ $EUID -ne 0 ]]; then
  ui_banner "guided installer"
  ui_info "This needs root for packages, users and systemd. Re-running under sudo."
  exec sudo --preserve-env=FRIDAY_PROFILE,FRIDAY_YES,FRIDAY_FROM,ROOT bash "$0" "$@"
fi
[[ -n "${SUDO_USER:-}" ]] || ui_die "run as your own user (it elevates itself). makepkg and uv refuse to run as root."

source "$REPO/install/lib.sh"
if [[ $UI_HAS_GUM -eq 0 ]]; then
  echo "Installing gum for the installer UI..."
  pacman -Sy --needed --noconfirm gum >/dev/null 2>&1 || true
  source "$REPO/install/ui.sh"
fi
source "$REPO/install/steps.sh"

PROFILE="$(friday_profile)"

# --- The steps, in order, with what each one actually does --------------------
# Written out rather than derived, because the explanation is the point of this installer.
# A step you cannot describe in two sentences is a step you should not be running blind.

STEPS=(packages users tree secrets venv models units keys upstream)

step_title() {
  case "$1" in
    packages) echo "System packages" ;;
    users)    echo "Service accounts" ;;
    tree)     echo "Install root" ;;
    secrets)  echo "Secrets" ;;
    venv)     echo "Python environment" ;;
    models)   echo "Model weights" ;;
    units)    echo "Services" ;;
    keys)     echo "Per-agent keys" ;;
    upstream) echo "Upstream projects" ;;
  esac
}

step_time() {
  case "$1" in
    packages) echo "5-15 min, network, a few GB" ;;
    users)    echo "seconds" ;;
    tree)     echo "seconds" ;;
    secrets)  echo "a minute, asks you one question" ;;
    venv)     echo "2-5 min, network" ;;
    models)   echo "10 min to 2 hours, network, 4-40 GB" ;;
    units)    echo "seconds" ;;
    keys)     echo "seconds" ;;
    upstream) echo "5-20 min, network, asks you questions" ;;
  esac
}

step_why() {
  case "$1" in
    packages) cat <<'X'
Installs everything from the Arch repositories and the AUR: the toolchain, CUDA,
`uv`, `age`/`sops`, Docker, Radicale, notmuch, and llama.cpp.

CUDA goes on even with the dev profile. A few hundred MB, and it means dropping a
card into this box later does not need a second install pass.

One bridge only. Spec section 10 names bridge instability as the first thing that
breaks, and debugging two unfamiliar bridges at once turns an evening into a weekend.
X
;;
    users) cat <<'X'
Creates `friday` and `fridaysup`, neither with a login shell, plus one narrow polkit
rule letting the supervisor manage `friday-*` units and nothing else.

This is spec section 9: she runs as `friday`, and `agent/core/` belongs to the
supervisor user. She can execute her orchestration loop and cannot write it.
X
;;
    tree) cat <<'X'
Creates `/srv/friday` exactly as spec section 11 describes it, with ownership and modes.

The one line here that carries a security property is `agent/core/`, owned by
`fridaysup`. The script does not assert that boundary, it TESTS it: if the `friday`
user can write there, it exits non-zero rather than continuing.
X
;;
    secrets) cat <<'X'
Generates an age identity, writes its public key into `.sops.yaml`, and mints the
LiteLLM master key encrypted.

ADR-0005: she gets capabilities, not credentials. The secrets directory is root-owned
0700 and she cannot read it. A helper hands exactly one key to exactly one unit.

The master key exists to mint the per-agent virtual keys and for nothing else. No
service is ever configured with it.
X
;;
    venv) cat <<'X'
Creates the virtual environment at `/srv/friday/.venv`, pinned to Python 3.12, and
installs the project into it.

Pinned, because Arch's `python` rolls forward and a venv tracking it breaks on an
unrelated `-Syu` - at which point every service fails to start at once, on a day you
changed nothing.

It finishes by validating every config file. A config error found here costs a second;
the same error found by a systemd unit costs a journal read.
X
;;
    models) cat <<'X'
Downloads the weights this profile needs. On dev that is a few GB; on target, forty.

**This step will refuse to run** while any model repository in its table is still a
`# VERIFY:` placeholder. Spec section 1 says verify current picks before downloading,
and a confidently wrong repository id wastes more of an evening than a marker telling
you to go and look.

The table is at the top of `install/03-models.sh` - one place to correct.
X
;;
    units) cat <<'X'
Renders the llama.cpp env files and the LiteLLM config for this profile, installs the
systemd units, and starts the week-1 set.

Two gates before a single unit is installed: the configuration must validate, and the
active profile must not have relaxed anything in `may_not_change`. If either fails,
nothing is installed. A box that refuses to start is better than one that starts with
a boundary quietly off.
X
;;
    keys) cat <<'X'
Mints one LiteLLM virtual key per agent, each scoped to the aliases that agent is
allowed to use, and stores them sops-encrypted.

Spec section 8: a single shared master key across agents is not sufficient - Hermes
shipped a hardening release specifically patching a LiteLLM credential exposure.

Needs LiteLLM already answering on 127.0.0.1:4000, which the previous step started.
X
;;
    upstream) cat <<'X'
OpenJarvis, Hermes, Langfuse and Qdrant - the components no Arch package provides.

It does what can be automated and **reports what cannot**, rather than skipping
silently. An installer that quietly misses half the stack leaves you with a green run
and a system that does not work.

OpenJarvis installs by piping a remote script to bash. Spec section 11 specifies that
command, it is the only place in the whole build where it happens, and you will be
offered the script to read first.
X
;;
  esac
}

# --- Failure recovery ---------------------------------------------------------
# A failed step is a decision point, not an exit. Most failures here are recoverable -
# a network blip, an AUR build, a missing placeholder - and dumping you back at a shell
# prompt with no context is the worst of the available options.
on_failure() {
  local name="$1" title; title="$(step_title "$name")"
  ui_err "$title did not complete."
  while true; do
    case "$(ui_choose "What now?" \
      "Retry this step" \
      "Skip it and continue (may break later steps)" \
      "Open a shell here, then come back" \
      "Show the last 40 log lines" \
      "Stop")" in
      "Retry"*) return 0 ;;
      "Skip"*)
        ui_warn "Skipping $title. Later steps may fail because of it."
        return 1 ;;
      "Open a shell"*)
        ui_note "Type 'exit' to return to the installer."
        ${SHELL:-/bin/bash} || true ;;
      "Show the last"*)
        journalctl -n 40 --no-pager 2>/dev/null || ui_note "no journal available" ;;
      "Stop"|"")
        ui_note "Nothing was left half-applied. Re-run any time; it picks up where you stopped."
        exit 1 ;;
    esac
  done
}

# --- Screens ------------------------------------------------------------------

welcome() {
  ui_banner "a fully local, always-on ambient AI"
  ui_doc "This installs **week 1**: inference, model routing, the agent runtime, and
messaging. When it finishes you will chat with her locally and text her from your phone.

Weeks 2 through 8 are deliberately manual. Each has a gate you need to look at - an eval
score, a latency measurement, a security check you should watch fail before you watch it
pass. Those live in \`docs/weeks/\`.

**Everything here is idempotent.** Quit at any point and re-run; it picks up where you
stopped rather than starting over. Nothing is left half-applied."
  ui_rule
  ui_note "Nine steps. Roughly 30-90 minutes, most of it downloads."
  ui_note "Four things will need you afterwards; it will list them."
  echo
  ui_confirm "Ready?" || { ui_note "Nothing changed."; exit 0; }
}

environment() {
  ui_header "Checking this machine"
  detect
  ui_status "${S[os]}"   "Arch Linux" "${D[os]}"
  ui_status "${S[gpu]}"  "GPU"        "${D[gpu]}"
  ui_status "${S[disk]}" "Disk"       "${D[disk]}"

  [[ "${S[os]}" == "fail" ]] && ui_die "${D[os]}"

  if [[ "${S[disk]}" == "fail" ]]; then
    ui_err "${D[disk]}"
    ui_confirm "Continue anyway?" || exit 1
  fi
  if [[ "${S[gpu]}" == "fail" ]]; then
    ui_warn "${D[gpu]}"
    ui_note "The dev profile runs on CPU and can build every layer except answer quality."
    ui_confirm "Switch to the dev profile?" && {
      install -d -m 0755 /etc/friday; echo dev > /etc/friday/profile; PROFILE=dev
      ui_ok "profile: dev"; }
  fi
}

pick_profile() {
  ui_header "Profile"
  ui_doc "**dev** - small or no GPU. Aliases collapse onto small models. Every layer is
buildable and testable; answer quality is not comparable.

**target** - 24 GB VRAM, Qwen 3.6 27B @ Q4. Every \"done when\" in \`docs/weeks/\` is
written against this one, including the 20/25 eval gate.

Retrieval *is* comparable across both, because the embedding and reranking models are
identical. So week 2-3 - the long pole - is fully testable on a weak box. ADR-0025."
  ui_note "Currently: $PROFILE"
  if ui_confirm "Change it?"; then
    local p; p="$(ui_choose "Which is this box?" "dev" "target")"
    [[ -n "$p" ]] && { install -d -m 0755 /etc/friday; echo "$p" > /etc/friday/profile
                       PROFILE="$p"; ui_ok "profile: $p"; }
  fi
}

walk() {
  local total=${#STEPS[@]} n=0 started=0
  [[ -z "${FRIDAY_FROM:-}" ]] && started=1

  for name in "${STEPS[@]}"; do
    n=$((n + 1))
    [[ "${FRIDAY_FROM:-}" == "$name" ]] && started=1
    [[ $started -eq 1 ]] || continue

    detect
    local title; title="$(step_title "$name")"

    if [[ "${S[$name]:-todo}" == "done" ]]; then
      ui_status done "$n/$total  $title" "already done"
      continue
    fi

    ui_header "Step $n of $total   $title"
    step_why "$name" | { [[ $UI_HAS_GUM -eq 1 ]] && gum format || cat; }
    ui_note "Expect: $(step_time "$name")"
    echo

    case "$(ui_choose "Run this step?" "Run it" "Skip for now" "Stop here")" in
      "Run it")
        until "step_${name}"; do
          on_failure "$name" || break
        done ;;
      "Skip"*) ui_warn "Skipped $title." ;;
      *) ui_note "Stopped at step $n. Re-run to continue: FRIDAY_FROM=$name bash $0"
         exit 0 ;;
    esac
  done
}

finish() {
  detect
  ui_header "Where things stand"
  dashboard
  echo
  report_manual
  ui_doc "When those are done, week 1 is complete: **you chat locally, and you text her
from your phone.**

Then \`docs/weeks/W2.md\`. Its first step is writing 25 eval questions, *before* any
ingestion - spec section 7 is explicit about the order, and questions written afterwards
are quietly shaped by what you already know is in the index."
}

# --- Main ---------------------------------------------------------------------
welcome
environment
pick_profile
step_personalise
walk
finish
