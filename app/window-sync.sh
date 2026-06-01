#!/usr/bin/env bash
set -u

sync_name="${FNDESK_WINDOW_SYNC_NAME:-fndesk-window-sync}"
edge_class="${FNDESK_EDGE_CLASS:-Microsoft-edge}"
interval="${FNDESK_WINDOW_SYNC_INTERVAL:-0.3}"

exec -a "${sync_name}" bash -c '
edge_class="$1"
interval="$2"

find_edge_window() {
  local w
  w="$(xdotool search --onlyvisible --class "${edge_class}" 2>/dev/null | head -n 1)"
  if [ -z "${w}" ]; then
    w="$(xdotool search --onlyvisible --name "Microsoft.*Edge" 2>/dev/null | head -n 1)"
  fi
  printf "%s" "${w}"
}

# 让 Edge 窗口严格铺满 Xvnc 桌面：只有当窗口几何与桌面不一致时才调整，
# 这样既能在 noVNC 改变远端分辨率后立刻跟随铺满（无黑边/不超出），
# 又不会每个周期都强制移动窗口而造成抖动或抢焦点。
while :; do
  desktop_size="$(xdpyinfo 2>/dev/null | awk "/dimensions:/ { print \$2; exit }")"
  width="${desktop_size%x*}"
  height="${desktop_size#*x}"

  if [ "${desktop_size}" != "${width}" ] && [ "${width}" -gt 0 ] 2>/dev/null && [ "${height}" -gt 0 ] 2>/dev/null; then
    win="$(find_edge_window)"
    if [ -n "${win}" ]; then
      WIDTH=0; HEIGHT=0; X=-1; Y=-1
      eval "$(xdotool getwindowgeometry --shell "${win}" 2>/dev/null)"
      if [ "${WIDTH}" != "${width}" ] || [ "${HEIGHT}" != "${height}" ] || [ "${X}" != "0" ] || [ "${Y}" != "0" ]; then
        xdotool windowmove "${win}" 0 0 >/dev/null 2>&1 || true
        xdotool windowsize "${win}" "${width}" "${height}" >/dev/null 2>&1 || true
        xdotool windowfocus "${win}" >/dev/null 2>&1 || true
      fi
    fi
  fi

  sleep "${interval}"
done
' "${sync_name}" "${edge_class}" "${interval}"
