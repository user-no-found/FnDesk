#!/usr/bin/env bash
set -u

sync_name="${FNDESK_WINDOW_SYNC_NAME:-fndesk-window-sync}"
edge_class="${FNDESK_EDGE_CLASS:-Microsoft-edge}"
interval="${FNDESK_WINDOW_SYNC_INTERVAL:-1}"

exec -a "${sync_name}" bash -c '
edge_class="$1"
interval="$2"

while :; do
  desktop_size="$(xdpyinfo 2>/dev/null | awk "/dimensions:/ { print \$2; exit }")"
  width="${desktop_size%x*}"
  height="${desktop_size#*x}"

  if [ "${desktop_size}" != "${width}" ] && [ "${width}" -gt 0 ] 2>/dev/null && [ "${height}" -gt 0 ] 2>/dev/null; then
    windows="$(xdotool search --onlyvisible --class "${edge_class}" 2>/dev/null || true)"
    if [ -z "${windows}" ]; then
      windows="$(xdotool search --onlyvisible --name "Microsoft.*Edge" 2>/dev/null || true)"
    fi

    for win in ${windows}; do
      xdotool windowmove "${win}" 0 0 >/dev/null 2>&1 || true
      xdotool windowsize "${win}" "${width}" "${height}" >/dev/null 2>&1 || true
      xdotool windowfocus "${win}" >/dev/null 2>&1 || true
      break
    done
  fi

  sleep "${interval}"
done
' "${sync_name}" "${edge_class}" "${interval}"
