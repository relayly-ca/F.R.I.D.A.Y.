#!/usr/bin/env bash
# Terminal UI, on gum (charmbracelet/gum, MIT). Sourced, never executed.
#
# Every function here degrades to plain output when gum is absent, and that is not defensive
# programming for its own sake - the FIRST thing install.sh does is install gum, so this file
# is necessarily used before gum exists. A UI layer that requires its own dependency to
# report on installing that dependency is a bootstrap loop.
#
# It also matters on the target box at 3am: if a package upgrade breaks gum, the installer
# still runs and still says what it is doing.

# Sourced. No `set -e` - forcing shell options onto a caller is how a library breaks a
# script that had different intentions.

UI_HAS_GUM=0
command -v gum >/dev/null 2>&1 && UI_HAS_GUM=1

# 256-colour indices rather than hex, so this looks right in a plain tty over ssh as well as
# in a truecolour terminal.
UI_ACCENT=${UI_ACCENT:-212}   # pink   - headings, the brand colour
UI_OK=${UI_OK:-42}            # green  - done
UI_WARN=${UI_WARN:-214}       # orange - attention, not failure
UI_ERR=${UI_ERR:-203}         # red    - failure
UI_DIM=${UI_DIM:-244}         # grey   - secondary text

_plain() { printf '%s\n' "$*"; }

# --- Structure ---------------------------------------------------------------

ui_banner() {
  if [[ $UI_HAS_GUM -eq 1 ]]; then
    gum style --border double --border-foreground "$UI_ACCENT" \
      --align center --width 68 --margin "1 0" --padding "1 2" \
      "FRIDAY" "$1"
  else
    printf '\n========================================================\n'
    printf '  FRIDAY\n  %s\n' "$1"
    printf '========================================================\n\n'
  fi
}

ui_header() {
  if [[ $UI_HAS_GUM -eq 1 ]]; then
    gum style --foreground "$UI_ACCENT" --bold --margin "1 0 0 0" "$*"
    gum style --foreground "$UI_DIM" "$(printf '%.0s-' {1..64})"
  else
    printf '\n=== %s\n' "$*"
  fi
}

ui_rule() {
  [[ $UI_HAS_GUM -eq 1 ]] \
    && gum style --foreground "$UI_DIM" "$(printf '%.0s-' {1..64})" \
    || printf -- '----------------------------------------------------------------\n'
}

# --- Messages ----------------------------------------------------------------
# gum log gives level colouring for free and keeps a consistent shape.

ui_info() { [[ $UI_HAS_GUM -eq 1 ]] && gum log --level info  "$*" || _plain "  INFO  $*"; }
ui_ok()   { [[ $UI_HAS_GUM -eq 1 ]] && gum log --level debug "$*" || _plain "  OK    $*"; }
ui_warn() { [[ $UI_HAS_GUM -eq 1 ]] && gum log --level warn  "$*" || _plain "  WARN  $*"; }
ui_err()  { [[ $UI_HAS_GUM -eq 1 ]] && gum log --level error "$*" || _plain "  ERROR $*"; }

ui_note() {
  [[ $UI_HAS_GUM -eq 1 ]] \
    && gum style --foreground "$UI_DIM" --margin "0 0 0 2" "$*" \
    || printf '    %s\n' "$*"
}

ui_die() { ui_err "$*"; exit 1; }

# Longer explanatory text. Markdown through gum format, plain otherwise.
ui_doc() {
  if [[ $UI_HAS_GUM -eq 1 ]]; then
    printf '%s\n' "$*" | gum format
  else
    printf '%s\n' "$*"
  fi
}

# --- Status ------------------------------------------------------------------
# The dashboard's unit of display. Three states, and `warn` is load-bearing: a thing that is
# present but wrong is not the same as a thing that is absent, and collapsing them is how you
# spend an evening reinstalling something that was already there.

# ui_status <done|todo|warn> <label> [detail]
ui_status() {
  local state="$1" label="$2" detail="${3:-}"
  local mark colour
  case "$state" in
    done) mark="done" ; colour=$UI_OK   ;;
    todo) mark="todo" ; colour=$UI_DIM  ;;
    warn) mark="warn" ; colour=$UI_WARN ;;
    fail) mark="FAIL" ; colour=$UI_ERR  ;;
    *)    mark="?"    ; colour=$UI_DIM  ;;
  esac
  if [[ $UI_HAS_GUM -eq 1 ]]; then
    gum join --horizontal \
      "$(gum style --foreground "$colour" --width 8 "  $mark")" \
      "$(gum style --width 30 "$label")" \
      "$(gum style --foreground "$UI_DIM" "$detail")"
  else
    printf '  %-6s %-30s %s\n' "$mark" "$label" "$detail"
  fi
}

# --- Interaction -------------------------------------------------------------
# All three fall back to plain `read`, so the installer is still usable over a serial
# console or in a terminal gum cannot draw in.

# ui_confirm <prompt> ; returns 0 for yes
ui_confirm() {
  if [[ "${FRIDAY_YES:-0}" == "1" ]]; then
    ui_note "auto-yes: $1"
    return 0
  fi
  if [[ $UI_HAS_GUM -eq 1 ]]; then
    gum confirm "$1"
  else
    local a; read -rp "$1 [y/N] " a; [[ "$a" =~ ^[Yy] ]]
  fi
}

# ui_choose <header> <option>...
ui_choose() {
  local header="$1"; shift
  if [[ $UI_HAS_GUM -eq 1 ]]; then
    gum choose --header "$header" --height 12 "$@"
  else
    printf '%s\n' "$header" >&2
    local i=1; for o in "$@"; do printf '  %d) %s\n' "$i" "$o" >&2; ((i++)); done
    local n; read -rp "> " n
    printf '%s' "${!n:-}"
  fi
}

# ui_input <placeholder> [--password]
ui_input() {
  local ph="$1"; shift
  if [[ $UI_HAS_GUM -eq 1 ]]; then
    gum input --placeholder "$ph" "$@"
  else
    local v
    if [[ "${1:-}" == "--password" ]]; then read -rsp "$ph: " v; echo >&2; else read -rp "$ph: " v; fi
    printf '%s' "$v"
  fi
}

# --- Running work ------------------------------------------------------------

# ui_spin <title> -- <command...>
#
# For quiet, slow things: downloads, systemctl, docker pulls. NOT for pacman - hiding a
# package manager's output behind a spinner means a conflict prompt or a signature error
# scrolls past invisibly, and you debug it later from a journal instead of seeing it.
ui_spin() {
  local title="$1"; shift
  [[ "${1:-}" == "--" ]] && shift
  if [[ $UI_HAS_GUM -eq 1 ]]; then
    gum spin --spinner dot --title "$title" --show-error -- "$@"
  else
    printf '  ... %s\n' "$title"
    "$@"
  fi
}

# ui_run <label> <command...>
#
# For loud things. Prints a header, runs in the open, reports the outcome. The output stays
# on screen because that is where the useful error message is.
ui_run() {
  local label="$1"; shift
  ui_header "$label"
  if "$@"; then
    ui_ok "$label"
    return 0
  fi
  local rc=$?
  ui_err "$label failed (exit $rc)"
  return $rc
}

# --- Summary -----------------------------------------------------------------

ui_summary() {
  local title="$1"; shift
  if [[ $UI_HAS_GUM -eq 1 ]]; then
    gum style --border rounded --border-foreground "$UI_ACCENT" \
      --padding "1 2" --margin "1 0" --width 68 "$title" "" "$@"
  else
    printf '\n--- %s ---\n' "$title"
    printf '%s\n' "$@"
    printf -- '-----------------\n'
  fi
}
