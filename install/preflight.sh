#!/usr/bin/env bash
# Preflight. Runs before every week and exits non-zero on any failure. It reads; it
# never changes anything.
#
# Also runnable by the supervisor as a health check (spec section 9, every 30s), which
# is why it is quiet-capable and fast.
#
#   bash install/preflight.sh
#   bash install/preflight.sh --quiet

set -uo pipefail   # deliberately not -e: every check runs, then it reports

ROOT=${ROOT:-/srv/friday}
REPO=${REPO:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}

# Floors come from the active profile, not from a constant. ADR-0025.
#
# Before profiles existed these were fixed at the target-box numbers and MIN_VRAM_MB became
# an override people set to silence the check - which is the same as not having one. Now the
# floor is a property of a named profile, and running the dev profile is a deliberate act
# recorded in /etc/friday/profile rather than an env var someone exported once.
PROFILE="${FRIDAY_PROFILE:-}"
[[ -z "$PROFILE" && -r /etc/friday/profile ]] && PROFILE="$(tr -d '[:space:]' < /etc/friday/profile)"
PROFILE="${PROFILE:-target}"

case "$PROFILE" in
  dev)    _DEF_VRAM=0     ; _DEF_DISK=40  ;;
  target) _DEF_VRAM=23000 ; _DEF_DISK=120 ;;
  *)      printf 'unknown profile %s (expected dev or target)\n' "$PROFILE" >&2; exit 1 ;;
esac
MIN_VRAM_MB=${MIN_VRAM_MB:-$_DEF_VRAM}
MIN_DISK_GB=${MIN_DISK_GB:-$_DEF_DISK}

QUIET=0
[[ "${1:-}" == "--quiet" ]] && QUIET=1

PASS=0; FAIL=0; WARN=0
RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; OFF=$'\033[0m'
[[ -t 1 ]] || { RED=""; GRN=""; YEL=""; OFF=""; }

pass() { PASS=$((PASS+1)); [[ $QUIET -eq 1 ]] || printf '  %sPASS%s  %s\n' "$GRN" "$OFF" "$*"; }
fail() { FAIL=$((FAIL+1));                printf '  %sFAIL%s  %s\n' "$RED" "$OFF" "$*"; }
warn() { WARN=$((WARN+1));                printf '  %sWARN%s  %s\n' "$YEL" "$OFF" "$*"; }
sect() { [[ $QUIET -eq 1 ]] || printf '\n%s\n' "$*"; }

printf 'FRIDAY preflight  %s  %s  profile=%s\n' "$(date -Is)" "$(hostname)" "$PROFILE"

# ---------------------------------------------------------------------------
sect "1. GPU and driver"
# On the dev profile a missing GPU is a warning: llama.cpp runs on CPU, slowly, and every
# layer except answer quality is still testable (ADR-0025). On target it is a failure.
_gpu_missing() { [[ "$PROFILE" == "dev" ]] && warn "$1" || fail "$1"; }
if ! command -v nvidia-smi >/dev/null 2>&1; then
  _gpu_missing "nvidia-smi not found (nvidia-utils)"
elif ! nvidia-smi -L >/dev/null 2>&1; then
  _gpu_missing "nvidia-smi present but cannot reach the driver (lsmod | grep nvidia)"
else
  pass "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader | head -n1), driver $(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -n1)"
  systemctl is-active --quiet nvidia-persistenced 2>/dev/null \
    && pass "nvidia-persistenced active" \
    || warn "nvidia-persistenced inactive; model load latency roughly doubles"
fi

sect "2. VRAM"
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
  total=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -n1)
  free=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits | head -n1)
  used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -n1)
  [[ "$total" -ge $MIN_VRAM_MB ]] \
    && pass "total VRAM ${total} MB (floor ${MIN_VRAM_MB} for profile ${PROFILE})" \
    || fail "total VRAM ${total} MB below ${MIN_VRAM_MB} MB for profile ${PROFILE}. Either drop to a smaller daily driver from the spec section 1 table, or run the dev profile: echo dev | sudo tee /etc/friday/profile"
  if pgrep -x llama-server >/dev/null 2>&1; then
    pass "VRAM ${used} MB in use by llama-server, ${free} MB free"
  elif [[ "$free" -lt $MIN_VRAM_MB ]]; then
    fail "${free} MB free and no llama-server running: nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv"
  else
    pass "free VRAM ${free} MB"
  fi
elif [[ "$PROFILE" == "dev" ]]; then
  warn "cannot measure VRAM; dev profile permits CPU-only inference"
else
  fail "cannot measure VRAM"
fi

sect "3. Disk"
if [[ -d "$ROOT" ]]; then
  avail=$(( $(df -Pk "$ROOT" | awk 'NR==2 {print $4}') / 1048576 ))
  [[ "$avail" -ge $MIN_DISK_GB ]] \
    && pass "${avail} GB free under $ROOT" \
    || fail "${avail} GB free under $ROOT; need ${MIN_DISK_GB} GB for weights, index and vault"
else
  fail "$ROOT does not exist. Run install/tree.sh."
fi

sect "4. Ports"
# A port held by the service that should own it is a pass. Preflight runs before every
# week, and by week 2 the week-1 services are meant to be up.
declare -A OWNER=(
  [4000]="litellm|python|uvicorn"   [8080]="llama-server"
  [8081]="llama-server"             [8082]="llama-server"
  [8083]="llama-server"             [8084]="llama-server"
  [8085]="llama-server"             [7424]="conduit"
  [5232]="radicale|python"          [6333]="qdrant|docker-proxy"
  [3000]="langfuse|docker-proxy|node"
)
if ! command -v ss >/dev/null 2>&1; then
  warn "ss not found (iproute2); skipping the port check"
else
  listening="$(ss -tlnpH 2>/dev/null || ss -tlnH 2>/dev/null)"
  for port in 3000 4000 5232 6333 7424 8080 8081 8082 8083 8084 8085; do
    line="$(printf '%s\n' "$listening" | awk -v p=":$port\$" '$4 ~ p')"
    if [[ -z "$line" ]]; then
      pass "port $port free"
    else
      proc="$(printf '%s' "$line" | grep -o '"[^"]*"' | head -n1 | tr -d '"')"
      if [[ -n "$proc" && "$proc" =~ ^(${OWNER[$port]})$ ]]; then
        pass "port $port held by $proc (expected)"
      elif [[ -z "$proc" ]]; then
        warn "port $port bound, owning process not visible (run as root to see it)"
      else
        fail "port $port held by '$proc', not the service that should own it"
      fi
    fi
  done

  # Spec section 9: no port forwarding. Nothing may listen on a routable address.
  routable="$(printf '%s\n' "$listening" | awk '$4 !~ /^(127\.|\[::1\]|\[::ffff:127\.)/ {print $4}')"
  if [[ -z "$routable" ]]; then
    pass "nothing listening on a routable address"
  else
    fail "listening off-loopback: $(printf '%s' "$routable" | tr '\n' ' ')"
  fi
fi

sect "5. Service accounts"
for u in friday fridaysup; do
  if id -u "$u" >/dev/null 2>&1; then
    shell="$(getent passwd "$u" | cut -d: -f7)"
    [[ "$shell" == */nologin || "$shell" == */false ]] \
      && pass "$u exists, no login shell" \
      || fail "$u has a login shell ($shell)"
  else
    fail "$u does not exist. Run install/01-users.sh."
  fi
done

sect "6. Filesystem-enforced core (spec section 9)"
CORE="$ROOT/agent/core"
if [[ ! -d "$CORE" ]]; then
  fail "$CORE does not exist"
else
  owner="$(stat -c '%U' "$CORE")"; mode="$(stat -c '%a' "$CORE")"
  [[ "$owner" == "fridaysup" ]] && pass "$CORE owned by fridaysup" \
                                || fail "$CORE owned by '$owner', expected fridaysup"
  [[ "$mode" == "755" ]] && pass "$CORE mode 0755" \
                         || fail "$CORE mode $mode, expected 755"
  if id -u friday >/dev/null 2>&1 && [[ $EUID -eq 0 ]]; then
    sudo -u friday test -w "$CORE" \
      && fail "the friday user CAN write $CORE. Spec section 9 is not in force." \
      || pass "the friday user cannot write $CORE"
  else
    warn "not root; skipped the live write test (owner and mode checked above)"
  fi
  for d in skills tools prompts; do
    p="$ROOT/agent/$d"
    [[ -d "$p" ]] || { fail "$p missing"; continue; }
    [[ "$(stat -c '%U' "$p")" == "friday" ]] \
      && pass "$p owned by friday (writable, as intended)" \
      || fail "$p owned by $(stat -c '%U' "$p"), expected friday"
  done
fi

sect "7. Memory tiers (spec section 7)"
[[ -f "$ROOT/vault/profile.md" ]] \
  && { grep -q 'Delete this stub text' "$ROOT/vault/profile.md" 2>/dev/null \
       && warn "vault/profile.md is still the stub. Write it by hand; it is tier one." \
       || pass "vault/profile.md written"; } \
  || fail "$ROOT/vault/profile.md missing (tier 1)"
for d in daily projects people ideas; do
  [[ -d "$ROOT/vault/$d" ]] && pass "vault/$d" || fail "vault/$d missing"
done
[[ -d "$ROOT/db" ]] && pass "db/ present (tiers 2 and 4)" || fail "$ROOT/db missing"

sect "8. Secrets (spec section 9)"
if ! command -v sops >/dev/null 2>&1 || ! command -v age >/dev/null 2>&1; then
  fail "sops and/or age not found"
else
  pass "sops $(sops --version 2>/dev/null | head -n1)"
  if [[ ! -f "$REPO/.sops.yaml" ]]; then
    fail "$REPO/.sops.yaml missing"
  elif grep -q 'age1REPLACE_WITH_YOUR_AGE_PUBLIC_KEY' "$REPO/.sops.yaml"; then
    fail ".sops.yaml still has the placeholder recipient"
  else
    pass ".sops.yaml has a real recipient"
  fi
  KEY="$ROOT/secrets/age.key"
  if [[ ! -f "$KEY" ]]; then
    fail "no age identity at $KEY"
  else
    [[ "$(stat -c '%a' "$KEY")" == "600" ]] && pass "$KEY mode 0600" \
                                            || fail "$KEY mode $(stat -c '%a' "$KEY"), expected 600"
    tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
    printf 'canary: preflight\n' > "$tmp/c.yaml"
    pub="$(grep -oP 'public key: \K\S+' "$KEY" 2>/dev/null || echo none)"
    if SOPS_AGE_KEY_FILE="$KEY" sops --encrypt --age "$pub" "$tmp/c.yaml" > "$tmp/c.enc" 2>/dev/null \
       && SOPS_AGE_KEY_FILE="$KEY" sops --decrypt "$tmp/c.enc" 2>/dev/null | grep -q preflight; then
      pass "sops round-trips with the local identity"
    else
      fail "sops round-trip failed: the identity at $KEY does not match .sops.yaml"
    fi
  fi
fi

sect "9. Toolchain"
for t in uv git docker jq sqlite3 nft ffmpeg; do
  command -v "$t" >/dev/null 2>&1 && pass "$t" || warn "$t not found"
done
[[ -x "$ROOT/.venv/bin/python" ]] \
  && pass "venv $("$ROOT/.venv/bin/python" --version 2>&1)" \
  || warn "no venv at $ROOT/.venv (expected before install/02-python-env.sh)"
command -v llama-server >/dev/null 2>&1 && pass "llama-server" || warn "llama-server not found (AUR llama.cpp-cuda)"

printf '\n%s\n' "----------------------------------------"
printf 'preflight: %d passed, %d warnings, %d failed  (profile %s)\n' "$PASS" "$WARN" "$FAIL" "$PROFILE"
[[ "$PROFILE" == "dev" ]] && printf '%sdev profile: the 20/25 eval gate is a TARGET gate. ADR-0025.%s\n' "$YEL" "$OFF"
if [[ $FAIL -gt 0 ]]; then
  printf '%sPREFLIGHT FAILED%s\n' "$RED" "$OFF"
  exit 1
fi
printf '%spreflight ok%s\n' "$GRN" "$OFF"
exit 0
