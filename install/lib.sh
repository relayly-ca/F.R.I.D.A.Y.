#!/usr/bin/env bash
# Shared helpers for install/*.sh. Sourced, never executed.
#
# The only interesting thing in here is profile resolution (ADR-0025). Everything else is
# logging and guards that would otherwise be copy-pasted into six scripts and drift.

# Not `set -e` here: this file is sourced, and forcing options onto the caller's shell is
# how a sourced library breaks a script that had different intentions.

ROOT=${ROOT:-/srv/friday}
REPO=${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}

# The UI layer. gum-backed, with a plain fallback for when gum is not installed yet - which
# is the normal state during the step that installs it.
# shellcheck source=install/ui.sh
source "$(dirname "${BASH_SOURCE[0]}")/ui.sh"

log()  { ui_header "$*"; }
info() { ui_ok "$*"; }
warn() { ui_warn "$*"; }
die()  { ui_die "$*"; }

need_root() { [[ $EUID -eq 0 ]] || die "Run as root: sudo bash $0"; }

need_users() {
  id -u friday    >/dev/null 2>&1 || die "user friday missing. Run install/01-users.sh first."
  id -u fridaysup >/dev/null 2>&1 || die "user fridaysup missing. Run install/01-users.sh first."
}

# --- Profile. ADR-0025. -------------------------------------------------------
# Precedence: FRIDAY_PROFILE, then /etc/friday/profile, then `target`.
#
# The default is `target` on purpose. A forgotten setting must degrade toward the correct
# system rather than away from it - the failure where someone ships the real box still on
# dev weights is silent, and the reverse fails loudly at model load.
friday_profile() {
  local p="${FRIDAY_PROFILE:-}"
  [[ -z "$p" && -r /etc/friday/profile ]] && p="$(tr -d '[:space:]' < /etc/friday/profile)"
  p="${p:-target}"
  case "$p" in
    dev|target) printf '%s' "$p" ;;
    *) die "unknown profile '$p'. config/profiles.yaml defines: dev, target" ;;
  esac
}

# Read one scalar out of config/profiles.yaml for the active profile.
#   profile_get min_vram_mb
#
# Python rather than yq: pyyaml is already a dependency and yq is not, and adding a tool to
# read one number is the kind of thing that makes an install script fail on a fresh box.
profile_get() {
  local key="$1" prof; prof="$(friday_profile)"
  python3 - "$REPO/config/profiles.yaml" "$prof" "$key" <<'PY'
import sys, yaml
path, prof, key = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path) as fh:
    data = yaml.safe_load(fh)
node = data["profiles"][prof]
for part in key.split("."):
    node = node[part]
if isinstance(node, (list, tuple)):
    print(" ".join(str(x) for x in node))
elif isinstance(node, bool):
    print("true" if node else "false")
elif node is None:
    print("")
else:
    print(node)
PY
}

banner_profile() {
  local p; p="$(friday_profile)"
  printf '\nprofile: %s%s%s   root: %s\n' "$_GRN" "$p" "$_OFF" "$ROOT"
  [[ "$p" == "dev" ]] && warn "dev profile: small models, reduced resident set. The 20/25 eval gate is a TARGET gate (ADR-0025)."
  return 0
}
