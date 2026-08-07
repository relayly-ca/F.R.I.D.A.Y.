#!/usr/bin/env bash
# systemd units, rendered for the active profile.
#
# Two things happen here beyond copying files, and both are gates rather than conveniences:
#
#   1. The config layer validates every file and cross-checks them.
#   2. The profile's `may_not_change` constraints are re-verified against the live config.
#
# If either fails, no unit is installed. A box that refuses to start is better than one that
# starts with a security property quietly relaxed.
#
#   sudo bash install/04-services.sh

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

need_root
need_users
banner_profile

PY="$ROOT/.venv/bin/python"
[[ -x "$PY" ]] || die "no venv at $ROOT/.venv. Run install/02-python-env.sh first."

# --- Gate 1: the configuration parses and agrees with itself ------------------
log "Config validation"
sudo -u friday env HOME="$ROOT" "$PY" -m friday.config --check \
  || die "configuration did not validate. Nothing installed."

# --- Gate 2: the profile has not relaxed an invariant -------------------------
log "Profile constraints (ADR-0025)"
sudo -u friday env HOME="$ROOT" "$PY" - <<'PY' || die "profile constraint check failed. Nothing installed."
import sys
from friday.profile import verify_constraints, active_name
violations = verify_constraints()
if violations:
    print(f"profile {active_name()!r} relaxes invariants it may not:", file=sys.stderr)
    for v in violations:
        print(f"  - {v}", file=sys.stderr)
    sys.exit(1)
print("  constraints hold")
PY

# --- Render the profile's llama env files and LiteLLM config ------------------
log "Rendering for profile $(friday_profile)"
install -d -m 0755 /etc/friday /etc/friday/llama
sudo -u friday env HOME="$ROOT" "$PY" - <<'PY'
from pathlib import Path
from friday.profile import render_litellm, render_llama_env
written = render_llama_env(Path("/etc/friday/llama"))
for p in written:
    print(f"  {p}")
render_litellm(Path("/etc/friday/litellm.yaml"))
print("  /etc/friday/litellm.yaml")
PY
chmod 0644 /etc/friday/llama/*.env /etc/friday/litellm.yaml

# Persist the profile so units and preflight agree with the shell that installed them.
friday_profile > /etc/friday/profile
chmod 0644 /etc/friday/profile

# --- Install units ------------------------------------------------------------
log "systemd units"
for unit in "$REPO"/systemd/*.service "$REPO"/systemd/*.timer; do
  [[ -e "$unit" ]] || continue
  install -m 0644 "$unit" /etc/systemd/system/
  info "$(basename "$unit")"
done
systemctl daemon-reload

# --- Enable the week-1 set ----------------------------------------------------
# Only what W1 needs. Later weeks enable their own; a script that enables everything leaves
# units failing for months because their dependencies do not exist yet.
log "Enabling the week-1 set"
mapfile -t SERVED < <(sudo -u friday env HOME="$ROOT" "$PY" -c \
  "from friday.profile import active; print('\n'.join(active().served()))")

for alias in "${SERVED[@]}"; do
  # coder and vision are on demand - enabled, not started. They evict daily.
  if [[ "$alias" == "coder" || "$alias" == "vision" ]]; then
    systemctl enable "friday-llama@${alias}.service" >/dev/null
    info "friday-llama@${alias} enabled (on demand)"
  else
    systemctl enable --now "friday-llama@${alias}.service"
    info "friday-llama@${alias} started"
  fi
done

systemctl enable --now friday-litellm.service

log "Status"
systemctl list-units 'friday-*' --all --no-pager --no-legend \
  | awk '{printf "  %-34s %-9s %s\n", $1, $3, $4}'

cat <<'EOF'

Check that the alias answers:

  curl -s http://127.0.0.1:4000/health/readiness | jq .

Then: sudo bash install/05-litellm-keys.sh
EOF
