#!/usr/bin/env bash
# FRIDAY. One command. Smart install + launch, like hermes setup.
#
#   bash friday.sh                first run: interactive wizard, then launch
#   bash friday.sh start          skip wizard, just launch
#   bash friday.sh stop           stop everything
#   bash friday.sh status         show what's running
#   bash friday.sh reset          wipe config + state, start from zero
#   bash friday.sh setup          run wizard only (no launch)
#   bash friday.sh setup model    run just the model section
#
# Everything local. Zero credits. Uses what's already on the box.

set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
PY="$REPO/.venv/bin/python"
DATA="${FRIDAY_DEV_DIR:-$HOME/.local/share/friday-dev}"
MODELS="$DATA/models"
PIDS="$DATA/pids"
LOGS="$DATA/logs"
CFG="$DATA/config"
SETUP_FLAG="$DATA/.setup-complete"

mkdir -p "$MODELS" "$PIDS" "$LOGS" "$DATA/db" "$DATA/vault"

# --- Colors -------------------------------------------------------------------
if [[ -t 1 ]]; then
  C0='\033[0m'; CB='\033[1m'; CC='\033[36m'; CG='\033[32m'; CY='\033[33m'; CR='\033[31m'; CD='\033[90m'
else
  C0=''; CB=''; CC=''; CG=''; CY=''; CR=''; CD=''
fi

header() { echo -e "\n${CB}${CC}◆ $1${C0}"; }
info()   { echo -e "  $1"; }
warn()   { echo -e "  ${CY}⚠ $1${C0}"; }
err()    { echo -e "  ${CR}✗ $1${C0}"; }
ok()     { echo -e "  ${CG}✓ $1${C0}"; }
dim()    { echo -e "  ${CD}$1${C0}"; }

# --- Prompt helpers -----------------------------------------------------------
prompt() {
  local question="$1" default="${2:-}" val
  if [[ -n "$default" ]]; then
    echo -ne "  ${CY}$question [$default]: ${C0}" >&2
  else
    echo -ne "  ${CY}$question: ${C0}" >&2
  fi
  read -r val
  echo "${val:-$default}"
}

prompt_yn() {
  local question="$1" default="${2:-y}" val
  if [[ "$default" == "y" ]]; then
    echo -ne "  ${CY}$question [Y/n]: ${C0}" >&2
  else
    echo -ne "  ${CY}$question [y/N]: ${C0}" >&2
  fi
  read -r val
  val="${val:-$default}"
  [[ "$val" =~ ^[Yy] ]]
}

prompt_choice() {
  local question="$1"; shift
  local choices=("$@")
  echo -e "  ${CY}$question${C0}"
  local i=1
  for c in "${choices[@]}"; do
    echo -e "    ${CD}$i)${C0} $c"
    i=$((i+1))
  done
  echo -ne "  ${CY}Choice [1]: ${C0}" >&2
  local n
  read -r n
  n="${n:-1}"
  echo "${choices[$((n-1))]}"
}

gum_choose() {
  if command -v gum &>/dev/null; then
    gum choose "$@" 2>/dev/null
  else
    prompt_choice "Choose:" "$@"
  fi
}

gum_confirm() {
  if command -v gum &>/dev/null; then
    gum confirm "$1" 2>/dev/null
  else
    prompt_yn "$1"
  fi
}

gum_input() {
  if command -v gum &>/dev/null; then
    gum input --placeholder "$1" 2>/dev/null || prompt "$1" "$2"
  else
    prompt "$1" "$2"
  fi
}

is_running() { [[ -f "$PIDS/$1" ]] && kill -0 "$(cat "$PIDS/$1" 2>/dev/null)" 2>/dev/null; }

# --- System detection ---------------------------------------------------------
detect_system() {
  header "System Detection"

  local os kernel gpu vram ram disk
  os="$(uname -s)"
  kernel="$(uname -r)"

  if [[ "$os" == "Linux" ]] && [[ -f /etc/arch-release ]]; then
    ok "OS: Arch Linux (kernel $kernel)"
  elif [[ "$os" == "Linux" ]]; then
    ok "OS: Linux (kernel $kernel)"
  else
    warn "OS: $os — FRIDAY targets Arch Linux but will try anyway"
  fi

  # GPU
  if command -v nvidia-smi &>/dev/null && nvidia-smi -L &>/dev/null; then
    gpu="$(nvidia-smi --query-gpu=name --format=csv,noheader | head -1)"
    vram="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1)"
    ok "GPU: $gpu ($vram MB VRAM)"

    # Pick profile based on VRAM
    if [[ "$vram" -ge 24000 ]]; then
      PROFILE="target"
      dim "  Profile: target (24GB+ — can run Qwen 27B)"
    elif [[ "$vram" -ge 8000 ]]; then
      PROFILE="dev"
      dim "  Profile: dev (8-24GB — Qwen 4B, full retrieval pipeline)"
    else
      PROFILE="dev"
      warn "  VRAM under 8GB — will run on GPU if possible, CPU fallback"
    fi
  else
    gpu="none"
    vram=0
    PROFILE="dev"
    warn "GPU: none — CPU-only mode (slow but works)"
  fi

  # RAM
  ram="$(free -h | awk '/^Mem:/ {print $2}')"
  ok "RAM: $ram"

  # Disk
  disk="$(df -h . | awk 'NR==2 {print $4}')"
  ok "Disk: $disk free"

  echo "$PROFILE" >"$DATA/profile"
}

# --- Tool detection -----------------------------------------------------------
detect_tools() {
  header "Installed Tools"

  MISSING=""
  INSTALLED=""

  check_tool() {
    local bin="$1" name="$2" install_hint="$3"
    if command -v "$bin" &>/dev/null; then
      ok "$name"
      INSTALLED="$INSTALLED $bin"
    else
      warn "$name — $install_hint"
      MISSING="$MISSING $bin"
    fi
  }

  check_tool llama-server "llama.cpp (inference)"   "pacman -S llama-cpp"
  check_tool uv          "uv (Python manager)"       "pacman -S uv"
  check_tool docker      "Docker (Qdrant, OpenHands)" "pacman -S docker"
  check_tool hf          "HuggingFace CLI"            "uv tool install huggingface-hub"
  check_tool curl        "curl"                       "pacman -S curl"
  check_tool git         "git"                        "pacman -S git"
  check_tool gum         "gum (UI)"                   "paru -S gum"

  # Python venv
  if [[ -f "$PY" ]]; then
    ok "Python venv (all deps installed)"
    INSTALLED="$INSTALLED venv"
  else
    err "Python venv missing"
    MISSING="$MISSING venv"
  fi
}

# --- Model selection ----------------------------------------------------------
MODELS_TABLE=(
  # "size_mb repo file"
  "2600 Qwen/Qwen3-4B-GGUF Qwen3-4B-Q4_K_M.gguf"
  "1600 Qwen/Qwen3-1.7B-GGUF Qwen3-1.7B-Q4_K_M.gguf"
  "600 gpustack/bge-m3-GGUF bge-m3-Q8_0.gguf"
  "600 gpustack/bge-reranker-v2-m3-GGUF bge-reranker-v2-m3-Q8_0.gguf"
)

pick_models() {
  header "Model Selection"

  local vram
  vram="$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 || echo 0)"

  # Recommend based on VRAM
  if [[ "$vram" -ge 24000 ]]; then
    ok "Recommended: Qwen3-4B + bge-m3 + bge-reranker-v2-m3 (fits 24GB easily)"
    DAILY_REPO="Qwen/Qwen3-4B-GGUF"
    DAILY_FILE="Qwen3-4B-Q4_K_M.gguf"
  elif [[ "$vram" -ge 8000 ]]; then
    ok "Recommended: Qwen3-4B + bge-m3 + bge-reranker-v2-m3 (fits 8GB)"
    DAILY_REPO="Qwen/Qwen3-4B-GGUF"
    DAILY_FILE="Qwen3-4B-Q4_K_M.gguf"
  elif [[ "$vram" -ge 4000 ]]; then
    warn "VRAM is tight — recommending Qwen3-1.7B (smaller, faster, less capable)"
    DAILY_REPO="Qwen/Qwen3-1.7B-GGUF"
    DAILY_FILE="Qwen3-1.7B-Q4_K_M.gguf"
  else
    warn "No GPU or under 4GB — recommending Qwen3-1.7B (will run on CPU)"
    DAILY_REPO="Qwen/Qwen3-1.7B-GGUF"
    DAILY_FILE="Qwen3-1.7B-Q4_K_M.gguf"
  fi

  # Always use bge-m3 and bge-reranker — they're small and identical across profiles
  EMBED_REPO="gpustack/bge-m3-GGUF"
  EMBED_FILE="bge-m3-Q8_0.gguf"
  RERANK_REPO="gpustack/bge-reranker-v2-m3-GGUF"
  RERANK_FILE="bge-reranker-v2-m3-Q8_0.gguf"

  local choice
  choice=$(gum_choose "Use recommended models" "Choose different chat model" "Skip downloads (I have models)")
  case "$choice" in
    "Use recommended models")
      ok "Using recommended models"
      ;;
    "Choose different chat model")
      local chat_model
      chat_model=$(gum_choose "Qwen3-4B (2.6GB, best quality)" "Qwen3-1.7B (1.6GB, faster)")
      case "$chat_model" in
        *4B*) DAILY_REPO="Qwen/Qwen3-4B-GGUF"; DAILY_FILE="Qwen3-4B-Q4_K_M.gguf" ;;
        *1.7B*) DAILY_REPO="Qwen/Qwen3-1.7B-GGUF"; DAILY_FILE="Qwen3-1.7B-Q4_K_M.gguf" ;;
      esac
      ;;
    "Skip downloads (I have models)")
      ok "Skipping downloads — place GGUF files in $MODELS/"
      return
      ;;
  esac

  # Save model config
  cat >"$DATA/models.conf" <<MCONF
DAILY_REPO=$DAILY_REPO
DAILY_FILE=$DAILY_FILE
EMBED_REPO=$EMBED_REPO
EMBED_FILE=$EMBED_FILE
RERANK_REPO=$RERANK_REPO
RERANK_FILE=$RERANK_FILE
MCONF
  ok "Model config saved"
}

check_models() {
  local have_all=1
  if ! find "$MODELS" -iname "*qwen*.gguf" -quit 2>/dev/null | grep -q .; then
    have_all=0
  fi
  if ! find "$MODELS" -iname "*bge-m3*.gguf" -quit 2>/dev/null | grep -q .; then
    have_all=0
  fi
  if ! find "$MODELS" -iname "*reranker*.gguf" -quit 2>/dev/null | grep -q .; then
    have_all=0
  fi
  return $(( 1 - have_all ))
}

download_models() {
  [[ -f "$DATA/models.conf" ]] || return 0
  source "$DATA/models.conf"

  if ! find "$MODELS" -iname "*$DAILY_FILE*" -quit 2>/dev/null | grep -q .; then
    local size_mb
    case "$DAILY_FILE" in
      *4B*) size_mb="2600" ;;
      *1.7B*) size_mb="1600" ;;
      *) size_mb="??" ;;
    esac
    info "  Downloading $DAILY_FILE (${size_mb}MB)..."
    hf download "$DAILY_REPO" "$DAILY_FILE" --local-dir "$MODELS" 2>&1 | tail -1
  fi
  if ! find "$MODELS" -iname "*$EMBED_FILE*" -quit 2>/dev/null | grep -q .; then
    info "  Downloading $EMBED_FILE (600MB)..."
    hf download "$EMBED_REPO" "$EMBED_FILE" --local-dir "$MODELS" 2>&1 | tail -1
  fi
  if ! find "$MODELS" -iname "*$RERANK_FILE*" -quit 2>/dev/null | grep -q .; then
    info "  Downloading $RERANK_FILE (600MB)..."
    hf download "$RERANK_REPO" "$RERANK_FILE" --local-dir "$MODELS" 2>&1 | tail -1
  fi
  ok "Models ready."
}

# --- Component configuration --------------------------------------------------
configure_components() {
  header "FRIDAY Components"
  info "Everything is local. Nothing leaves your machine."
  echo ""

  ENABLE_DAILY=1; ENABLE_EMBED=1; ENABLE_RERANK=1
  ENABLE_LITELLM=1; ENABLE_QDRANT=1; ENABLE_LAUNCHPAD=1; ENABLE_WALL=0

  local choice
  choice=$(gum_choose "Enable all components (recommended)" "Choose what to enable" "Use defaults and skip")

  case "$choice" in
    "Enable all components (recommended)")
      ok "All components enabled"
      ;;
    "Choose what to enable")
      gum_confirm "Inference — chat model (llama.cpp on GPU)"      && ENABLE_DAILY=1   || ENABLE_DAILY=0
      gum_confirm "Embeddings — bge-m3 for vector search"           && ENABLE_EMBED=1    || ENABLE_EMBED=0
      gum_confirm "Reranking — bge-reranker-v2-m3"                 && ENABLE_RERANK=1   || ENABLE_RERANK=0
      gum_confirm "LiteLLM proxy — model routing, aliases"         && ENABLE_LITELLM=1  || ENABLE_LITELLM=0
      gum_confirm "Qdrant — vector database (Docker)"              && ENABLE_QDRANT=1   || ENABLE_QDRANT=0
      gum_confirm "Launchpad UI — unified dashboard at :8090"      && ENABLE_LAUNCHPAD=1 || ENABLE_LAUNCHPAD=0
      gum_confirm "Wall — agent state + scrutiny at :8088"         && ENABLE_WALL=1      || ENABLE_WALL=0
      ;;
    "Use defaults and skip")
      ok "Using defaults"
      ;;
  esac
}

# --- User profile -------------------------------------------------------------
configure_profile() {
  header "Your Profile"
  info "vault/profile.md is the seed everything grows from."
  info "FRIDAY uses this to know who you are.\n"

  local name timezone
  name=$(gum_input "Your name (as FRIDAY should think of you)" "$(whoami)")
  timezone=$(gum_input "Your timezone" "$(timedatectl show --property=Timezone --value 2>/dev/null || echo 'UTC')")

  # Write profile.md
  cat >"$DATA/vault/profile.md" <<PROFILE
# $name

You are $name's ambient AI. You run locally on their hardware. You are always on,
always private, and you send nothing to anyone else's server.

## About $name
- Timezone: $timezone
- (Replace this with real details about yourself — your work, your people,
  your projects, how you like to be spoken to, and what you never want done
  without asking. About 1500 tokens. Delete this stub text.)
PROFILE

  ok "Profile written to $DATA/vault/profile.md"
  dim "  Edit it by hand later — it's the most important file in the system."
}

# --- Config generation --------------------------------------------------------
generate_config() {
  cat >"$CFG" <<CFG
ENABLE_DAILY=$ENABLE_DAILY
ENABLE_EMBED=$ENABLE_EMBED
ENABLE_RERANK=$ENABLE_RERANK
ENABLE_LITELLM=$ENABLE_LITELLM
ENABLE_QDRANT=$ENABLE_QDRANT
ENABLE_LAUNCHPAD=$ENABLE_LAUNCHPAD
ENABLE_WALL=$ENABLE_WALL
CFG
}

generate_litellm() {
  local daily_alias="qwen3-4b"
  find "$MODELS" -iname "*1.7b*.gguf" -quit 2>/dev/null | grep -q . && daily_alias="qwen3-1.7b"

  cat >"$DATA/litellm.yaml" <<YAML
model_list:
  - model_name: daily
    litellm_params: {model: openai/$daily_alias, api_base: http://127.0.0.1:8080/v1, api_key: dummy, timeout: 600}
  - model_name: fast
    litellm_params: {model: openai/$daily_alias, api_base: http://127.0.0.1:8080/v1, api_key: dummy, timeout: 60}
  - model_name: embed
    litellm_params: {model: openai/bge-m3, api_base: http://127.0.0.1:8082/v1, api_key: dummy, timeout: 120}
  - model_name: rerank
    litellm_params: {model: openai/bge-reranker-v2-m3, api_base: http://127.0.0.1:8085/v1, api_key: dummy, timeout: 120}
router_settings:
  fallbacks: [{daily: [fast]}]
  allowed_fails: 2
  cooldown_time: 30
litellm_settings: {num_retries: 2, request_timeout: 600, drop_params: true}
general_settings:
  telemetry: false
YAML
}

# --- The wizard ---------------------------------------------------------------
do_setup() {
  header "FRIDAY — Setup Wizard"
  info "A fully local, always-on ambient AI."
  info "Everything runs on your hardware. Nothing leaves your machine."

  detect_system
  detect_tools

  # Install missing venv
  if [[ "$MISSING" == *"venv"* ]]; then
    header "Installing Python dependencies..."
    cd "$REPO" && uv sync --extra dev 2>&1 | tail -3
  fi

  pick_models
  configure_components
  configure_profile

  generate_config
  generate_litellm

  # Download models if needed
  if ! check_models; then
    if gum_confirm "Download models now? (~3.6GB total)"; then
      download_models
    else
      warn "Models not downloaded — run 'bash friday.sh setup model' later"
    fi
  else
    ok "All models present."
  fi

  touch "$SETUP_FLAG"
  ok "Setup complete. FRIDAY is ready."
}

# --- Start --------------------------------------------------------------------
do_start() {
  [[ -f "$CFG" ]] && source "$CFG"
  ENABLE_DAILY=${ENABLE_DAILY:-1}
  ENABLE_EMBED=${ENABLE_EMBED:-1}
  ENABLE_RERANK=${ENABLE_RERANK:-1}
  ENABLE_LITELLM=${ENABLE_LITELLM:-1}
  ENABLE_QDRANT=${ENABLE_QDRANT:-1}
  ENABLE_LAUNCHPAD=${ENABLE_LAUNCHPAD:-1}
  ENABLE_WALL=${ENABLE_WALL:-0}

  # Kill anything still running
  for f in "$PIDS"/*; do [[ -f "$f" ]] && kill "$(cat "$f")" 2>/dev/null || true; done
  rm -f "$PIDS"/*

  # Ensure models
  if ! check_models; then
    download_models
  fi

  local DAILY EMBED RERANK
  DAILY=$(find "$MODELS" -iname "*qwen*.gguf" | head -1)
  EMBED=$(find "$MODELS" -iname "*bge-m3*.gguf" | head -1)
  RERANK=$(find "$MODELS" -iname "*reranker*.gguf" | head -1)

  if [[ -z "$DAILY" ]]; then
    err "No chat model found in $MODELS"
    info "Run: bash friday.sh setup model"
    return 1
  fi

  # Inference
  if [[ "$ENABLE_DAILY" == "1" ]]; then
    info "Starting llama-server (chat) on :8080..."
    llama-server --model "$DAILY" --host 127.0.0.1 --port 8080 --ctx-size 8192 --n-gpu-layers 999 --alias qwen3-4b >"$LOGS/daily.log" 2>&1 & echo $! >"$PIDS/daily"
  fi
  if [[ "$ENABLE_EMBED" == "1" && -n "$EMBED" ]]; then
    info "Starting llama-server (embed) on :8082..."
    llama-server --model "$EMBED" --host 127.0.0.1 --port 8082 --embedding --pooling cls --ctx-size 8192 --n-gpu-layers 999 --alias bge-m3 >"$LOGS/embed.log" 2>&1 & echo $! >"$PIDS/embed"
  fi
  if [[ "$ENABLE_RERANK" == "1" && -n "$RERANK" ]]; then
    info "Starting llama-server (rerank) on :8085..."
    llama-server --model "$RERANK" --host 127.0.0.1 --port 8085 --reranking --ctx-size 8192 --n-gpu-layers 999 --alias bge-reranker-v2-m3 >"$LOGS/rerank.log" 2>&1 & echo $! >"$PIDS/rerank"
  fi

  # Wait for inference
  for p in 8080 8082 8085; do
    for i in $(seq 1 30); do curl -sf "http://127.0.0.1:$p/health" >/dev/null 2>&1 && break; sleep 1; done
  done

  # LiteLLM
  if [[ "$ENABLE_LITELLM" == "1" ]]; then
    generate_litellm
    info "Starting LiteLLM on :4000..."
    "$REPO/.venv/bin/litellm" --config "$DATA/litellm.yaml" --host 127.0.0.1 --port 4000 >"$LOGS/litellm.log" 2>&1 & echo $! >"$PIDS/litellm"
    for i in $(seq 1 15); do curl -sf http://127.0.0.1:4000/health/readiness >/dev/null 2>&1 && break; sleep 1; done
  fi

  # Qdrant
  if [[ "$ENABLE_QDRANT" == "1" ]]; then
    if ! curl -sf http://127.0.0.1:6333/ >/dev/null 2>&1; then
      info "Starting Qdrant on :6333..."
      docker run -d --name friday-qdrant --restart always -p 127.0.0.1:6333:6333 -v "$DATA/qdrant:/qdrant/storage" qdrant/qdrant >/dev/null 2>&1 || true
    fi
  fi

  # Wall
  if [[ "$ENABLE_WALL" == "1" ]]; then
    info "Starting wall on :8088..."
    "$PY" -m friday.wall --port 8088 >"$LOGS/wall.log" 2>&1 & echo $! >"$PIDS/wall"
  fi

  # Launchpad
  if [[ "$ENABLE_LAUNCHPAD" == "1" ]]; then
    info "Starting launchpad on :8090..."
    "$PY" -m friday.launchpad --port 8090 >"$LOGS/launchpad.log" 2>&1 & echo $! >"$PIDS/launchpad"
  fi

  echo ""
  header "FRIDAY is up"
  [[ "$ENABLE_LAUNCHPAD" == "1" ]] && ok "UI:      http://127.0.0.1:8090"
  [[ "$ENABLE_WALL" == "1" ]]      && ok "Wall:    http://127.0.0.1:8088"
  [[ "$ENABLE_LITELLM" == "1" ]]   && ok "LiteLLM: http://127.0.0.1:4000/v1/models"
  ok "Ask:     cd $REPO && uv run python -m friday.cli ask 'hello'"
  ok "Stop:    bash friday.sh stop"
  ok "Status:  bash friday.sh status"
}

# --- Stop ---------------------------------------------------------------------
do_stop() {
  header "Stopping FRIDAY"
  for f in "$PIDS"/*; do [[ -f "$f" ]] && kill "$(cat "$f")" 2>/dev/null || true; done
  rm -f "$PIDS"/*
  ok "All stopped."
}

# --- Status -------------------------------------------------------------------
do_status() {
  header "FRIDAY Status"
  for name in daily embed rerank litellm wall launchpad; do
    if is_running "$name"; then
      local port=""
      case $name in
        daily) port=":8080";; embed) port=":8082";; rerank) port=":8085";;
        litellm) port=":4000";; wall) port=":8088";; launchpad) port=":8090";;
      esac
      ok "$name running (pid $(cat "$PIDS/$name")) $port"
    else
      dim "$name not running"
    fi
  done
  curl -sf http://127.0.0.1:6333/ >/dev/null 2>&1 && ok "qdrant running :6333" || dim "qdrant not running"
  echo ""
  dim "Setup: $([ -f "$SETUP_FLAG" ] && echo 'complete' || echo 'not run yet')"
  dim "Config: $CFG"
  dim "Models: $MODELS"
  dim "Profile: $DATA/vault/profile.md"
}

# --- Reset --------------------------------------------------------------------
do_reset() {
  header "Reset FRIDAY"
  if ! gum_confirm "This wipes all config, models, and state. Continue?"; then
    info "Reset cancelled."
    return 0
  fi
  do_stop 2>/dev/null || true
  rm -rf "$DATA"
  ok "Everything wiped. Run 'bash friday.sh' to start fresh."
}

# --- Main ---------------------------------------------------------------------
case "${1:-auto}" in
  setup)
    if [[ "${2:-}" == "model" ]]; then
      detect_system
      pick_models
      if gum_confirm "Download now?"; then download_models; fi
    elif [[ "${2:-}" == "components" ]]; then
      configure_components
      generate_config
    elif [[ "${2:-}" == "profile" ]]; then
      configure_profile
    else
      do_setup
    fi
    ;;
  start)
    [[ -f "$SETUP_FLAG" ]] || do_setup
    do_start
    ;;
  stop)   do_stop ;;
  status) do_status ;;
  reset)  do_reset ;;
  auto)
    if [[ ! -f "$SETUP_FLAG" ]]; then
      do_setup
      if gum_confirm "Launch FRIDAY now?"; then
        do_start
      fi
    else
      do_start
    fi
    ;;
  *)
    echo "FRIDAY — local ambient AI"
    echo ""
    echo "Usage: bash friday.sh [setup|start|stop|status|reset]"
    echo ""
    echo "  (no args)  first run: wizard + launch. after that: just launch"
    echo "  setup      run setup wizard"
    echo "  setup model     just pick + download models"
    echo "  setup components toggle which services to run"
    echo "  setup profile   edit your profile.md"
    echo "  start      skip wizard, just launch"
    echo "  stop       stop everything"
    echo "  status     show what's running"
    echo "  reset      wipe everything, start from zero"
    ;;
esac
