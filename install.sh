#!/usr/bin/env bash
# FRIDAY installer. One command, from a bare Arch box to a running week 1.
#
#   bash install.sh
#
# It elevates itself, so do not prefix it with sudo - several steps (makepkg, uv) refuse to
# run as root and need to know who invoked them.
#
# What this is: a front end over install/*.sh. Every step it runs is a script you can run by
# hand, in the order docs/weeks/W1.md gives, and running them by hand is a supported path
# rather than a fallback. This exists so the common case is one command, not so the
# individual steps become unreachable.
#
# What it is NOT: a substitute for the phase guides. It gets you through week 1. Weeks 2
# through 8 are deliberately manual, because each one has a gate you have to look at.
#
#   FRIDAY_PROFILE=dev bash install.sh     choose the profile up front
#   FRIDAY_YES=1       bash install.sh     no prompts, for a re-run
#   FRIDAY_STEP=models bash install.sh     run one step and stop

set -uo pipefail   # deliberately not -e: a failed step is reported, not a silent exit

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT=${ROOT:-/srv/friday}

source "$REPO/install/ui.sh"

# --- Elevate ------------------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
  ui_banner "installer"
  ui_info "This needs root for packages, users and systemd. Re-running under sudo."
  exec sudo --preserve-env=FRIDAY_PROFILE,FRIDAY_YES,FRIDAY_STEP,ROOT bash "$0" "$@"
fi

[[ -n "${SUDO_USER:-}" ]] || ui_die "run this as your own user (it elevates itself), not as root directly. makepkg and uv refuse to run as root."

source "$REPO/install/lib.sh"

# --- gum, first ---------------------------------------------------------------
# The UI degrades without it, and the dashboard is most of the point, so install it before
# anything else and re-source so the rest of the run is styled.
if [[ $UI_HAS_GUM -eq 0 ]]; then
  echo "Installing gum for the installer UI..."
  pacman -Sy --needed --noconfirm gum >/dev/null 2>&1 || true
  source "$REPO/install/ui.sh"
fi

PROFILE="$(friday_profile)"
ui_banner "a fully local, always-on ambient AI"

# --- State detection ----------------------------------------------------------
# Reads only. This runs before anything is changed and again at the end, so the dashboard is
# a measurement rather than a memory of what the script thinks it did.

declare -A S     # step -> done|todo|warn|fail
declare -A D     # step -> detail

detect() {
  # os
  if [[ -f /etc/arch-release ]]; then S[os]=done; D[os]="Arch Linux"
  else S[os]=fail; D[os]="not Arch - pacman/paru/uv only, never apt"; fi

  # gpu
  if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
    local vram; vram="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -n1)"
    D[gpu]="$(nvidia-smi --query-gpu=name --format=csv,noheader | head -n1), ${vram} MB"
    if [[ "$PROFILE" == "target" && "$vram" -lt 23000 ]]; then S[gpu]=warn
      D[gpu]="${D[gpu]} - below the target floor; consider the dev profile"
    else S[gpu]=done; fi
  elif [[ "$PROFILE" == "dev" ]]; then
    S[gpu]=warn; D[gpu]="none - dev profile runs on CPU, slowly"
  else
    S[gpu]=fail; D[gpu]="no usable GPU and profile is target"
  fi

  # disk
  local free; free=$(( $(df -Pk "$(dirname "$ROOT")" | awk 'NR==2 {print $4}') / 1048576 ))
  local floor; floor="$(profile_get min_disk_gb 2>/dev/null || echo 40)"
  D[disk]="${free} GB free, floor ${floor}"
  [[ "$free" -ge "$floor" ]] && S[disk]=done || S[disk]=fail

  # packages
  if command -v llama-server >/dev/null 2>&1 && command -v uv >/dev/null 2>&1 \
     && command -v sops >/dev/null 2>&1; then S[packages]=done; D[packages]="llama.cpp, uv, sops present"
  elif command -v uv >/dev/null 2>&1; then S[packages]=warn; D[packages]="partial - llama.cpp or sops missing"
  else S[packages]=todo; D[packages]="pacman + paru"; fi

  # users
  if id -u friday >/dev/null 2>&1 && id -u fridaysup >/dev/null 2>&1; then
    S[users]=done; D[users]="friday, fridaysup"
  else S[users]=todo; D[users]="two service accounts, no login shell"; fi

  # tree + the core boundary. This is a security property, so it is checked rather than
  # inferred from the directory existing. ADR-0004.
  if [[ -d "$ROOT/agent/core" ]]; then
    if sudo -u friday test -w "$ROOT/agent/core" 2>/dev/null; then
      S[tree]=fail; D[tree]="friday CAN write agent/core - spec section 9 is not in force"
    else
      S[tree]=done; D[tree]="$ROOT, core owned by fridaysup"
    fi
  else S[tree]=todo; D[tree]="spec section 11 install root"; fi

  # secrets
  if [[ -f "$ROOT/secrets/age.key" ]] && ! grep -q 'age1REPLACE' "$REPO/.sops.yaml" 2>/dev/null; then
    S[secrets]=done; D[secrets]="age identity, sops recipient set"
  elif [[ -f "$ROOT/secrets/age.key" ]]; then
    S[secrets]=warn; D[secrets]=".sops.yaml still has the placeholder recipient"
  else S[secrets]=todo; D[secrets]="age keypair + sops"; fi

  # venv
  if [[ -x "$ROOT/.venv/bin/python" ]]; then
    S[venv]=done; D[venv]="$("$ROOT/.venv/bin/python" --version 2>&1)"
  else S[venv]=todo; D[venv]="uv, pinned 3.12"; fi

  # models
  local n; n=$(find "$ROOT/models" -name '*.gguf' 2>/dev/null | wc -l)
  if [[ "$n" -gt 0 ]]; then
    S[models]=done; D[models]="$n weights, $(du -sh "$ROOT/models" 2>/dev/null | cut -f1)"
  else S[models]=todo; D[models]="profile $PROFILE"; fi

  # units
  if [[ -f /etc/systemd/system/friday-litellm.service ]]; then
    local up; up=$(systemctl list-units 'friday-*' --state=running --no-legend 2>/dev/null | wc -l)
    S[units]=done; D[units]="installed, $up running"
  else S[units]=todo; D[units]="systemd units + rendered config"; fi

  # upstream: the components no Arch package provides
  local have=0 want=3
  command -v jarvis >/dev/null 2>&1 && ((have++))
  [[ -x "$ROOT/.venv/bin/hermes" ]] && ((have++))
  docker ps --filter 'name=langfuse' --format '{{.Names}}' 2>/dev/null | grep -q . && ((have++))
  if [[ "$have" -eq "$want" ]]; then S[upstream]=done; D[upstream]="OpenJarvis, Hermes, Langfuse"
  elif [[ "$have" -gt 0 ]]; then S[upstream]=warn; D[upstream]="$have of $want - some need you"
  else S[upstream]=todo; D[upstream]="OpenJarvis, Hermes, Langfuse, Qdrant"; fi

  # keys
  if [[ -f "$ROOT/secrets/litellm-keys.yaml" ]]; then
    S[keys]=done; D[keys]="per-agent virtual keys"
  else S[keys]=todo; D[keys]="spec section 8, one key per agent"; fi

  # model repo ids. install/03 refuses to run while any row is a placeholder, so this is
  # detected from the script itself rather than from a note someone might forget to update.
  if grep -q '# VERIFY:' "$REPO/install/03-models.sh"; then
    S[weights]=todo; D[weights]="edit the table at the top of install/03-models.sh"
  else S[weights]=done; D[weights]="verified"; fi

  # mesh. Spec section 9: no port forwarding, so the phone reaches Conduit over a mesh or
  # not at all. This is the half of week 1 that reads as messaging and is really networking.
  if ip link show wg0 >/dev/null 2>&1 || command -v headscale >/dev/null 2>&1; then
    S[mesh]=done; D[mesh]="configured"
  else S[mesh]=todo; D[mesh]="WireGuard or Headscale - never a port forward"; fi

  # personalisation: tracked config ships generic (ADR-0028)
  if grep -q 'principal = "CHANGEME"' "$REPO/config/friday.toml"; then
    S[personal]=todo; D[personal]="principal and timezone not set"
  elif grep -q '^timezone = "UTC"' "$REPO/config/friday.toml"; then
    S[personal]=warn; D[personal]="timezone still UTC - calendar answers will be wrong"
  else S[personal]=done; D[personal]="$(grep -oP '^principal = "\K[^"]+' "$REPO/config/friday.toml")"; fi

  # profile.md - tier 1, hand written, and never generated
  if [[ -f "$ROOT/vault/profile.md" ]]; then
    if grep -q 'Delete this stub text' "$ROOT/vault/profile.md" 2>/dev/null; then
      S[profile]=warn; D[profile]="still the stub - write it by hand, it is tier 1"
    else S[profile]=done; D[profile]="written"; fi
  else S[profile]=todo; D[profile]="you write it, not the installer"; fi
}

dashboard() {
  ui_header "System"
  ui_status "${S[os]}"       "Arch Linux"        "${D[os]}"
  ui_status "${S[gpu]}"      "GPU"               "${D[gpu]}"
  ui_status "${S[disk]}"     "Disk"              "${D[disk]}"

  ui_header "Install  (profile: $PROFILE)"
  ui_status "${S[packages]}" "1  Packages"       "${D[packages]}"
  ui_status "${S[users]}"    "2  Service accounts" "${D[users]}"
  ui_status "${S[tree]}"     "3  Install root"   "${D[tree]}"
  ui_status "${S[secrets]}"  "4  Secrets"        "${D[secrets]}"
  ui_status "${S[venv]}"     "5  Python env"     "${D[venv]}"
  ui_status "${S[models]}"   "6  Weights"        "${D[models]}"
  ui_status "${S[units]}"    "7  Services"       "${D[units]}"
  ui_status "${S[keys]}"     "8  Virtual keys"   "${D[keys]}"
  ui_status "${S[upstream]}" "9  Upstream projects" "${D[upstream]}"

  ui_header "Yours - the installer cannot do these"
  ui_status "${S[personal]}" "name + timezone"   "${D[personal]}"
  ui_status "${S[profile]}"  "vault/profile.md"  "${D[profile]}"
  ui_status "${S[weights]}"  "model repo ids"    "${D[weights]}"
  ui_status "${S[mesh]}"     "mesh + Matrix"     "${D[mesh]}"
}

# --- Steps --------------------------------------------------------------------

step_packages() { ui_run "Packages" bash "$REPO/install/00-arch-packages.sh"; }
step_users()    { ui_run "Service accounts" bash "$REPO/install/01-users.sh"; }
step_tree()     { ui_run "Install root" bash "$REPO/install/tree.sh"; }
step_venv()     { ui_run "Python environment" bash "$REPO/install/02-python-env.sh"; }
step_models()   { ui_run "Weights" bash "$REPO/install/03-models.sh"; }
step_units()    { ui_run "Services" bash "$REPO/install/04-services.sh"; }
step_keys()     { ui_run "Virtual keys" bash "$REPO/install/05-litellm-keys.sh"; }
step_upstream() { ui_run "Upstream projects" bash "$REPO/install/06-upstream.sh"; }

step_secrets() {
  ui_header "Secrets"
  install -d -m 0700 -o root -g root "$ROOT/secrets"

  if [[ ! -f "$ROOT/secrets/age.key" ]]; then
    ui_spin "Generating an age identity" -- age-keygen -o "$ROOT/secrets/age.key"
    chmod 0600 "$ROOT/secrets/age.key"
    ui_ok "wrote $ROOT/secrets/age.key"
  else
    ui_ok "age identity present"
  fi

  local pub; pub="$(grep -oP 'public key: \K\S+' "$ROOT/secrets/age.key")"
  if grep -q 'age1REPLACE' "$REPO/.sops.yaml" 2>/dev/null; then
    ui_note "sops recipient: $pub"
    if ui_confirm "Write that public key into .sops.yaml?"; then
      sed -i "s|age1REPLACE_WITH_YOUR_AGE_PUBLIC_KEY|$pub|g" "$REPO/.sops.yaml"
      ui_ok ".sops.yaml recipient set"
    else
      ui_warn "left the placeholder. Nothing can be encrypted until it is set."
    fi
  fi

  # The one secret week 1 needs. Spec section 8: the master key MINTS per-agent virtual keys
  # and is used for nothing else. No service is ever configured with it.
  if [[ ! -f "$ROOT/secrets/litellm.env.sops" ]]; then
    local tmp; tmp="$(mktemp)"; chmod 600 "$tmp"
    printf 'LITELLM_MASTER_KEY=sk-%s\nLITELLM_DATABASE_URL=sqlite:////srv/friday/db/litellm.db\n' \
      "$(openssl rand -hex 24)" > "$tmp"
    SOPS_AGE_KEY_FILE="$ROOT/secrets/age.key" sops --encrypt "$tmp" > "$ROOT/secrets/litellm.env.sops"
    shred -u "$tmp"
    chmod 0600 "$ROOT/secrets/litellm.env.sops"
    ui_ok "minted and encrypted the LiteLLM master key"
  else
    ui_ok "LiteLLM master key present"
  fi
}

step_personalise() {
  ui_header "Making it yours"
  # Tracked config ships generic so the repo is forkable (ADR-0028). This is the one step
  # that writes your name into it, and it is idempotent.
  local cur; cur="$(grep -oP '^principal = "\K[^"]+' "$REPO/config/friday.toml" || echo CHANGEME)"
  if [[ "$cur" == "CHANGEME" ]]; then
    local who; who="$(ui_input "What should she call you?")"
    [[ -n "$who" ]] && sed -i "s/^principal = \"CHANGEME\"/principal = \"$who\"/" "$REPO/config/friday.toml" \
      && ui_ok "principal = $who"
  else
    ui_ok "principal = $cur"
  fi

  local tz; tz="$(grep -oP '^timezone = "\K[^"]+' "$REPO/config/friday.toml" || echo UTC)"
  if [[ "$tz" == "UTC" ]]; then
    local sys; sys="$(timedatectl show -p Timezone --value 2>/dev/null || echo UTC)"
    ui_note "Timezone is UTC. A wrong one makes every calendar answer wrong in a way that"
    ui_note "looks like a retrieval problem for about two days."
    if [[ "$sys" != "UTC" ]] && ui_confirm "Use this system's timezone ($sys)?"; then
      sed -i "s|^timezone = \"UTC\"|timezone = \"$sys\"|" "$REPO/config/friday.toml"
      ui_ok "timezone = $sys"
    fi
  else
    ui_ok "timezone = $tz"
  fi
}

step_profile_md() {
  ui_header "vault/profile.md"
  ui_doc "Spec section 11, and the last line of the whole document: **you write this by hand.**
It is tier 1 of four, about 1500 tokens, injected into every prompt. It is the seed
everything else grows from and the reason she will feel like she knows you.

The installer does not generate it. That is not a limitation."
  if ui_confirm "Open it in \$EDITOR now?"; then
    sudo -u friday "${EDITOR:-nano}" "$ROOT/vault/profile.md"
  else
    ui_note "Later: sudo -u friday \$EDITOR $ROOT/vault/profile.md"
  fi
}

run_all() {
  local failed=0
  for s in packages users tree secrets venv models units keys upstream; do
    [[ "${S[$s]}" == "done" ]] && { ui_ok "$s already done, skipping"; continue; }
    "step_${s}" || { failed=1; break; }
    detect
  done
  return $failed
}

# --- What still needs a human -------------------------------------------------
# Computed from live state rather than printed unconditionally, so it shrinks as you work
# through it and says nothing when there is nothing left.
report_manual() {
  local -a todo=()
  [[ "${S[weights]}"  != "done" ]] && todo+=("Model repo ids: edit the table at the top of install/03-models.sh. Spec section 1 says verify current picks before downloading, so the script refuses to run rather than fetching something wrong.")
  [[ "${S[upstream]}" != "done" ]] && todo+=("Upstream projects: run step 9, or see /tmp/friday-manual-steps.txt if it already ran.")
  [[ "${S[mesh]}"     != "done" ]] && todo+=("The mesh: WireGuard or Headscale. Spec section 9 - the phone reaches Conduit over the mesh or not at all. Never a port forward.")
  [[ "${S[personal]}" != "done" ]] && todo+=("Name and timezone: run \"Make it mine\". A wrong timezone makes every calendar answer wrong in a way that reads as a retrieval problem.")
  [[ "${S[profile]}"  != "done" ]] && todo+=("vault/profile.md: you write it by hand. Tier 1 of four, injected into every prompt. Not generated, and that is not a limitation.")

  # Conduit and the bridge are genuinely interactive: registering accounts and linking a
  # bridge means scanning a code from your phone. No script can do it for you.
  todo+=("Conduit: register your account and a 'friday' account, then link ONE bridge from your Matrix client. Spec section 10 - bridge instability is the first thing that breaks, so add a second only after the first survives a week.")

  if [[ ${#todo[@]} -eq 0 ]]; then
    ui_summary "Week 1 complete" "Nothing left for a human." "Done when: you chat locally, and you text her from your phone."
  else
    ui_summary "Needs you (${#todo[@]})" "${todo[@]}"
  fi
}

# --- Profile choice -----------------------------------------------------------
choose_profile() {
  ui_header "Profile"
  ui_doc "**dev** - small or no GPU. Aliases collapse onto small models. Everything is
buildable and testable; answer quality is not comparable.

**target** - 24 GB VRAM, Qwen 3.6 27B @ Q4. Every \"done when\" in docs/weeks/ is
written against this one, including the 20/25 eval gate.

Retrieval *is* comparable across both, because the embedding and reranking models are
identical. See ADR-0025."
  local p; p="$(ui_choose "Which profile is this box?" "dev" "target")"
  [[ -n "$p" ]] || return 0
  install -d -m 0755 /etc/friday
  printf '%s\n' "$p" > /etc/friday/profile
  PROFILE="$p"
  ui_ok "profile set to $p"
}

# --- Main ---------------------------------------------------------------------
detect

if [[ -n "${FRIDAY_STEP:-}" ]]; then
  "step_${FRIDAY_STEP}" ; exit $?
fi

while true; do
  dashboard

  if [[ "${S[os]}" == "fail" ]]; then
    ui_err "${D[os]}"
    exit 1
  fi

  echo
  choice="$(ui_choose "What now?" \
    "Install everything that is not done" \
    "Run one step" \
    "Change profile (currently: $PROFILE)" \
    "Preflight (reads, changes nothing)" \
    "What still needs me" \
    "Make it mine (name, timezone)" \
    "Write vault/profile.md" \
    "What gets installed, and why" \
    "Quit")"

  case "$choice" in
    "Install everything"*)
      if ui_confirm "Install everything still outstanding, on profile '$PROFILE'?"; then
        run_all
        detect
        report_manual
      fi ;;
    "Run one step")
      s="$(ui_choose "Which step?" packages users tree secrets venv models units keys upstream)"
      [[ -n "$s" ]] && "step_${s}" ; detect ;;
    "Change profile"*) choose_profile ; detect ;;
    "Preflight"*)      bash "$REPO/install/preflight.sh" || true ;;
    "What still needs me") report_manual ;;
    "Make it mine"*)   step_personalise ; detect ;;
    "Write vault"*)    step_profile_md ; detect ;;
    "What gets installed"*)
      if [[ $UI_HAS_GUM -eq 1 ]]; then gum pager < "$REPO/docs/INSTALL.md"
      else "${PAGER:-less}" "$REPO/docs/INSTALL.md"; fi ;;
    "Quit"|"") ui_note "Nothing was left half-applied; re-run any time." ; exit 0 ;;
  esac
done
