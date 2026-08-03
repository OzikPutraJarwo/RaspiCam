#!/usr/bin/env bash
set -uo pipefail

LIB_DIR="/usr/local/lib/raspicam"
PURGE="$LIB_DIR/purge.sh"

if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
else
  SUDO="sudo"
fi

if [ ! -x "$PURGE" ]; then
  echo "RaspiCam does not look like it was installed with install.sh." >&2
  exit 1
fi

echo "This removes RaspiCam completely: the service, the program files, your settings,"
echo "and the tunnel clients that were installed with it."
read -r -p "Continue? [y/N] " reply </dev/tty
case "$reply" in
  y | Y) ;;
  *)
    echo "Cancelled."
    exit 0
    ;;
esac

read -r -p "Also delete every recording and photo on the storage drive? [y/N] " media </dev/tty
case "$media" in
  y | Y) $SUDO "$PURGE" --media ;;
  *) $SUDO "$PURGE" ;;
esac

echo "RaspiCam is being removed. This takes a few seconds."
