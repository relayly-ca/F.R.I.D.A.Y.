#!/usr/bin/env bash
# FRIDAY installer. One command, from a bare Arch box to a running week 1.
#
#   bash install.sh
#
# It elevates itself, so do not prefix it with sudo - several steps (makepkg, uv) refuse to
# run as root and need to know who invoked them.
#
# What this is: a front end over install/*.sh. Every step it runs is a script you can run by
# hand, in the order docs/weeks/W1.md gives, and running them by hand is a supported path
# rather than a fallback. This exists so the common case is one command, not so the
# individual steps become unreachable.
#
# What it is NOT: a substitute for the phase guides. It gets you through week 1. Weeks 2
# through 8 are deliberately manual, because each one has a gate you have to look at.
#
#   FRIDAY_PROFILE=dev bash install.sh     choose the profile up front
#   FRIDAY_YES=1       bash install.sh     no prompts, for a re-run
#   FRIDAY_STEP=models bash install.sh     run one step and stop

set -uo pipefail   # deliberately not -e: a failed step is reported, not a silent exit

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT=${ROOT:-/srv/friday}

source "$REPO/install/ui.sh"

# --- Elevate ------------------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
  ui_banner "installer"
  ui_info "This needs root for packages, users and systemd. Re-running under sudo."
  exec sudo --preserve-env=FRIDAY_PROFILE,FRIDAY_YES,FRIDAY_STEP,ROOT bash "$0" "$@"
fi

[[ -n "${SUDO_USER:-}" ]] || ui_die "run this as your own user (it elevates itself), not as root directly. makepkg and uv refuse to run as root."

source "$REPO/install/lib.sh"

# --- gum, first ---------------------------------------------------------------
# The UI degrades without it, and the dashboard is most of the point, so install it before
# anything else and re-source so the rest of the run is styled.
if [[ $UI_HAS_GUM -eq 0 ]]; then
  echo "Installing gum for the installer UI..."
  pacman -Sy --needed --noconfirm gum >/dev/null 2>&1 || true
  source "$REPO/install/ui.sh"
fi

PROFILE="$(friday_profile)"
ui_banner "a fully local, always-on ambient AI"

source "$REPO/install/steps.sh"

# --- Main ---------------------------------------------------------------------
detect

if [[ -n "${FRIDAY_STEP:-}" ]]; then
  "step_${FRIDAY_STEP}" ; exit $?
fi

while true; do
  dashboard

  if [[ "${S[os]}" == "fail" ]]; then
    ui_err "${D[os]}"
    exit 1
  fi

  echo
  choice="$(ui_choose "What now?" \
    "Install everything that is not done" \
    "Run one step" \
    "Change profile (currently: $PROFILE)" \
    "Preflight (reads, changes nothing)" \
    "What still needs me" \
    "Make it mine (name, timezone)" \
    "Write vault/profile.md" \
    "What gets installed, and why" \
    "Quit")"

  case "$choice" in
    "Install everything"*)
      if ui_confirm "Install everything still outstanding, on profile '$PROFILE'?"; then
        run_all
        detect
        report_manual
      fi ;;
    "Run one step")
      s="$(ui_choose "Which step?" packages users tree secrets venv models units keys upstream)"
      [[ -n "$s" ]] && "step_${s}" ; detect ;;
    "Change profile"*) choose_profile ; detect ;;
    "Preflight"*)      bash "$REPO/install/preflight.sh" || true ;;
    "What still needs me") report_manual ;;
    "Make it mine"*)   step_personalise ; detect ;;
    "Write vault"*)    step_profile_md ; detect ;;
    "What gets installed"*)
      if [[ $UI_HAS_GUM -eq 1 ]]; then gum pager < "$REPO/docs/INSTALL.md"
      else "${PAGER:-less}" "$REPO/docs/INSTALL.md"; fi ;;
    "Quit"|"") ui_note "Nothing was left half-applied; re-run any time." ; exit 0 ;;
  esac
done
