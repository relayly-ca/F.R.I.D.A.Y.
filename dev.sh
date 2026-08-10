#!/usr/bin/env bash
# FRIDAY dev launcher. Gum-based, user-space, no sudo.
#
# Runs FRIDAY from the repo directory without systemd, without /srv/friday,
# without root. Everything in ~/.local/share/friday-dev/ for this session.
#
#   bash dev.sh           interactive menu
#   bash dev.sh start     start everything
#   bash dev.sh stop      stop everything
#   bash dev.sh status    show what's running
#   bash dev.sh wall      launch the dashboard

set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
DATA_DIR="${FRIDAY_DEV_DIR:-$HOME/.local/share/friday-dev}"
MODELS_DIR="${FRIDAY_MODELS_DIR:-$DATA_DIR/models}"
PID_DIR="$DATA_DIR/pids"
LOG_DIR="$DATA_DIR/logs"
DB_DIR="$DATA_DIR/db"
VAULT_DIR="$DATA_DIR/vault"
VENV_PYTHON="$REPO/.venv/bin/python"

mkdir -p "$MODELS_DIR" "$PID_DIR" "$LOG_DIR" "$DB_DIR" "$VAULT_DIR"

# --- Colors and UI -----------------------------------------------------------
if command -v gum &>/dev/null; then
  HAVE_GUM=1
  header() { gum style --border rounded --padding "0 1" --foreground 212 -- "$1"; }
  info()  { gum style --foreground 39 -- "$1"; }
  warn()  { gum style --foreground 208 -- "$1"; }
  err()   { gum style --foreground 196 -- "$1"; }
  ok()    { gum style --foreground 76 -- "$1"; }
else
  HAVE_GUM=0
  header() { echo "=== $1 ==="; }
  info()  { echo "  $1"; }
  warn()  { echo "  WARN: $1"; }
  err()   { echo "  ERROR: $1"; }
  ok()    { echo "  OK: $1"; }
fi

# --- Status helpers ----------------------------------------------------------
is_running() { [[ -f "$PID_DIR/$1" ]] && kill -0 "$(cat "$PID_DIR/$1" 2>/dev/null)" 2>/dev/null; }
pid_of() { cat "$PID_DIR/$1" 2>/dev/null; }

start_proc() {
  local name="$1"
  shift
  if is_running "$name"; then
    warn "$name already running (pid $(pid_of "$name"))"
    return 0
  fi
  "$@" >"$LOG_DIR/$name.log" 2>&1 &
  echo $! >"$PID_DIR/$name"
  info "started $name (pid $!)"
}

stop_proc() {
  local name="$1"
  if ! is_running "$name"; then
    info "$name not running"
    rm -f "$PID_DIR/$name"
    return 0
  fi
  local pid; pid="$(pid_of "$name")"
  kill "$pid" 2>/dev/null || true
  sleep 1
  kill -9 "$pid" 2>/dev/null || true
  rm -f "$PID_DIR/$name"
  ok "stopped $name"
}

# --- Config generation -------------------------------------------------------
generate_litellm_config() {
  local cfg="$DATA_DIR/litellm.yaml"
  cat >"$cfg" <<YAML
model_list:
  - model_name: daily
    litellm_params:
      model: openai/qwen3-4b
      api_base: http://127.0.0.1:8080/v1
      api_key: dummy
      timeout: 600
  - model_name: fast
    litellm_params:
      model: openai/qwen3-4b
      api_base: http://127.0.0.1:8081/v1
      api_key: dummy
      timeout: 60
  - model_name: embed
    litellm_params:
      model: openai/bge-m3
      api_base: http://127.0.0.1:8082/v1
      api_key: dummy
      timeout: 120
  - model_name: rerank
    litellm_params:
      model: openai/bge-reranker-v2-m3
      api_base: http://127.0.0.1:8085/v1
      api_key: dummy
      timeout: 120

router_settings:
  fallbacks:
    - {daily: [fast]}
  allowed_fails: 2
  cooldown_time: 30

litellm_settings:
  num_retries: 2
  request_timeout: 600
  drop_params: true

general_settings:
  telemetry: false
YAML
  echo "$cfg"
}

# --- Friday.toml for dev ------------------------------------------------------
generate_friday_toml() {
  local cfg="$DATA_DIR/friday.toml"
  cat >"$cfg" <<TOML
[general]
principal = "$(whoami)"
timezone = "$(timedatectl show --property=Timezone --value 2>/dev/null || echo 'UTC')"
log_level = "info"
debug_prompts = false

[paths]
root = "$DATA_DIR"
vault = "$VAULT_DIR"
db = "$DB_DIR"
agent = "$DATA_DIR/agent"
core = "$DATA_DIR/agent/core"
loops = "$DATA_DIR/loops"
ingest = "$DATA_DIR/ingest"
work = "$DATA_DIR/work"
eval = "$DATA_DIR/eval"
logs = "$LOG_DIR"
models = "$MODELS_DIR"
secrets = "$DATA_DIR/secrets"

[config]
scrutiny = "config/scrutiny.yaml"
agents = "config/agents.yaml"
memory = "config/memory.yaml"
sources = "config/sources.yaml"

[models]
litellm_base_url = "http://127.0.0.1:4000"
virtual_keys = "$DATA_DIR/litellm-keys.yaml"

[tracing]
enabled = false

[voice]
enabled = false

[output]
ai_chosen_surface = true
surfaces = ["text", "wall"]
default_surface = "text"

[supervisor]
health_check_interval_s = 30
failures_before_revert = 3
known_good_requires_eval = true
managed_units = []

[budgets]
tokens_per_hour = 2000000
tokens_per_day = 20000000
concurrent_tasks = 2
warn_at = 0.80
soft_stop_at = 0.95
hard_kill_at = 1.00
sigterm_grace_s = 10
keep_branch_on_kill = true
revert_vault_on_kill = true

[modes]
enabled = false
default = "assist"
available = ["assist", "brainstorm", "focus", "away"]
brainstorm_suppresses = ["act", "propagate", "ask"]

[kill_switch]
phone = false
gpio_button = false
gpio_pin = 0
TOML
  echo "$cfg"
}

# --- Model discovery ---------------------------------------------------------
find_model() {
  local pattern="$1"
  # Look for a GGUF matching the pattern (case-insensitive) in the models dir
  local match
  match="$(find "$MODELS_DIR" -iname "*${pattern}*.gguf" 2>/dev/null | head -1)"
  if [[ -n "$match" ]]; then
    echo "$match"
    return 0
  fi
  # Fallback: any GGUF
  match="$(find "$MODELS_DIR" -name "*.gguf" 2>/dev/null | head -1)"
  if [[ -n "$match" ]]; then
    echo "$match"
    return 0
  fi
  return 1
}

# --- Start/stop ---------------------------------------------------------------
do_start() {
  header "FRIDAY dev launcher"

  # Check for models
  local daily_model embed_model rerank_model
  daily_model="$(find_model "qwen3-4b" || find_model "qwen" || true)"
  embed_model="$(find_model "bge-m3" || echo "$daily_model")"
  rerank_model="$(find_model "reranker" || echo "$daily_model")"

  if [[ -z "$daily_model" ]]; then
    err "No GGUF models found in $MODELS_DIR"
    echo ""
    info "Download models first:"
    echo "  hf download Qwen/Qwen3-4B-GGUF Qwen3-4B-Q4_K_M.gguf --local-dir $MODELS_DIR"
    echo "  hf download lmstudio-community/bge-m3-GGUF bge-m3-Q8_0.gguf --local-dir $MODELS_DIR"
    echo "  hf download lmstudio-community/bge-reranker-v2-m3-GGUF bge-reranker-v2-m3-Q8_0.gguf --local-dir $MODELS_DIR"
    return 1
  fi

  info "daily model: $daily_model"
  info "embed model: $embed_model"
  info "rerank model: $rerank_model"

  # Start llama-server instances
  # daily + fast share the same model on dev (one process, two ports would need two instances)
  # Actually for dev we run one server on 8080 and point both daily+fast at it
  if ! is_running llama-daily; then
    info "starting llama-server (daily+fast) on :8080..."
    start_proc llama-daily llama-server \
      --model "$daily_model" \
      --host 127.0.0.1 --port 8080 \
      --ctx-size 8192 --n-gpu-layers 999 --alias qwen3-4b
  fi

  if ! is_running llama-embed; then
    info "starting llama-server (embed) on :8082..."
    start_proc llama-embed llama-server \
      --model "$embed_model" \
      --host 127.0.0.1 --port 8082 \
      --embedding --pooling cls --ctx-size 8192 --n-gpu-layers 999 --alias bge-m3
  fi

  if ! is_running llama-rerank; then
    info "starting llama-server (rerank) on :8085..."
    start_proc llama-rerank llama-server \
      --model "$rerank_model" \
      --host 127.0.0.1 --port 8085 \
      --reranking --ctx-size 8192 --n-gpu-layers 999 --alias bge-reranker-v2-m3
  fi

  # Wait for llama-servers to be ready
  info "waiting for llama-servers..."
  for port in 8080 8082 8085; do
    for i in $(seq 1 30); do
      curl -sf "http://127.0.0.1:$port/health" >/dev/null 2>&1 && break
      sleep 1
    done
    curl -sf "http://127.0.0.1:$port/health" >/dev/null 2>&1 && ok "llama-server :$port ready" || warn "llama-server :$port not ready yet"
  done

  # Generate configs
  local litellm_cfg friday_toml
  litellm_cfg="$(generate_litellm_config)"
  friday_toml="$(generate_friday_toml)"
  info "litellm config: $litellm_cfg"
  info "friday.toml: $friday_toml"

  # Start LiteLLM (use the repo venv)
  if ! is_running litellm; then
    info "starting LiteLLM on :4000..."
    start_proc litellm "$REPO/.venv/bin/litellm" \
      --config "$litellm_cfg" \
      --host 127.0.0.1 --port 4000
  fi

  # Wait for LiteLLM
  for i in $(seq 1 15); do
    curl -sf "http://127.0.0.1:4000/health/readiness" >/dev/null 2>&1 && break
    sleep 1
  done
  curl -sf "http://127.0.0.1:4000/health/readiness" >/dev/null 2>&1 && ok "LiteLLM ready" || warn "LiteLLM not ready yet"

  # Start the launchpad (unified UI that embeds the wall + links everything)
  if ! is_running launchpad; then
    info "starting FRIDAY launchpad on :8090..."
    start_proc launchpad "$VENV_PYTHON" -m friday.launchpad --port 8090
  fi

  echo ""
  header "FRIDAY is up"
  info "launchpad: http://127.0.0.1:8090  (unified UI — everything connected)"
  info "wall:      http://127.0.0.1:8088  (agents, gates, scrutiny)"
  info "litellm:   http://127.0.0.1:4000/v1/models"
  info "ask:      cd $REPO && uv run python -m friday.cli ask 'hello'"
  info "stop:     bash dev.sh stop"
}

do_stop() {
  header "Stopping FRIDAY dev"
  stop_proc launchpad
  stop_proc litellm
  stop_proc llama-rerank
  stop_proc llama-embed
  stop_proc llama-daily
  ok "all stopped"
}

do_status() {
  header "FRIDAY dev status"
  for name in llama-daily llama-embed llama-rerank litellm launchpad; do
    if is_running "$name"; then
      ok "$name running (pid $(pid_of "$name"))"
    else
      warn "$name not running"
    fi
  done
  echo ""
  if is_running litellm; then
    info "LiteLLM models:"
    curl -s http://127.0.0.1:4000/v1/models -H "Authorization: Bearer sk-friday-dev-key-not-for-production" 2>/dev/null \
      | python3 -c "import sys,json; [print(f'  {m[\"id\"]}') for m in json.load(sys.stdin).get('data',[])]" 2>/dev/null || true
  fi
  if is_running wall; then
    info "Dashboard: http://127.0.0.1:8088"
  fi
}

# --- Interactive menu ---------------------------------------------------------
do_menu() {
  while true; do
    choice="$(gum choose \
      "Start FRIDAY" \
      "Stop FRIDAY" \
      "Status" \
      "Ask FRIDAY" \
      "Download models" \
      "Quit" 2>/dev/null)" || break

    case "$choice" in
      "Start FRIDAY") do_start ;;
      "Stop FRIDAY") do_stop ;;
      "Status") do_status ;;
      "Ask FRIDAY")
        q="$(gum input --placeholder "Ask FRIDAY..." 2>/dev/null)" || continue
        [[ -n "$q" ]] && cd "$REPO" && uv run python -m friday.cli ask "$q"
        ;;
      "Download models")
        header "Download models"
        info "Downloading to $MODELS_DIR"
        gum confirm "Download Qwen3-4B (chat, ~2.5GB)?" && \
          hf download Qwen/Qwen3-4B-GGUF Qwen3-4B-Q4_K_M.gguf --local-dir "$MODELS_DIR" &
        gum confirm "Download bge-m3 (embeddings, ~600MB)?" && \
          hf download lmstudio-community/bge-m3-GGUF bge-m3-Q8_0.gguf --local-dir "$MODELS_DIR" &
        gum confirm "Download bge-reranker-v2-m3 (reranking, ~600MB)?" && \
          hf download lmstudio-community/bge-reranker-v2-m3-GGUF bge-reranker-v2-m3-Q8_0.gguf --local-dir "$MODELS_DIR" &
        wait
        ok "Downloads complete"
        ls -lh "$MODELS_DIR"/*.gguf 2>/dev/null
        ;;
      "Quit") break ;;
    esac
    echo ""
    gum confirm "Continue?" || break
  done
}

# --- Main ---------------------------------------------------------------------
case "${1:-menu}" in
  start)  do_start ;;
  stop)   do_stop ;;
  status) do_status ;;
  wall)
    start_proc wall "$VENV_PYTHON" -m friday.wall --port 8088
    info "Dashboard at http://127.0.0.1:8088"
    ;;
  menu)   do_menu ;;
  *) echo "Usage: bash dev.sh [start|stop|status|wall|menu]"; exit 1 ;;
esac
