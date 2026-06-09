#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT="${SCRIPT_DIR}/fndesk.fpk"
APP_TGZ="${SCRIPT_DIR}/app.tgz"

if [[ ! -d "${SCRIPT_DIR}/app" ]]; then
  echo "Missing app" >&2
  exit 1
fi

echo "========================================="
echo "  FnDesk build"
echo "========================================="

VERSION="$(awk '/^version[[:space:]]*=/{print $3; exit}' "${SCRIPT_DIR}/manifest")"
echo "Version: ${VERSION}"

chmod 755 "${SCRIPT_DIR}/cmd/main" "${SCRIPT_DIR}"/cmd/*_init "${SCRIPT_DIR}"/cmd/*_callback 2>/dev/null || true
chmod 755 "${SCRIPT_DIR}/app/install-kiosk.sh"
find "${SCRIPT_DIR}/app" -type d -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true
find "${SCRIPT_DIR}/app" -type f -name '*.pyc' -delete 2>/dev/null || true

rm -f "${APP_TGZ}" "${OUTPUT}"
tar -czf "${APP_TGZ}" -C "${SCRIPT_DIR}/app" .
tar -czf "${OUTPUT}" -C "${SCRIPT_DIR}" app.tgz cmd config ICON.PNG ICON_256.PNG LICENSE manifest wizard
rm -f "${APP_TGZ}"

echo "Built: ${OUTPUT}"
echo "Size: $(ls -lh "${OUTPUT}" | awk '{print $5}')"
echo "========================================="
