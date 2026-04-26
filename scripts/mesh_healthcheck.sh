#!/usr/bin/env bash
# Health check and local self-healing for the AIOperator Tailscale SSH mesh.

set -o pipefail

M5_IP="${M5_IP:-100.127.88.43}"
MBP_IP="${MBP_IP:-100.91.236.65}"
CLOUD_IP="${CLOUD_IP:-100.72.54.102}"
MAC_USER="${MAC_USER:-renjianqiu}"
CLOUD_USER="${CLOUD_USER:-root}"
CLOUD_PORT="${CLOUD_PORT:-28022}"
CHECK_TIMEOUT="${CHECK_TIMEOUT:-6}"
LOG_FILE="${LOG_FILE:-$HOME/Library/Logs/aiop-mesh-health.log}"

if [[ "$(uname -s)" == "Linux" ]]; then
  LOG_FILE="${LOG_FILE:-/var/log/aiop-mesh-health.log}"
fi

mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null || true

ts() {
  date "+%Y-%m-%d %H:%M:%S%z"
}

log() {
  printf "%s [%s] %s\n" "$(ts)" "$1" "$2" | tee -a "$LOG_FILE" >/dev/null
}

tailscale_bin() {
  if [[ "$(uname -s)" == "Darwin" && -x /Applications/Tailscale.app/Contents/MacOS/Tailscale ]]; then
    printf "%s\n" "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
    return 0
  fi

  if command -v tailscale >/dev/null 2>&1; then
    command -v tailscale
    return 0
  fi

  return 1
}

tailscale_cmd() {
  local candidates=()

  if [[ "$(uname -s)" == "Darwin" && -x /Applications/Tailscale.app/Contents/MacOS/Tailscale ]]; then
    candidates+=("/Applications/Tailscale.app/Contents/MacOS/Tailscale")
  fi

  [[ -x /usr/local/bin/tailscale ]] && candidates+=("/usr/local/bin/tailscale")
  [[ -x /opt/homebrew/bin/tailscale ]] && candidates+=("/opt/homebrew/bin/tailscale")

  if command -v tailscale >/dev/null 2>&1; then
    candidates+=("$(command -v tailscale)")
  fi

  if [[ -S /tmp/tailscale/tailscaled.sock ]]; then
    [[ -x /usr/local/bin/tailscale ]] && candidates+=("/usr/local/bin/tailscale --socket=/tmp/tailscale/tailscaled.sock")
    [[ -x /opt/homebrew/bin/tailscale ]] && candidates+=("/opt/homebrew/bin/tailscale --socket=/tmp/tailscale/tailscaled.sock")
    if [[ -x /Applications/Tailscale.app/Contents/MacOS/Tailscale ]]; then
      candidates+=("/Applications/Tailscale.app/Contents/MacOS/Tailscale --socket=/tmp/tailscale/tailscaled.sock")
    fi
    if command -v tailscale >/dev/null 2>&1; then
      candidates+=("$(command -v tailscale) --socket=/tmp/tailscale/tailscaled.sock")
    fi
  fi

  local candidate
  for candidate in "${candidates[@]}"; do
    # shellcheck disable=SC2086
    if $candidate status >/dev/null 2>&1; then
      printf "%s\n" "$candidate"
      return 0
    fi
  done

  [[ "${#candidates[@]}" -gt 0 ]] && printf "%s\n" "${candidates[0]}" && return 0
  return 1
}

using_tailscale_userspace() {
  [[ -S /tmp/tailscale/tailscaled.sock ]]
}

local_tailscale_ip() {
  local ts_cmd
  ts_cmd="$(tailscale_cmd)" || return 1
  # shellcheck disable=SC2086
  $ts_cmd ip -4 2>/dev/null | head -n 1
}

local_node() {
  local ip
  ip="$(local_tailscale_ip || true)"
  case "$ip" in
    "$M5_IP") echo "m5" ;;
    "$MBP_IP") echo "mbp" ;;
    "$CLOUD_IP") echo "cloud" ;;
    *) echo "unknown" ;;
  esac
}

ssh_port_for_node() {
  case "$1" in
    cloud) echo "$CLOUD_PORT" ;;
    *) echo "22" ;;
  esac
}

user_for_node() {
  case "$1" in
    cloud) echo "$CLOUD_USER" ;;
    *) echo "$MAC_USER" ;;
  esac
}

ip_for_node() {
  case "$1" in
    m5) echo "$M5_IP" ;;
    mbp) echo "$MBP_IP" ;;
    cloud) echo "$CLOUD_IP" ;;
  esac
}

check_tailscale() {
  local ts_cmd
  if ! ts_cmd="$(tailscale_cmd)"; then
    log "ERROR" "tailscale binary not found"
    return 1
  fi

  # shellcheck disable=SC2086
  if $ts_cmd status >/dev/null 2>&1 && [[ -n "$(local_tailscale_ip || true)" ]]; then
    log "OK" "tailscale status is healthy"
    return 0
  fi

  log "WARN" "tailscale status or local IP check failed; trying local restart"
  if [[ "$(uname -s)" == "Darwin" ]]; then
    open -g -a Tailscale >/dev/null 2>&1 || true
  elif command -v systemctl >/dev/null 2>&1; then
    sudo -n systemctl restart tailscaled >/dev/null 2>&1 || true
  fi

  sleep 2
  # shellcheck disable=SC2086
  if $ts_cmd status >/dev/null 2>&1 && [[ -n "$(local_tailscale_ip || true)" ]]; then
    log "OK" "tailscale recovered after restart attempt"
    return 0
  fi

  log "ERROR" "tailscale is still unhealthy or not logged in"
  return 1
}

port_listening() {
  local port="$1"
  if command -v nc >/dev/null 2>&1 && nc -z -w "$CHECK_TIMEOUT" 127.0.0.1 "$port" >/dev/null 2>&1; then
    return 0
  fi

  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
  elif command -v ss >/dev/null 2>&1; then
    ss -ltn "( sport = :$port )" | grep -q ":$port"
  else
    return 1
  fi
}

restart_local_sshd() {
  if [[ "$(uname -s)" == "Darwin" ]]; then
    sudo -n /usr/sbin/sshd -t >/dev/null 2>&1 || {
      log "ERROR" "local sshd config check failed"
      return 1
    }
    sudo -n launchctl enable system/com.openssh.sshd >/dev/null 2>&1 || true
    sudo -n launchctl bootstrap system /System/Library/LaunchDaemons/ssh.plist >/dev/null 2>&1 || true
    sudo -n launchctl kickstart -k system/com.openssh.sshd >/dev/null 2>&1
  elif command -v systemctl >/dev/null 2>&1; then
    sudo -n systemctl restart sshd >/dev/null 2>&1 || sudo -n systemctl restart ssh >/dev/null 2>&1
  else
    return 1
  fi
}

check_local_sshd() {
  local node="$1"
  local port
  port="$(ssh_port_for_node "$node")"

  if port_listening "$port"; then
    log "OK" "local sshd is listening on port $port"
    return 0
  fi

  log "WARN" "local sshd is not listening on port $port; trying restart"
  if restart_local_sshd && sleep 2 && port_listening "$port"; then
    log "OK" "local sshd recovered on port $port"
    return 0
  fi

  log "ERROR" "local sshd is still down on port $port; sudo NOPASSWD may be required"
  return 1
}

tcp_probe() {
  local node="$1"
  local ip port
  ip="$(ip_for_node "$node")"
  port="$(ssh_port_for_node "$node")"

  if using_tailscale_userspace; then
    return 0
  fi

  if command -v nc >/dev/null 2>&1; then
    nc -z -w "$CHECK_TIMEOUT" "$ip" "$port" >/dev/null 2>&1
  else
    timeout "$CHECK_TIMEOUT" bash -c "</dev/tcp/$ip/$port" >/dev/null 2>&1
  fi
}

ssh_probe() {
  local node="$1"
  local ip port user
  ip="$(ip_for_node "$node")"
  port="$(ssh_port_for_node "$node")"
  user="$(user_for_node "$node")"

  local proxy_args=()
  if using_tailscale_userspace; then
    local ts_cmd
    ts_cmd="$(tailscale_cmd)" || return 1
    proxy_args=(-o "ProxyCommand=$ts_cmd nc %h %p")
  fi

  ssh \
    -o BatchMode=yes \
    -o ControlMaster=no \
    -o ConnectTimeout="$CHECK_TIMEOUT" \
    -o ServerAliveInterval=10 \
    -o ServerAliveCountMax=2 \
    -o StrictHostKeyChecking=no \
    "${proxy_args[@]}" \
    -p "$port" \
    "$user@$ip" hostname >/dev/null 2>&1
}

check_remote_node() {
  local node="$1"
  local ip port
  ip="$(ip_for_node "$node")"
  port="$(ssh_port_for_node "$node")"

  if ! tcp_probe "$node"; then
    log "ERROR" "$node tcp probe failed at $ip:$port"
    return 1
  fi

  if ! ssh_probe "$node"; then
    log "ERROR" "$node ssh probe failed at $ip:$port"
    return 1
  fi

  log "OK" "$node ssh probe passed at $ip:$port"
  return 0
}

main() {
  local node failures=0
  node="$(local_node)"
  log "INFO" "starting mesh health check as node=$node"

  check_tailscale || failures=$((failures + 1))

  if [[ "$node" != "unknown" ]]; then
    check_local_sshd "$node" || failures=$((failures + 1))
  else
    log "WARN" "unknown local Tailscale IP; skipping local sshd port inference"
  fi

  for target in m5 mbp cloud; do
    [[ "$target" == "$node" ]] && continue
    check_remote_node "$target" || failures=$((failures + 1))
  done

  if [[ "$failures" -eq 0 ]]; then
    log "OK" "mesh health check passed"
  else
    log "ERROR" "mesh health check finished with failures=$failures"
  fi

  return "$failures"
}

main "$@"
