#!/usr/bin/env bash
# Service accounts. Spec section 9: "Agent runs as friday; agent/core/ owned by the
# supervisor user."
#
#   friday      runs everything except the supervisor. No login shell.
#   fridaysup   runs only the supervisor. Owns agent/core/. No login shell.
#
# The point: she can execute her orchestration loop and cannot write it. Enforced by
# ownership, not by an instruction in a prompt that a sufficiently confused model will
# talk itself out of.
#
# Idempotent. Re-running is also how you repair permissions after a careless chown.
#
#   sudo bash install/01-users.sh

set -euo pipefail

ROOT=${ROOT:-/srv/friday}

log() { printf '\n=== %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run as root: sudo bash $0"

log "Service accounts"
if ! id -u friday >/dev/null 2>&1; then
  useradd --system --create-home --home-dir "$ROOT" \
          --shell /usr/bin/nologin --comment "FRIDAY services" friday
  echo "created friday"
else
  echo "friday exists"
fi

if ! id -u fridaysup >/dev/null 2>&1; then
  useradd --system --no-create-home --home-dir "$ROOT" \
          --shell /usr/bin/nologin --comment "FRIDAY supervisor" fridaysup
  echo "created fridaysup"
else
  echo "fridaysup exists"
fi

# No password, no SSH key, no su.
passwd -l friday    >/dev/null
passwd -l fridaysup >/dev/null

# Audio for the voice pipeline in weeks 4-5. Harmless before then.
getent group audio >/dev/null && usermod -aG audio friday

# The supervisor must read what it supervises without being able to be it.
usermod -aG friday fridaysup
# The reverse is deliberately NOT done. friday is not in the fridaysup group.

log "Supervisor privileges"
# Spec section 9: the supervisor kills over-budget tasks and reverts to last-known-good.
# It needs to manage friday-* units, and nothing else. That comes from a narrow polkit
# rule, not from sudo and not from a NOPASSWD line.
install -d -m 0755 /etc/polkit-1/rules.d
cat > /etc/polkit-1/rules.d/49-friday-supervisor.rules <<'RULES'
// FRIDAY supervisor: manage friday-* units only.
//
// The whole of fridaysup's elevated privilege. It cannot install packages, cannot write
// outside its own files, and cannot manage any unit whose name does not start with
// "friday-". friday-supervisor.service itself is excluded, so the supervisor can neither
// stop itself nor be stopped by anything it supervises.
polkit.addRule(function(action, subject) {
    if (action.id == "org.freedesktop.systemd1.manage-units" &&
        subject.user == "fridaysup") {
        var unit = action.lookup("unit");
        if (unit && unit.indexOf("friday-") === 0 &&
            unit != "friday-supervisor.service") {
            return polkit.Result.YES;
        }
    }
    return polkit.Result.NOT_HANDLED;
});
RULES
chmod 0644 /etc/polkit-1/rules.d/49-friday-supervisor.rules
systemctl restart polkit.service 2>/dev/null || true

log "Verification"
for u in friday fridaysup; do
  printf '%-12s %s\n' "$u" "$(getent passwd "$u" | cut -d: -f7)"
done

cat <<'EOF'

Next: sudo bash install/tree.sh
EOF
