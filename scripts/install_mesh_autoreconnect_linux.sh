#!/usr/bin/env bash
# Install boot-time auto-reconnect checks for the cloud Linux node.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SERVICE_SRC="$REPO_DIR/ops/systemd/aiop-mesh-health.service"
TIMER_SRC="$REPO_DIR/ops/systemd/aiop-mesh-health.timer"

echo "Installing systemd units..."
cp "$SERVICE_SRC" /etc/systemd/system/aiop-mesh-health.service
cp "$TIMER_SRC" /etc/systemd/system/aiop-mesh-health.timer

echo "Enabling sshd/ssh and tailscaled when available..."
systemctl enable --now sshd 2>/dev/null || systemctl enable --now ssh 2>/dev/null || true
systemctl enable --now tailscaled 2>/dev/null || true

echo "Enabling mesh health timer..."
systemctl daemon-reload
systemctl enable --now aiop-mesh-health.timer
systemctl start aiop-mesh-health.service || true

echo ""
echo "Installed. Verify with:"
echo "  systemctl list-timers aiop-mesh-health.timer"
echo "  journalctl -u aiop-mesh-health.service -n 100 --no-pager"
echo "  tail -f /var/log/aiop-mesh-health.log"
