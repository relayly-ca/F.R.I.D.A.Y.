#!/usr/bin/env bash
# Weights, for the active profile. ADR-0025.
#
# Spec section 1 gives the model table and then says: "Verify current picks before
# downloading." Take that seriously - names move and quantisations get re-cut. The table
# below is the ONE place to correct them, which is why it is a table at the top of a script
# and not scattered through a week guide.
#
# Profile decides what gets pulled: dev is a few GB, target is around forty.
#
#   sudo bash install/03-models.sh
#   sudo FRIDAY_PROFILE=dev bash install/03-models.sh

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

need_root
need_users
banner_profile

MODELS_DIR="$ROOT/models"
install -d -m 0755 -o friday -g friday "$MODELS_DIR"

# --- The table. `# VERIFY:` every row before the first run. --------------------
# Format:  <local-name>|<hf-repo>|<file-glob>
#
# local-name is what /etc/friday/llama/*.env points at, so changing a repo here does not
# touch a unit file.
declare -A MODEL_REPO=(
  [daily-model]="# VERIFY: Qwen 3.6 27B Q4 GGUF repo"
  [fast-model]="# VERIFY: 4B router GGUF repo (spec section 8 names gemma4-4b)"
  [coder-model]="# VERIFY: Devstral-2 22B Q4 GGUF repo"
  [vision-model]="# VERIFY: Qwen3-VL GGUF repo"
  [bge-m3]="# VERIFY: bge-m3 GGUF repo"
  [bge-reranker-v2-m3]="# VERIFY: bge-reranker-v2-m3 GGUF repo"
)
declare -A MODEL_FILE=(
  [daily-model]="*Q4_K_M.gguf"
  [fast-model]="*Q4_K_M.gguf"
  [coder-model]="*Q4_K_M.gguf"
  [vision-model]="*Q4_K_M.gguf"
  [bge-m3]="*f16.gguf"
  [bge-reranker-v2-m3]="*f16.gguf"
)

command -v hf >/dev/null 2>&1 || {
  warn "the huggingface CLI is missing. Installing it as a uv tool."
  sudo -u "${SUDO_USER:-friday}" uv tool install "huggingface_hub[cli]"
}

# --- What this profile needs --------------------------------------------------
# Ask the profile rather than deciding here, so the two cannot disagree.
mapfile -t WANTED < <("$ROOT/.venv/bin/python" - <<'PY'
from friday.profile import active
for alias, model in active().aliases.items():
    if model:
        print(model)
PY
)
# Deduplicate: on dev, daily/fast/coder all resolve to the same model and it downloads once.
mapfile -t WANTED < <(printf '%s\n' "${WANTED[@]}" | sort -u)

log "Models for this profile"
printf '  %s\n' "${WANTED[@]}"

UNVERIFIED=0
for name in "${WANTED[@]}"; do
  repo="${MODEL_REPO[$name]:-}"
  [[ -n "$repo" ]] || die "no repository recorded for '$name'. Add a row to the table in $0."
  if [[ "$repo" == \#\ VERIFY:* ]]; then
    warn "$name: $repo"
    UNVERIFIED=1
  fi
done

if [[ $UNVERIFIED -eq 1 ]]; then
  cat <<'EOF'

Some rows are still placeholders. Spec section 1: verify current picks before downloading.

Search Hugging Face for the GGUF conversion of each, then edit the MODEL_REPO table at the
top of install/03-models.sh and re-run. Correcting them here is the whole point of the table
being in one place.
EOF
  exit 1
fi

# --- Download. hf skips files already present, so this is re-runnable. ---------
for name in "${WANTED[@]}"; do
  target="$MODELS_DIR/$name.gguf"
  if [[ -f "$target" ]]; then
    info "$name present ($(du -h "$target" | cut -f1))"
    continue
  fi
  log "Downloading $name"
  tmp="$MODELS_DIR/.dl-$name"
  install -d -m 0755 -o friday -g friday "$tmp"
  sudo -u friday env HOME="$ROOT" hf download "${MODEL_REPO[$name]}" \
    --include "${MODEL_FILE[$name]}" --local-dir "$tmp"
  found="$(find "$tmp" -name '*.gguf' -print -quit)"
  [[ -n "$found" ]] || die "no .gguf found in $tmp after download"
  mv "$found" "$target"
  chown friday:friday "$target"
  rm -rf "$tmp"
  info "wrote $target"
done

log "Verification"
du -sh "$MODELS_DIR"
ls -1sh "$MODELS_DIR"/*.gguf 2>/dev/null || warn "no .gguf files in $MODELS_DIR"

cat <<'EOF'

Next: sudo bash install/04-services.sh
EOF
