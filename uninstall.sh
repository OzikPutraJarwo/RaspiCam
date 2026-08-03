#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${RASPICAM_DIR:-/opt/raspicam}"
SERVICE_NAME="raspicam"

if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
else
  SUDO="sudo"
fi

echo "This removes the RaspiCam service and program files from $INSTALL_DIR."
echo "Recorded video on your storage drive is never touched."
read -r -p "Continue? [y/N] " reply
case "$reply" in
  y|Y) ;;
  *) echo "Cancelled."; exit 0 ;;
esac

$SUDO systemctl disable --now $SERVICE_NAME >/dev/null 2>&1 || true
$SUDO rm -f /etc/systemd/system/$SERVICE_NAME.service
$SUDO systemctl daemon-reload
$SUDO rm -f /usr/local/bin/raspicam

read -r -p "Also delete settings in $INSTALL_DIR/data? [y/N] " purge
case "$purge" in
  y|Y) $SUDO rm -rf "$INSTALL_DIR" ;;
  *) $SUDO find "$INSTALL_DIR" -mindepth 1 -maxdepth 1 ! -name data -exec rm -rf {} + ;;
esac

echo "RaspiCam removed."
