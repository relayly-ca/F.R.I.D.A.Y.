#!/usr/bin/env bash
# Packages. Arch repositories, then the AUR.
#
# Everything is `--needed`, so re-running is a no-op and the script is the repair after a
# partial install. Nothing here is profile-dependent: the same tools are installed on the
# dev box and the target box, and only the WEIGHTS differ (install/03-models.sh).
#
#   sudo bash install/00-arch-packages.sh
#   sudo SKIP_AUR=1 bash install/00-arch-packages.sh    # repositories only

set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

need_root
banner_profile

# --- Repository packages -----------------------------------------------------
log "Repository packages"

# CUDA is installed even on the dev box. It is a few hundred MB and it means moving to the
# target machine, or dropping a card into this one, does not need a second install pass.
PKGS=(
  base-devel git cmake ninja pkgconf
  cuda cudnn nvidia-utils
  uv python python-yaml
  age sops
  jq sqlite ripgrep rsync
  docker docker-compose docker-buildx
  iproute2 nftables wireguard-tools
  ffmpeg sox alsa-utils
  radicale python-passlib python-bcrypt
  isync notmuch python-notmuch
  nodejs npm
  polkit
)
pacman -Syu --needed --noconfirm "${PKGS[@]}"

# --- AUR ---------------------------------------------------------------------
if [[ "${SKIP_AUR:-0}" == "1" ]]; then
  warn "SKIP_AUR=1, skipping AUR packages. llama.cpp will be missing."
else
  log "paru"
  if ! command -v paru >/dev/null 2>&1; then
    # makepkg refuses to run as root, so this drops to the invoking user.
    build_user="${SUDO_USER:-}"
    [[ -n "$build_user" ]] || die "cannot build paru as root and SUDO_USER is unset. Install paru by hand, or re-run with sudo from your own account."
    tmp="$(sudo -u "$build_user" mktemp -d)"
    sudo -u "$build_user" git clone --depth 1 https://aur.archlinux.org/paru-bin.git "$tmp/paru-bin"
    ( cd "$tmp/paru-bin" && sudo -u "$build_user" makepkg -si --noconfirm )
    rm -rf "$tmp"
  else
    info "paru present"
  fi

  log "llama.cpp"
  # This package has moved between the repositories and the AUR. Prefer the repositories.
  if pacman -Si llama.cpp-cuda >/dev/null 2>&1; then
    info "found llama.cpp-cuda in the repositories"
    pacman -S --needed --noconfirm llama.cpp-cuda
  elif command -v llama-server >/dev/null 2>&1; then
    info "llama-server already present, leaving it alone"
  else
    build_user="${SUDO_USER:-}"
    [[ -n "$build_user" ]] || die "need SUDO_USER to build from the AUR"
    sudo -u "$build_user" paru -S --needed --noconfirm llama.cpp-cuda
  fi
fi

# --- Docker ------------------------------------------------------------------
log "Docker"
systemctl enable --now docker.service
if [[ -n "${SUDO_USER:-}" ]]; then
  usermod -aG docker "$SUDO_USER"
  warn "added $SUDO_USER to the docker group. Log out and back in for it to take effect."
  warn "Membership in 'docker' is root-equivalent on this host. docs/weeks/W5.md weighs this."
fi

# --- Verify ------------------------------------------------------------------
log "Verification"
printf '%-16s %s\n' "uv"           "$(uv --version 2>/dev/null || echo MISSING)"
printf '%-16s %s\n' "sops"         "$(sops --version 2>/dev/null | head -n1 || echo MISSING)"
printf '%-16s %s\n' "llama-server" "$(command -v llama-server >/dev/null 2>&1 && llama-server --version 2>&1 | head -n1 || echo MISSING)"
printf '%-16s %s\n' "docker"       "$(docker --version 2>/dev/null || echo MISSING)"

if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
  printf '%-16s %s\n' "gpu" "$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader | head -n1)"
else
  # Not fatal. The dev profile permits CPU-only, and preflight decides whether that is
  # acceptable for the active profile rather than this script guessing.
  warn "no usable NVIDIA GPU detected. Fine on the dev profile; fatal on target."
fi

cat <<'EOF'

Next: sudo bash install/01-users.sh
      sudo bash install/tree.sh
      sudo bash install/02-python-env.sh
EOF
