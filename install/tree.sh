#!/usr/bin/env bash
# Create the install root. This is spec section 11's mkdir, made idempotent and given
# ownership and modes.
#
# The spec's command is:
#
#   sudo mkdir -p /srv/friday/{vault/{daily,projects,people,ideas},db,agent/{skills,tools,prompts,core},loops,ingest,work,eval,logs}
#   cd /srv/friday && git init work
#
# Everything below produces exactly that tree. If you ever change this script, the spec
# command must still describe the result, or one of the two is wrong.
#
#   sudo bash install/tree.sh

set -euo pipefail

ROOT=${ROOT:-/srv/friday}

log() { printf '\n=== %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run as root: sudo bash $0"
id -u friday    >/dev/null 2>&1 || die "User friday missing. Run install/01-users.sh first."
id -u fridaysup >/dev/null 2>&1 || die "User fridaysup missing. Run install/01-users.sh first."

log "Install root at $ROOT"
install -d -m 0755 -o friday -g friday "$ROOT"

# --- Memory tiers. Spec section 7. -------------------------------------------
# Tier 3 is the vault: markdown, four subdirectories, written by the consolidation
# loop and editable by you.
log "vault (tier 3)"
install -d -m 0750 -o friday -g friday "$ROOT/vault"
for d in daily projects people ideas; do
  install -d -m 0750 -o friday -g friday "$ROOT/vault/$d"
done

# Tier 1 is profile.md: hand-written, ~1500 tokens, injected into every prompt. It is
# NOT generated, so this script only leaves a stub with instructions and never
# overwrites an existing one.
if [[ ! -e "$ROOT/vault/profile.md" ]]; then
  cat > "$ROOT/vault/profile.md" <<'PROFILE'
# profile.md

Write this by hand. Do not generate it.

Spec section 7 and section 11: this is tier one of four, about 1500 tokens, injected
into every prompt. It is the seed everything else grows from and the reason she will
feel like she knows you. Hermes's Honcho user model feeds proposals into it; you
approve them, they are not written here automatically.

Roughly what belongs here, in your own words rather than as headings to fill in:
who you are and what you do, the people who matter and how you refer to them, the
projects currently live, how you like to be spoken to, what you never want her to do
without asking, and the standing facts she should never have to retrieve.

Delete this stub text once you have written the real thing.
PROFILE
  chown friday:friday "$ROOT/vault/profile.md"
  chmod 0640 "$ROOT/vault/profile.md"
  echo "wrote $ROOT/vault/profile.md stub - replace it by hand"
else
  echo "$ROOT/vault/profile.md exists, leaving it alone"
fi

# Tier 2 and 4 live here: episodic.db (append-only), the FTS5 tables, and Qdrant
# storage.
log "db (tiers 2 and 4)"
install -d -m 0750 -o friday -g friday "$ROOT/db"

# --- Agent runtime. Spec section 9. ------------------------------------------
log "agent"
install -d -m 0755 -o friday -g friday "$ROOT/agent"
for d in skills tools prompts; do
  install -d -m 0755 -o friday -g friday "$ROOT/agent/$d"
done

# The one line in this file that carries a security property.
#
# Spec section 9: "Agent runs as friday; agent/core/ owned by the supervisor user. The
# agent writes skills, tools, prompts, configs - never the loop that runs them."
#
# Owner fridaysup, mode 0755: world-readable and executable so she can load her
# orchestration loop, writable only by fridaysup so she cannot change it. Do not
# "fix" this to 0775 or chown it to friday. If something appears to need that, the
# something is wrong.
install -d -m 0755 -o fridaysup -g fridaysup "$ROOT/agent/core"
find "$ROOT/agent/core" -mindepth 1 -exec chown fridaysup:fridaysup {} + 2>/dev/null || true
find "$ROOT/agent/core" -mindepth 1 -type f -exec chmod 0644 {} + 2>/dev/null || true
find "$ROOT/agent/core" -mindepth 1 -type d -exec chmod 0755 {} + 2>/dev/null || true

# --- Everything else from section 11 -----------------------------------------
log "loops, ingest, eval, logs"
for d in loops ingest eval logs; do
  install -d -m 0750 -o friday -g friday "$ROOT/$d"
done
install -d -m 0755 -o friday -g friday "$ROOT/models"
install -d -m 0750 -o friday -g friday "$ROOT/backups"

# Secrets: root-owned 0700. Neither service account can list it. Spec section 9,
# capabilities not credentials - the helper reads these, she does not.
install -d -m 0700 -o root -g root "$ROOT/secrets"

# --- work: the agent's git repository ----------------------------------------
# Spec section 11: `cd /srv/friday && git init work`. Spec section 9: branch only,
# human merge. This is where OpenHands does its work; Forgejo hosts the remote.
log "work (agent branches, human merges)"
install -d -m 0750 -o friday -g friday "$ROOT/work"
if [[ ! -d "$ROOT/work/.git" ]]; then
  sudo -u friday git -C "$ROOT/work" init -q
  sudo -u friday git -C "$ROOT/work" commit -q --allow-empty -m "work: initial"
  echo "initialised $ROOT/work"
else
  echo "$ROOT/work already a git repository"
fi

# The vault is a git repository too, so a bad consolidation is revertible and the
# supervisor can revert to the pre-run commit.
if [[ ! -d "$ROOT/vault/.git" ]]; then
  sudo -u friday git -C "$ROOT/vault" init -q
  sudo -u friday git -C "$ROOT/vault" add -A
  sudo -u friday git -C "$ROOT/vault" commit -q -m "vault: initial" || true
  echo "initialised $ROOT/vault as a git repository"
fi

# --- Verify the boundary rather than asserting it ----------------------------
log "Verification"
printf '%-34s %s\n' "$ROOT/agent/core" "$(stat -c '%U:%G %a' "$ROOT/agent/core")"
printf '%-34s %s\n' "$ROOT/agent/skills" "$(stat -c '%U:%G %a' "$ROOT/agent/skills")"
printf '%-34s %s\n' "$ROOT/secrets" "$(stat -c '%U:%G %a' "$ROOT/secrets")"

if sudo -u friday test -w "$ROOT/agent/core"; then
  die "FAILED: the friday user can write agent/core/. Spec section 9 is not in force."
fi
echo "OK: the friday user cannot write agent/core/"

log "Tree"
find "$ROOT" -maxdepth 2 -type d -not -path '*/.git*' | sort | sed "s|^$ROOT|/srv/friday|"

cat <<'EOF'

Now write /srv/friday/vault/profile.md by hand. Not generated - you write it.
It is the seed everything else grows from.
EOF
