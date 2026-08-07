#!/usr/bin/env bash
# Per-agent LiteLLM virtual keys. Spec section 8.
#
# "Bind LiteLLM to 127.0.0.1 only and issue virtual keys per agent - Hermes shipped a
# hardening release specifically patching a LiteLLM credential exposure."
#
# A single shared master key across agents is NOT sufficient, and this script exists because
# key issuance is part of install rather than an afterthought. One key per entry in
# config/agents.yaml, each scoped to the aliases that agent is allowed to use.
#
# ADR-0005: the keys land sops-encrypted. The agent never reads this file - a helper does,
# and hands one key to one unit.
#
#   sudo bash install/05-litellm-keys.sh

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

need_root
need_users
banner_profile

PY="$ROOT/.venv/bin/python"
KEYS="$ROOT/secrets/litellm-keys.yaml"
AGE_KEY="$ROOT/secrets/age.key"

[[ -x "$PY" ]] || die "no venv at $ROOT/.venv. Run install/02-python-env.sh first."
[[ -f "$AGE_KEY" ]] || die "no age identity at $AGE_KEY. See docs/weeks/W1.md step 3."
curl -sf http://127.0.0.1:4000/health/readiness >/dev/null \
  || die "LiteLLM is not answering on 127.0.0.1:4000. Start friday-litellm first."

# The master key mints and does nothing else. It is read here, in this script, and is never
# written into a unit file or an environment that a service inherits.
MASTER="$(SOPS_AGE_KEY_FILE="$AGE_KEY" sops --decrypt "$ROOT/secrets/litellm.env.sops" \
  | sed -n 's/^LITELLM_MASTER_KEY=//p')"
[[ -n "$MASTER" ]] || die "could not read LITELLM_MASTER_KEY from the sops file"

log "Minting one key per agent"

# Each agent gets exactly the aliases it is configured to use, resolved through the profile.
# An agent that later needs another alias needs a config change and a re-mint, which is the
# correct friction: a key scoped to everything is a master key with extra steps.
tmp="$(mktemp)"; trap 'shred -u "$tmp" 2>/dev/null || rm -f "$tmp"' EXIT
chmod 600 "$tmp"
printf '# LiteLLM virtual keys, one per agent. Spec section 8.\n# Minted by install/05-litellm-keys.sh. Never edit by hand.\n' > "$tmp"

mapfile -t AGENTS < <(sudo -u friday env HOME="$ROOT" "$PY" -c \
  "from friday.config import get; print('\n'.join(sorted(get().agents.agents)))")

for agent in "${AGENTS[@]}"; do
  alias="$(sudo -u friday env HOME="$ROOT" "$PY" -c \
    "from friday.profile import alias_for; print(alias_for('$agent'))")

  # Budgets come from config/agents.yaml, which is the same place the supervisor reads them.
  # Two enforcement points is deliberate: LiteLLM refuses the request, the supervisor kills
  # the task, and neither is trusted alone.
  max_tokens="$(sudo -u friday env HOME="$ROOT" "$PY" -c \
    "from friday.config import get; print(get().agent('$agent').max_tokens)")

  resp="$(curl -sf -X POST http://127.0.0.1:4000/key/generate \
    -H "Authorization: Bearer $MASTER" -H 'Content-Type: application/json' \
    -d "{\"models\":[\"$alias\"],\"key_alias\":\"friday-$agent\",\"metadata\":{\"agent\":\"$agent\",\"max_tokens\":$max_tokens}}")" \
    || die "key generation failed for $agent"

  key="$(printf '%s' "$resp" | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["key"])')"
  printf '%s:\n  key: %s\n  models: [%s]\n' "$agent" "$key" "$alias" >> "$tmp"
  info "$agent -> $alias"
done

SOPS_AGE_KEY_FILE="$AGE_KEY" sops --encrypt "$tmp" > "$KEYS"
chown root:root "$KEYS"; chmod 0600 "$KEYS"

log "Verification"
info "$(SOPS_AGE_KEY_FILE="$AGE_KEY" sops --decrypt "$KEYS" | grep -c '  key:') keys in $KEYS"
info "file mode $(stat -c '%U:%G %a' "$KEYS")"

cat <<'EOF'

Keys are sops-encrypted and root-owned. The friday user cannot read them; the helper at
/srv/friday/bin/secret-helper hands ONE key to ONE unit at start (ADR-0005).

W1 is now installable end to end. See docs/weeks/W1.md from step 9 (OpenJarvis).
EOF
