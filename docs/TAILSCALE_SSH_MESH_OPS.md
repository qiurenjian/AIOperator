# Tailscale SSH Mesh Ops

目标：让 M5、MBP、cloud 三者 SSH 互联保持长期可用。这里不维持常驻 SSH 长连接，也不每分钟重建连接；只做每分钟一次的轻量探测，并在异常时尽快发现，能本地修复的再自动修复。

## 节点

| 节点 | Tailscale IP | SSH |
| --- | --- | --- |
| M5 | `100.127.88.43` | `renjianqiu@100.127.88.43:22` |
| MBP | `100.91.236.65` | `renjianqiu@100.91.236.65:22` |
| cloud | `100.72.54.102` | `root@100.72.54.102:28022` |

## 策略

1. Tailscale 是主网络，不依赖公网 IP 或家庭内网 IP。
2. SSH 不追求单条 session 永远不掉，使用 `ServerAliveInterval` 和 `ControlPersist` 降低交互断线概率。
3. 每台机器每 60 秒执行一次轻量探测 `scripts/mesh_healthcheck.sh`：
   - 检查本机 Tailscale 是否健康。
   - 检查本机 sshd 是否监听。
   - 从本机探测另外两台的 SSH TCP 端口。
   - 从本机实际执行一次 `ssh hostname`。
4. 只有探测发现本机 Tailscale 或 sshd 异常时，才尝试本地重启。
5. 远端不可达时只告警，不跨机器强修，避免误操作。

## 断电恢复模型

cloud 是 systemd 服务模型：机器重启后 `sshd`、`tailscaled` 和 `aiop-mesh-health.timer` 都应自动启动，恢复后自动重新进入探测状态。

M5 / MBP 是 macOS + 用户态 Tailscale 模型：

1. `sshd` 作为系统服务持久启用，开机后应自动可用。
2. `com.aioperator.mesh-health` 是用户 LaunchAgent，用户会话启动后自动开始每分钟探测。
3. Tailscale 需要配置为登录时启动；如果机器重启后停在登录界面且 Tailscale 没有后台模式，Tailnet 可能暂时不可达。
4. 长期无人值守的 MBP 需要接电，并设置接电不睡眠、网络唤醒、断电恢复后自动开机。
5. 如果关闭 Tailscale SSH，必须先确认标准 macOS sshd 已经在 22 端口监听，否则会把远程入口切断。

所以完整的“断电后自动恢复”依赖三层：

| 层 | 目标 | 配置 |
| --- | --- | --- |
| 电源 | 断电恢复后机器能开机 | `pmset autorestart 1`，MacBook 需确认硬件/系统是否支持 |
| 网络 | Tailscale 自动回来 | Tailscale 登录项/后台服务，cloud 上 `systemctl enable tailscaled` |
| SSH/探测 | sshd 与健康检查自动回来 | macOS `launchctl enable com.openssh.sshd` + LaunchAgent；cloud systemd timer |

## M5 / MBP 安装

在 M5 和 MBP 各执行一次：

```bash
cd /Users/renjianqiu/projects/AIOperator
scripts/install_mesh_autoreconnect_macos.sh
```

查看日志：

```bash
tail -f ~/Library/Logs/aiop-mesh-health.log
```

## cloud 安装

如果 cloud 上仓库路径不是 `/root/AIOperator`，先改 `ops/systemd/aiop-mesh-health.service` 的 `ExecStart`。

```bash
cd /root/AIOperator
scripts/install_mesh_autoreconnect_linux.sh
```

查看状态和日志：

```bash
systemctl list-timers aiop-mesh-health.timer
journalctl -u aiop-mesh-health.service -n 100 --no-pager
tail -f /var/log/aiop-mesh-health.log
```

## sudo 免密建议

脚本可以无 sudo 运行探测；自动修复 sshd/Tailscale 需要 sudo。如果不配置免密，脚本会记录 `sudo NOPASSWD may be required`，但不会卡住。

macOS 可用 `sudo visudo -f /etc/sudoers.d/aiop-mesh-health` 增加：

```sudoers
renjianqiu ALL=(root) NOPASSWD: /usr/sbin/sshd, /bin/launchctl
```

也可以在 M5 和 MBP 本机各执行一次：

```bash
cd /Users/renjianqiu/projects/AIOperator
scripts/install_mesh_sudoers_macos.sh
```

Linux cloud 可用 `visudo -f /etc/sudoers.d/aiop-mesh-health` 增加：

```sudoers
root ALL=(root) NOPASSWD: /bin/systemctl, /usr/bin/systemctl
```

## 手动验证

在任意节点：

```bash
scripts/mesh_healthcheck.sh
```

期望看到类似日志：

```text
[OK] tailscale status is healthy
[OK] local sshd is listening on port 22
[OK] mbp ssh probe passed at 100.91.236.65:22
[OK] cloud ssh probe passed at 100.72.54.102:28022
[OK] mesh health check passed
```

## 常见故障判断

`tcp probe failed`：Tailscale 路由、远端机器睡眠、远端 sshd 未监听或防火墙问题。

`ssh probe failed`：TCP 通，但密钥、用户、端口、known_hosts 或 Tailscale SSH ACL 有问题。

`local sshd is still down`：本机需要开启 Remote Login，或给脚本配置 sudo 免密。

Mac 合盖睡眠会让 SSH 不可达。长期作为节点使用的 MBP 建议接电源，并在系统设置中开启网络唤醒/防止接电源时睡眠；M5 如果经常移动，健康检查只能在它醒着并联网时保证可达。

## MBP 远程入口恢复

如果 MBP 在关闭 Tailscale SSH 后出现 `Connection refused`，说明标准 macOS sshd 没有接管 22 端口。需要在 MBP 本机终端执行：

```bash
sudo /usr/sbin/sshd -t
sudo launchctl enable system/com.openssh.sshd
sudo launchctl bootstrap system /System/Library/LaunchDaemons/ssh.plist 2>/dev/null || true
sudo launchctl kickstart -k system/com.openssh.sshd
sudo lsof -nP -iTCP:22 -sTCP:LISTEN
```

然后从 M5 验证：

```bash
ssh mbp hostname
ssh cloud-ts 'ssh -o BatchMode=yes -o ConnectTimeout=8 renjianqiu@100.91.236.65 hostname'
```

## 断电恢复验收

每个节点重启后分别检查：

M5 / MBP：

```bash
launchctl list | grep com.aioperator.mesh-health
launchctl print system/com.openssh.sshd | grep -E "state|pid" || true
/Applications/Tailscale.app/Contents/MacOS/Tailscale status
tail -n 20 ~/Library/Logs/aiop-mesh-health.log
```

cloud：

```bash
systemctl is-enabled sshd 2>/dev/null || systemctl is-enabled ssh
systemctl is-enabled tailscaled
systemctl is-enabled aiop-mesh-health.timer
systemctl list-timers aiop-mesh-health.timer
tail -n 20 /var/log/aiop-mesh-health.log
```

从任一节点验证互通：

```bash
ssh mbp hostname
ssh m5 hostname
ssh cloud-ts hostname
```
