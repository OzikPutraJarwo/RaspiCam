#!/usr/bin/env bash
set -uo pipefail

INSTALL_DIR="__INSTALL_DIR__"
SERVICE_NAME="raspicam"
LIB_DIR="/usr/local/lib/raspicam"

PURGE_MEDIA=0
if [ "${1:-}" = "--media" ]; then
  PURGE_MEDIA=1
fi

if [ -z "${RASPICAM_PURGE_DETACHED:-}" ]; then
  TEMP="$(mktemp /tmp/raspicam-purge.XXXXXX)"
  cp "$0" "$TEMP"
  chmod 755 "$TEMP"
  if command -v systemd-run >/dev/null 2>&1; then
    exec systemd-run --unit=raspicam-purge --collect --setenv=RASPICAM_PURGE_DETACHED=1 "$TEMP" "$@"
  fi
  exec setsid env RASPICAM_PURGE_DETACHED=1 "$TEMP" "$@"
fi

sleep 2

if [ "$PURGE_MEDIA" = "1" ] && [ -f "$INSTALL_DIR/data/config.json" ]; then
  MEDIA_ROOT="$(python3 -c "import json;print(json.load(open('$INSTALL_DIR/data/config.json'))['storage'].get('root') or '')" 2>/dev/null)"
  if [ -n "$MEDIA_ROOT" ] && [ -d "$MEDIA_ROOT/RaspiCam" ]; then
    rm -rf "${MEDIA_ROOT:?}/RaspiCam"
  fi
fi

systemctl disable --now "$SERVICE_NAME" >/dev/null 2>&1
rm -f "/etc/systemd/system/$SERVICE_NAME.service"
systemctl daemon-reload >/dev/null 2>&1
rm -f /usr/local/bin/raspicam

if [ -f "$LIB_DIR/extras" ]; then
  while IFS= read -r extra; do
    if [ -n "$extra" ] && [ -e "$extra" ]; then
      rm -f "$extra"
    fi
  done < "$LIB_DIR/extras"
fi

if [ -f "$LIB_DIR/npm-extras" ]; then
  while IFS= read -r package; do
    if [ -n "$package" ]; then
      npm uninstall -g "$package" >/dev/null 2>&1
    fi
  done < "$LIB_DIR/npm-extras"
fi

rm -f /etc/sudoers.d/raspicam
rm -rf "${INSTALL_DIR:?}"
rm -rf "$LIB_DIR"
rm -f "$0"
