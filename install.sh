#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${RASPICAM_REPO:-https://github.com/OzikPutraJarwo/RaspiCam.git}"
BRANCH="${RASPICAM_BRANCH:-main}"
INSTALL_DIR="${RASPICAM_DIR:-/opt/raspicam}"
SERVICE_NAME="raspicam"
PORT="${RASPICAM_PORT:-}"

info() { printf "\033[1;34m==>\033[0m %s\n" "$1"; }
warn() { printf "\033[1;33m!!\033[0m %s\n" "$1"; }
fail() { printf "\033[1;31mxx\033[0m %s\n" "$1" >&2; exit 1; }

if [ "$(id -u)" -eq 0 ]; then
  SUDO=""
  TARGET_USER="${SUDO_USER:-root}"
else
  command -v sudo >/dev/null 2>&1 || fail "sudo is required. Run this script as root instead."
  SUDO="sudo"
  TARGET_USER="$(id -un)"
fi
TARGET_GROUP="$(id -gn "$TARGET_USER")"

run_as() {
  if [ "$(id -un)" = "$TARGET_USER" ]; then
    "$@"
  elif [ "$(id -u)" -eq 0 ] && command -v runuser >/dev/null 2>&1; then
    runuser -u "$TARGET_USER" -- "$@"
  else
    sudo -u "$TARGET_USER" "$@"
  fi
}

git_admin() {
  $SUDO git -c safe.directory="$INSTALL_DIR" "$@"
}

command -v apt-get >/dev/null 2>&1 || fail "This installer supports Raspberry Pi OS and other Debian based systems."

info "Installing system packages"
$SUDO apt-get update -qq
$SUDO apt-get install -y -qq git python3 python3-venv python3-pip ffmpeg v4l-utils >/dev/null

if grep -qi raspberry /proc/device-tree/model 2>/dev/null; then
  if ! command -v rpicam-hello >/dev/null 2>&1 && ! command -v libcamera-hello >/dev/null 2>&1; then
    info "Installing Raspberry Pi camera tools"
    $SUDO apt-get install -y -qq rpicam-apps >/dev/null 2>&1 || $SUDO apt-get install -y -qq libcamera-apps >/dev/null 2>&1 || warn "Could not install rpicam-apps, CSI cameras may not work."
  fi
fi

if [ -d "$INSTALL_DIR/.git" ]; then
  info "Updating RaspiCam in $INSTALL_DIR"
  git_admin -C "$INSTALL_DIR" remote set-url origin "$REPO_URL"
  git_admin -C "$INSTALL_DIR" fetch --depth 1 origin "$BRANCH"
  git_admin -C "$INSTALL_DIR" reset --hard "origin/$BRANCH"
else
  info "Downloading RaspiCam into $INSTALL_DIR"
  $SUDO rm -rf "$INSTALL_DIR"
  $SUDO mkdir -p "$INSTALL_DIR"
  $SUDO git clone --depth 1 --branch "$BRANCH" "$REPO_URL" "$INSTALL_DIR"
fi
$SUDO chown -R "$TARGET_USER":"$TARGET_GROUP" "$INSTALL_DIR"

info "Setting up the Python environment"
run_as python3 -m venv "$INSTALL_DIR/.venv"
run_as "$INSTALL_DIR/.venv/bin/pip" install --quiet --upgrade pip
run_as "$INSTALL_DIR/.venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
run_as mkdir -p "$INSTALL_DIR/data"

if ! command -v cloudflared >/dev/null 2>&1; then
  case "$(uname -m)" in
    aarch64|arm64) CF_ARCH="arm64" ;;
    armv7l|armv6l) CF_ARCH="arm" ;;
    x86_64) CF_ARCH="amd64" ;;
    *) CF_ARCH="" ;;
  esac
  if [ -n "$CF_ARCH" ]; then
    info "Installing cloudflared for one click remote access"
    if curl -fsSL -o /tmp/cloudflared "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$CF_ARCH"; then
      $SUDO install -m 755 /tmp/cloudflared /usr/local/bin/cloudflared
      rm -f /tmp/cloudflared
    else
      warn "cloudflared download failed. Serveo will still be available."
    fi
  fi
fi

info "Registering the raspicam service"
$SUDO usermod -aG video "$TARGET_USER" >/dev/null 2>&1 || true
$SUDO install -m 755 "$INSTALL_DIR/bin/raspicam" /usr/local/bin/raspicam

ENV_LINE=""
if [ -n "$PORT" ]; then
  ENV_LINE="Environment=RASPICAM_PORT=$PORT"
fi

$SUDO tee /etc/systemd/system/$SERVICE_NAME.service >/dev/null <<UNIT
[Unit]
Description=RaspiCam surveillance dashboard
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$TARGET_USER
Group=$TARGET_GROUP
SupplementaryGroups=video
WorkingDirectory=$INSTALL_DIR
$ENV_LINE
ExecStart=$INSTALL_DIR/.venv/bin/python -m app.run
Restart=always
RestartSec=3
KillMode=mixed
TimeoutStopSec=15

[Install]
WantedBy=multi-user.target
UNIT

$SUDO systemctl daemon-reload
$SUDO systemctl enable --now $SERVICE_NAME >/dev/null 2>&1
$SUDO systemctl restart $SERVICE_NAME

sleep 2
ADDRESS="$(hostname -I 2>/dev/null | awk '{print $1}')"
ACTIVE_PORT="${PORT:-8080}"

echo
info "RaspiCam is installed"
echo "   Open http://${ADDRESS:-localhost}:$ACTIVE_PORT in a browser and set your password."
echo "   Manage it with: raspicam status | logs | restart | update | uninstall"
echo
if ! $SUDO systemctl is-active --quiet $SERVICE_NAME; then
  warn "The service is not running yet. Check the output of: raspicam logs"
fi
