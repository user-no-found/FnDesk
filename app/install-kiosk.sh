#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run as root." >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -z "${KIOSK_USER:-}" ]]; then
  if [[ -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
    KIOSK_USER="${SUDO_USER}"
  else
    echo "KIOSK_USER is not set. Run with sudo from the kiosk user, or set KIOSK_USER=<user>." >&2
    exit 1
  fi
fi

KIOSK_OUTPUT="${KIOSK_OUTPUT:-}"
FNDESK_DRM_DEVICE="${FNDESK_DRM_DEVICE:-}"
FNDESK_DRM_LEGACY="${FNDESK_DRM_LEGACY:-1}"
FNDESK_DRM_NO_MODIFIERS="${FNDESK_DRM_NO_MODIFIERS:-1}"
FNDESK_USE_SYSTEM_LIBDRM="${FNDESK_USE_SYSTEM_LIBDRM:-1}"
FNDESK_SOFTWARE_RENDERER="${FNDESK_SOFTWARE_RENDERER:-1}"
FNDESK_INSTALLED_PACKAGES=()
FNDESK_CREATED_EDGE_KEY=0
FNDESK_CREATED_EDGE_REPO=0

systemctl_bounded() {
  timeout --signal=KILL 5s systemctl "$@"
}

BOOTSTRAP_PACKAGES=(
  ca-certificates
  curl
  gnupg
  locales
)

LOCAL_PACKAGES=(
  cage
  seatd
  wayland-utils
  xwayland
  fonts-noto-cjk
  adwaita-icon-theme
  fcitx5
  fcitx5-chinese-addons
  fcitx5-frontend-gtk3
  fcitx5-frontend-gtk4
  fcitx5-frontend-qt5
  dbus
  dbus-user-session
)

package_installed() {
  dpkg-query -W -f='${db:Status-Abbrev}' "$1" 2>/dev/null | grep -q '^ii '
}

warn_dpkg_state_for_apt() {
  local broken
  broken="$(dpkg-query -W -f='${Package}\t${db:Status-Abbrev}\n' 2>/dev/null | awk '$2 ~ /^i[UFHWT]/ { print $1 " (" $2 ")" }')"
  if [[ -n "${broken}" ]]; then
    echo "dpkg has half-installed packages; apt may return a non-zero status after installing FnDesk dependencies:" >&2
    printf '%s\n' "${broken}" >&2
  fi
}

install_bundled_edge() {
  local edge_deb

  if package_installed microsoft-edge-stable; then
    echo "[2/8] microsoft-edge-stable is already installed; keeping existing installation."
    return 0
  fi

  if [[ ! -d "${SCRIPT_DIR}/debs" ]]; then
    return 1
  fi

  edge_deb="$(find "${SCRIPT_DIR}/debs" -maxdepth 1 -type f -name 'microsoft-edge-stable_*_amd64.deb' 2>/dev/null | sort -V | tail -n 1)"
  if [[ -z "${edge_deb}" ]]; then
    return 1
  fi

  echo "[2/8] Installing bundled Microsoft Edge: ${edge_deb}"
  warn_dpkg_state_for_apt
  apt-get install -y "${edge_deb}" || true
  if ! package_installed microsoft-edge-stable; then
    echo "[2/8] bundled Microsoft Edge install did not finish." >&2
    return 1
  fi
  FNDESK_INSTALLED_PACKAGES+=("microsoft-edge-stable")
}

setup_edge_repository() {
  install -d -m 0755 /etc/apt/keyrings

  if [[ ! -f /etc/apt/keyrings/microsoft.gpg ]]; then
    local key_tmp
    key_tmp="$(mktemp)"
    if ! curl -fsSL https://packages.microsoft.com/keys/microsoft.asc -o "${key_tmp}"; then
      rm -f "${key_tmp}"
      echo "[2/8] Failed to download Microsoft Edge signing key. Check network access to packages.microsoft.com, or bundle microsoft-edge-stable_*.deb in app/debs/." >&2
      return 1
    fi
    if ! gpg --dearmor -o /etc/apt/keyrings/microsoft.gpg "${key_tmp}"; then
      rm -f "${key_tmp}"
      echo "[2/8] Failed to import Microsoft Edge signing key." >&2
      return 1
    fi
    rm -f "${key_tmp}"
    chmod 0644 /etc/apt/keyrings/microsoft.gpg
    FNDESK_CREATED_EDGE_KEY=1
  fi

  cat >/etc/apt/sources.list.d/microsoft-edge.list <<'EOF'
deb [arch=amd64 signed-by=/etc/apt/keyrings/microsoft.gpg] https://packages.microsoft.com/repos/edge stable main
EOF
  FNDESK_CREATED_EDGE_REPO=1
}

install_missing_packages() {
  local label="$1"
  shift
  local missing=()
  local package

  for package in "$@"; do
    if ! package_installed "${package}"; then
      missing+=("${package}")
    fi
  done

  if [[ "${#missing[@]}" -eq 0 ]]; then
    echo "${label}: already installed; skipping apt."
    return 0
  fi

  echo "${label}: installing ${missing[*]}"
  warn_dpkg_state_for_apt
  apt-get update || true
  apt-get install -y "${missing[@]}" || true

  local still_missing=()
  for package in "${missing[@]}"; do
    if ! package_installed "${package}"; then
      still_missing+=("${package}")
    fi
  done

  if [[ "${#still_missing[@]}" -ne 0 ]]; then
    echo "${label}: packages still missing after apt: ${still_missing[*]}" >&2
    return 1
  fi

  FNDESK_INSTALLED_PACKAGES+=("${missing[@]}")
}

echo "[1/8] Checking bootstrap packages: ${BOOTSTRAP_PACKAGES[*]}"
install_missing_packages "[1/8] Bootstrap packages" "${BOOTSTRAP_PACKAGES[@]}"

echo "[2/8] Checking Microsoft Edge"
if package_installed microsoft-edge-stable; then
  echo "[2/8] microsoft-edge-stable is already installed."
elif install_bundled_edge; then
  echo "[2/8] Bundled Microsoft Edge installed."
else
  echo "[2/8] Bundled Microsoft Edge not found; using Microsoft apt repository."
  setup_edge_repository
  install_missing_packages "[2/8] Microsoft Edge" microsoft-edge-stable
fi

echo "[3/8] Checking local display packages: ${LOCAL_PACKAGES[*]}"
install_missing_packages "[3/8] Local display packages" "${LOCAL_PACKAGES[@]}"

echo "[4/8] Ensuring kiosk user exists and can access graphics devices"
id "${KIOSK_USER}" >/dev/null 2>&1
usermod -aG video,render "${KIOSK_USER}"

echo "[4/8] Ensuring zh_CN.UTF-8 locale is available"
if ! locale -a | grep -qi '^zh_CN\.utf8$'; then
  sed -i 's/^# *\(zh_CN.UTF-8 UTF-8\)/\1/' /etc/locale.gen
  locale-gen zh_CN.UTF-8
fi

echo "[5/8] Configuring fcitx5 Chinese input for ${KIOSK_USER}"
KIOSK_HOME="$(getent passwd "${KIOSK_USER}" | cut -d: -f6)"
KIOSK_GROUP="$(id -gn "${KIOSK_USER}")"
install -d -o "${KIOSK_USER}" -g "${KIOSK_GROUP}" -m 0700 "${KIOSK_HOME}/.config/fcitx5"
cat >"${KIOSK_HOME}/.config/fcitx5/profile" <<'EOF'
[Groups/0]
Name=Default
Default Layout=us
DefaultIM=pinyin

[Groups/0/Items/0]
Name=keyboard-us
Layout=

[Groups/0/Items/1]
Name=pinyin
Layout=

[GroupOrder]
0=Default
EOF
chown "${KIOSK_USER}:${KIOSK_GROUP}" "${KIOSK_HOME}/.config/fcitx5/profile"

echo "[5/8] Adding FnDesk recovery aliases for ${KIOSK_USER}"
sed -i '/^alias fnre=/d' "${KIOSK_HOME}/.bashrc" 2>/dev/null || true
sed -i '/^alias fndesk-restart=/d' "${KIOSK_HOME}/.bashrc" 2>/dev/null || true
sed -i '/^alias fndesk-start=/d' "${KIOSK_HOME}/.bashrc" 2>/dev/null || true
sed -i '/^alias fndesk-stop=/d' "${KIOSK_HOME}/.bashrc" 2>/dev/null || true
cat >>"${KIOSK_HOME}/.bashrc" <<'EOF'

# FnDesk local display controls
alias fndesk-start='sudo systemctl --no-block start fndesk-local.service'
alias fndesk-stop='sudo systemctl --no-block stop fndesk-local.service'
alias fndesk-restart='sudo systemctl --no-block restart fndesk-local.service'
EOF
chown "${KIOSK_USER}:${KIOSK_GROUP}" "${KIOSK_HOME}/.bashrc"

echo "[6/8] Reserving tty1; FnDesk will use a private seatd instance"
systemctl_bounded disable getty@tty1.service 2>/dev/null || true
systemctl_bounded --no-block stop getty@tty1.service 2>/dev/null || true
for tty in tty2 tty3 tty4 tty5 tty6; do
  systemctl_bounded enable "getty@${tty}.service" >/dev/null 2>&1 || true
  systemctl_bounded --no-block start "getty@${tty}.service" >/dev/null 2>&1 || true
done

echo "[7/8] Writing FnDesk local display configuration"
install -d -m 0755 /etc/fndesk
cat >/etc/default/fndesk <<EOF
KIOSK_USER=${KIOSK_USER}
KIOSK_GROUP=${KIOSK_GROUP}
KIOSK_OUTPUT=${KIOSK_OUTPUT}
FNDESK_DRM_DEVICE=${FNDESK_DRM_DEVICE}
FNDESK_DRM_LEGACY=${FNDESK_DRM_LEGACY}
FNDESK_DRM_NO_MODIFIERS=${FNDESK_DRM_NO_MODIFIERS}
FNDESK_USE_SYSTEM_LIBDRM=${FNDESK_USE_SYSTEM_LIBDRM}
FNDESK_SOFTWARE_RENDERER=${FNDESK_SOFTWARE_RENDERER}
FNDESK_INSTALLED_PACKAGES='${FNDESK_INSTALLED_PACKAGES[*]}'
FNDESK_CREATED_EDGE_KEY=${FNDESK_CREATED_EDGE_KEY}
FNDESK_CREATED_EDGE_REPO=${FNDESK_CREATED_EDGE_REPO}
EOF

install -d -m 0755 /etc/opt/edge/policies/managed
cat >/etc/opt/edge/policies/managed/fndesk.json <<'EOF'
{
  "ApplicationLocaleValue": "zh-CN",
  "FavoritesBarEnabled": true,
  "HideFirstRunExperience": true
}
EOF
chmod 0644 /etc/opt/edge/policies/managed/fndesk.json
rm -f /etc/opt/edge/policies/managed/web-kiosk.json 2>/dev/null || true

install -m 0755 "${SCRIPT_DIR}/bin/fndesk-local-launch" /usr/local/bin/fndesk-local-launch
install -m 0755 "${SCRIPT_DIR}/bin/fndesk-local-browser" /usr/local/bin/fndesk-local-browser
install -m 0755 "${SCRIPT_DIR}/bin/fndesk-display-power" /usr/local/bin/fndesk-display-power
install -m 0755 "${SCRIPT_DIR}/bin/fndesk-seatd-socket-guard" /usr/local/bin/fndesk-seatd-socket-guard

install -d -m 0755 /etc/systemd/logind.conf.d /etc/systemd/sleep.conf.d
cat >/etc/systemd/logind.conf.d/fndesk.conf <<'EOF'
[Login]
IdleAction=ignore
HandleLidSwitch=ignore
HandleLidSwitchExternalPower=ignore
HandleLidSwitchDocked=ignore
HandlePowerKey=ignore
EOF

cat >/etc/systemd/sleep.conf.d/fndesk.conf <<'EOF'
[Sleep]
AllowSuspend=no
AllowHibernation=no
AllowSuspendThenHibernate=no
AllowHybridSleep=no
EOF

echo "[8/8] Writing systemd units"
install -m 0644 "${SCRIPT_DIR}/systemd/fndesk-local.service" /etc/systemd/system/fndesk-local.service
install -m 0644 "${SCRIPT_DIR}/systemd/fndesk-display-power.service" /etc/systemd/system/fndesk-display-power.service

# Remove old Web Edge/noVNC service names and hotplug auto-start behavior.
systemctl_bounded --no-block stop web-kiosk.service 2>/dev/null || true
systemctl_bounded --no-block stop web-kiosk-display-power.service 2>/dev/null || true
systemctl_bounded disable web-kiosk.service 2>/dev/null || true
systemctl_bounded disable web-kiosk-display-power.service 2>/dev/null || true
rm -f /etc/systemd/system/web-kiosk.service 2>/dev/null || true
rm -f /etc/systemd/system/web-kiosk-display-power.service 2>/dev/null || true
rm -f /usr/local/bin/web-kiosk-launch 2>/dev/null || true
rm -f /usr/local/bin/web-kiosk-browser 2>/dev/null || true
rm -f /usr/local/bin/web-kiosk-display-power 2>/dev/null || true
rm -f /etc/default/web-kiosk 2>/dev/null || true
rm -rf /etc/web-kiosk 2>/dev/null || true
rm -f /etc/systemd/logind.conf.d/web-kiosk.conf 2>/dev/null || true
rm -f /etc/systemd/sleep.conf.d/web-kiosk.conf 2>/dev/null || true
rm -f /etc/udev/rules.d/99-web-kiosk-drm.rules 2>/dev/null || true
udevadm control --reload-rules 2>/dev/null || true

# seatd-launch needs exclusive ownership of /run/seatd.sock. It creates a
# per-session seatd whose target runs as KIOSK_USER; the global restart-always
# daemon must therefore remain disabled while FnDesk is installed.
systemctl_bounded disable seatd.service 2>/dev/null || true
systemctl_bounded --no-block stop seatd.service 2>/dev/null || true

systemctl_bounded daemon-reload
systemctl_bounded mask sleep.target suspend.target hibernate.target hybrid-sleep.target suspend-then-hibernate.target 2>/dev/null || true
systemctl_bounded enable fndesk-display-power.service
systemctl_bounded --no-block start fndesk-display-power.service
systemctl_bounded disable fndesk-local.service 2>/dev/null || true
systemctl_bounded --no-block stop fndesk-local.service 2>/dev/null || true

echo
echo "Install completed."
echo "FnDesk control console manages the local-display Edge."
echo "Local Edge does not start automatically. Start it from the Web console or run: systemctl start fndesk-local.service"
echo "Chinese input uses fcitx5 pinyin. Toggle with Ctrl+Space if needed."
echo "The new logind power policy takes effect after logind is next restarted; the installer does not interrupt active sessions."
echo "Check local logs with: journalctl -u fndesk-local.service -b"
