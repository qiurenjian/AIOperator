#!/usr/bin/env bash
# Install boot/login-time auto-reconnect checks for M5/MBP.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLIST_SRC="$REPO_DIR/ops/launchd/com.aioperator.mesh-health.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.aioperator.mesh-health.plist"

echo "Enabling standard macOS sshd..."
sudo /usr/sbin/sshd -t
sudo launchctl enable system/com.openssh.sshd
sudo launchctl bootstrap system /System/Library/LaunchDaemons/ssh.plist 2>/dev/null || true
sudo launchctl kickstart -k system/com.openssh.sshd

echo "Starting Tailscale app if it is installed..."
if [[ -x /Applications/Tailscale.app/Contents/MacOS/Tailscale ]]; then
  open -g -a Tailscale || true
else
  echo "WARN: /Applications/Tailscale.app not found"
fi

echo "Installing per-login mesh health check..."
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cp "$PLIST_SRC" "$PLIST_DST"
launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"
launchctl start com.aioperator.mesh-health || true

echo "Applying power settings for plugged-in operation..."
sudo pmset -c sleep 0 displaysleep 30 disksleep 0 womp 1 tcpkeepalive 1 powernap 1 || true
sudo pmset autorestart 1 || true

echo ""
echo "Installed. Verify with:"
echo "  launchctl list | grep com.aioperator.mesh-health"
echo "  tail -f ~/Library/Logs/aiop-mesh-health.log"
echo ""
echo "Note: this LaunchAgent runs after the user session starts."
echo "For unattended recovery after a full power loss, make sure the Mac can boot and log in, and Tailscale is configured to start at login."
