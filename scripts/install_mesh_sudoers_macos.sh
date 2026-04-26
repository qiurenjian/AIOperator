#!/usr/bin/env bash
# Install the minimal sudoers rule needed for local mesh self-healing on macOS.

set -euo pipefail

RULE_FILE="/etc/sudoers.d/aiop-mesh-health"
TMP_FILE="/tmp/aiop-mesh-health-sudoers"

cat > "$TMP_FILE" <<'EOF'
renjianqiu ALL=(root) NOPASSWD: /usr/sbin/sshd, /bin/launchctl
EOF

sudo mkdir -p /etc/sudoers.d
sudo cp "$TMP_FILE" "$RULE_FILE"
sudo chmod 440 "$RULE_FILE"
sudo visudo -cf "$RULE_FILE"

echo "Installed sudoers rule: $RULE_FILE"
