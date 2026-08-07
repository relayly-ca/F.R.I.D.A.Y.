#!/usr/bin/env bash
# The Python environment under $ROOT, owned by friday. This is what the systemd units run.
#
# Pinned to 3.12. Arch's `python` rolls forward, and a venv tracking it breaks on an
# unrelated -Syu - at which point every service fails to start at once, on a day you changed
# nothing. pyproject.toml pins the same range; if these two ever disagree, this file is wrong.
#
#   sudo bash install/02-python-env.sh

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

need_root
need_users
banner_profile

PY_VERSION=3.12
[[ -d "$ROOT" ]] || die "$ROOT does not exist. Run install/tree.sh first."

log "uv and Python $PY_VERSION"
command -v uv >/dev/null 2>&1 || die "uv not found. Run install/00-arch-packages.sh first."

# uv keeps its downloaded interpreters and caches per user, so this runs as `friday` - the
# user that will actually execute the venv. Running it as root produces an environment with
# root-owned cache entries that friday cannot refresh.
install -d -m 0755 -o friday -g friday "$ROOT/.cache"
sudo -u friday env HOME="$ROOT" XDG_CACHE_HOME="$ROOT/.cache" uv python install "$PY_VERSION"

log "Virtual environment at $ROOT/.venv"
sudo -u friday env HOME="$ROOT" XDG_CACHE_HOME="$ROOT/.cache" \
  uv venv --python "$PY_VERSION" "$ROOT/.venv"

log "Installing the project"
# --no-dev: this is the runtime environment. pytest, ruff and mypy belong in the repo-local
# venv that `make test` uses, not on the box running the services.
sudo -u friday env HOME="$ROOT" XDG_CACHE_HOME="$ROOT/.cache" VIRTUAL_ENV="$ROOT/.venv" \
  uv pip install --python "$ROOT/.venv/bin/python" -e "$REPO"

# Voice extra is heavy and W4 is the first week that needs it. Opt in.
if [[ "${WITH_VOICE:-0}" == "1" ]]; then
  log "Voice extra (W4)"
  sudo -u friday env HOME="$ROOT" XDG_CACHE_HOME="$ROOT/.cache" \
    uv pip install --python "$ROOT/.venv/bin/python" -e "$REPO[voice]"
fi

log "Verification"
printf '%-16s %s\n' "python" "$("$ROOT/.venv/bin/python" --version 2>&1)"
printf '%-16s %s\n' "owner"  "$(stat -c '%U:%G' "$ROOT/.venv")"

# The config layer validates every file and cross-checks them. A config error found here
# costs a second; the same error found by a systemd unit costs a journal read.
log "Config validation"
if sudo -u friday env HOME="$ROOT" "$ROOT/.venv/bin/python" -m friday.config --check; then
  info "config ok"
else
  die "configuration did not validate. Fix it before installing units."
fi

cat <<'EOF'

Next: sudo bash install/03-models.sh
EOF
