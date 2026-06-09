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
FNDESK_INSTALLED_PACKAGES=()
FNDESK_CREATED_EDGE_KEY=0
FNDESK_CREATED_EDGE_REPO=0

BOOTSTRAP_PACKAGES=(
  ca-certificates
  curl
  gnupg
  locales
)

LOCAL_PACKAGES=(
  cage
  seatd
  wlr-randr
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
alias fndesk-start='sudo systemctl start fndesk-local.service && sudo chvt 1'
alias fndesk-stop='sudo systemctl stop fndesk-local.service'
alias fndesk-restart='sudo systemctl restart fndesk-local.service && sudo chvt 1'
EOF
chown "${KIOSK_USER}:${KIOSK_GROUP}" "${KIOSK_HOME}/.bashrc"

echo "[6/8] Enabling seatd and reserving tty1"
systemctl enable --now seatd.service
systemctl disable --now getty@tty1.service 2>/dev/null || true
for tty in tty2 tty3 tty4 tty5 tty6; do
  systemctl enable --now "getty@${tty}.service" >/dev/null 2>&1 || true
done

echo "[7/8] Writing FnDesk local display configuration"
install -d -m 0755 /etc/fndesk
cat >/etc/default/fndesk <<EOF
KIOSK_USER=${KIOSK_USER}
KIOSK_OUTPUT=${KIOSK_OUTPUT}
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

cat >/usr/local/bin/fndesk-local-launch <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

source /etc/default/fndesk

export XDG_RUNTIME_DIR="/run/fndesk-local"
export LIBSEAT_BACKEND=seatd
export WLR_LIBINPUT_NO_DEVICES=1
export WLR_NO_HARDWARE_CURSORS=1
export GTK_IM_MODULE=fcitx
export QT_IM_MODULE=fcitx
export XMODIFIERS=@im=fcitx
export INPUT_METHOD=fcitx
export SDL_IM_MODULE=fcitx
export LANG=zh_CN.UTF-8
export LANGUAGE=zh_CN:zh
export LC_ALL=zh_CN.UTF-8
export XCURSOR_THEME=Adwaita
export XCURSOR_SIZE=24

mkdir -p "${XDG_RUNTIME_DIR}"
chmod 700 "${XDG_RUNTIME_DIR}"

if [[ -n "${KIOSK_OUTPUT:-}" ]] && command -v wlr-randr >/dev/null 2>&1; then
  wlr-randr --output "${KIOSK_OUTPUT}" --on || true
fi

has_connected_display() {
  local connector

  if [[ -n "${KIOSK_OUTPUT:-}" ]]; then
    connector="/sys/class/drm/${KIOSK_OUTPUT}/status"
    if [[ -f "${connector}" ]] && grep -qx connected "${connector}"; then
      return 0
    fi
    connector="/sys/class/drm/card0-${KIOSK_OUTPUT}/status"
    if [[ -f "${connector}" ]] && grep -qx connected "${connector}"; then
      return 0
    fi
    return 1
  fi

  for connector in /sys/class/drm/*/status; do
    [[ -f "${connector}" ]] || continue
    if grep -qx connected "${connector}"; then
      return 0
    fi
  done

  return 1
}

if ! has_connected_display; then
  echo "FnDesk local display: no connected DRM display; local display service is idle." >&2
  exit 75
fi

exec dbus-run-session -- cage -s -- /usr/local/bin/fndesk-local-browser
EOF
chmod 0755 /usr/local/bin/fndesk-local-launch

cat >/usr/local/bin/fndesk-local-browser <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

source /etc/default/fndesk

export GTK_IM_MODULE=fcitx
export QT_IM_MODULE=fcitx
export XMODIFIERS=@im=fcitx
export INPUT_METHOD=fcitx
export SDL_IM_MODULE=fcitx
export LANG=zh_CN.UTF-8
export LANGUAGE=zh_CN:zh
export LC_ALL=zh_CN.UTF-8

if command -v dbus-update-activation-environment >/dev/null 2>&1; then
  dbus-update-activation-environment --systemd \
    DISPLAY XDG_CURRENT_DESKTOP XDG_RUNTIME_DIR \
    GTK_IM_MODULE QT_IM_MODULE XMODIFIERS INPUT_METHOD SDL_IM_MODULE \
    LANG LANGUAGE LC_ALL || true
fi

fcitx5 --enable xim,xcb -d || true
sleep 1
fcitx5-remote -o >/dev/null 2>&1 || true

edge_args=(
  --start-maximized
  --ozone-platform=x11
  --lang=zh-CN
  --no-first-run
  --no-default-browser-check
  --password-store=basic
  --disable-background-timer-throttling
  --disable-renderer-backgrounding
  --disable-backgrounding-occluded-windows
  --disable-session-crashed-bubble
  --disable-infobars
  --enable-features=OverlayScrollbar
)

exec microsoft-edge-stable "${edge_args[@]}"
EOF
chmod 0755 /usr/local/bin/fndesk-local-browser

cat >/usr/local/bin/fndesk-display-power <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

if [[ -w /sys/module/kernel/parameters/consoleblank ]]; then
  printf '0' >/sys/module/kernel/parameters/consoleblank || true
fi

if command -v setterm >/dev/null 2>&1 && [[ -w /dev/tty1 ]]; then
  setterm --blank 0 --powerdown 0 --powersave off </dev/tty1 >/dev/tty1 2>/dev/null || true
fi
EOF
chmod 0755 /usr/local/bin/fndesk-display-power

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
cat >/etc/systemd/system/fndesk-local.service <<EOF
[Unit]
Description=FnDesk Local Microsoft Edge
After=systemd-user-sessions.service network-online.target seatd.service
Wants=network-online.target seatd.service
Conflicts=getty@tty1.service

[Service]
Type=simple
EnvironmentFile=/etc/default/fndesk
User=root
ExecStartPre=/usr/bin/install -d -o ${KIOSK_USER} -g $(id -gn ${KIOSK_USER}) -m 0700 /run/fndesk-local
ExecStartPre=-/usr/bin/chvt 1
ExecStart=/usr/sbin/runuser -u ${KIOSK_USER} -- /usr/local/bin/fndesk-local-launch
ExecStopPost=/usr/bin/rm -rf /run/fndesk-local
Restart=on-failure
RestartPreventExitStatus=75
RestartSec=2
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
StandardInput=tty
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

cat >/etc/systemd/system/fndesk-display-power.service <<'EOF'
[Unit]
Description=FnDesk Display Power Policy
Before=fndesk-local.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/fndesk-display-power
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

# Remove old Web Edge/noVNC service names and hotplug auto-start behavior.
systemctl disable --now web-kiosk.service 2>/dev/null || true
systemctl disable --now web-kiosk-display-power.service 2>/dev/null || true
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

systemctl daemon-reload
systemctl mask sleep.target suspend.target hibernate.target hybrid-sleep.target suspend-then-hibernate.target 2>/dev/null || true
systemctl restart systemd-logind.service 2>/dev/null || true
systemctl enable --now fndesk-display-power.service
systemctl disable fndesk-local.service 2>/dev/null || true
systemctl stop fndesk-local.service 2>/dev/null || true

echo
echo "Install completed."
echo "FnDesk control console manages the local-display Edge."
echo "Local Edge does not start automatically. Start it from the Web console or run: systemctl start fndesk-local.service"
echo "Chinese input uses fcitx5 pinyin. Toggle with Ctrl+Space if needed."
echo "Check local logs with: journalctl -u fndesk-local.service -b"
