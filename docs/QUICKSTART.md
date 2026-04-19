# AIOperator 快速上手指南

## 目录
1. [系统架构概览](#系统架构概览)
2. [环境准备](#环境准备)
3. [完整链路演示](#完整链路演示)
4. [核心组件详解](#核心组件详解)
5. [故障排查](#故障排查)

---

## 系统架构概览

```
飞书用户
  ↓ @机器人 + 卡片交互
飞书开放平台
  ↓ webhook
Ingress (8000端口)
  ↓ 解析事件
Orchestrator
  ↓ 启动 Temporal Workflow
Temporal Server (7233端口)
  ↓ 调度 Activity
Worker (本地/云端)
  ↓ 执行 CLI
Claude CLI / Codex CLI
  ↓ 返回结果
Bitable 数据表 (记录状态)
  ↓ webhook 触发
下一个 Phase
```

**关键节点**：
- **飞书**: 用户界面 + 数据存储
- **Temporal**: 工作流引擎（处理长时任务、重试、超时）
- **Worker**: 执行环境（MBP/M5/云端分工）
- **CLI**: LLM 调用层（Claude Code/Codex）

---

## 环境准备

### 1. 云端环境（43.162.125.16:28022）

```bash
# SSH 登录
ssh -p 28022 ubuntu@43.162.125.16

# 检查服务状态
cd /path/to/AIOperator
docker-compose -f deploy/docker-compose.yml ps

# 预期输出：
# postgres         Up (healthy)
# temporal-server  Up (healthy)
# temporal-ui      Up (0.0.0.0:8080->8080/tcp)
# ingress          Up (0.0.0.0:8000->8000/tcp)
# worker-cloud     Up
```

### 2. 本地环境（M5）

```bash
cd /Users/renjianqiu/projects/AIOperator

# 检查 CLI 工具
claude --version  # 应显示 2.1.88+
codex --version   # 应显示 0.121.0+

# 检查登录状态
claude auth status
codex auth status

# 启动本地 worker（如需要）
docker-compose -f deploy/workers/m5.compose.yml up -d
```

### 3. 环境变量检查

```bash
# 云端
cat deploy/.env.cloud | grep -E "FEISHU_|BITABLE_|ANTHROPIC_"

# 本地（如需要）
cat deploy/workers/.env.m5 | grep -E "TEMPORAL_|NODE_ID"
```

---

## 完整链路演示

### 场景：用户在飞书发起 P0 需求

#### Step 1: 用户操作
```
飞书群聊中：
@AIOperator 帮我实现登录页面的记住密码功能

附加信息：
- 项目：HealthAssist iOS
- 优先级：P0
- 截止日期：2026-04-15
```

#### Step 2: 飞书 → Ingress
```bash
# 飞书发送 POST 请求到：
# https://your-domain.com/feishu/message

# Ingress 日志（查看方式）：
docker logs ingress -f --tail 100

# 预期日志：
# [INFO] Received message event: user_id=ou_xxx, text="@AIOperator 帮我..."
# [INFO] Extracted intent: type=feature_request, project=HealthAssist
# [INFO] Creating Bitable record...
# [INFO] Record created: record_id=recXXX
```

#### Step 3: Orchestrator → Temporal
```bash
# Temporal UI 查看（浏览器访问）：
# http://43.162.125.16:8080

# 导航路径：
# Workflows → 搜索 "recXXX" → 点击 Workflow ID

# 预期状态：
# Status: Running
# Current Activity: p0_confirm (Phase 0)
```

#### Step 4: Worker 执行 Claude CLI
```bash
# Worker 日志（云端）：
docker logs worker-cloud -f --tail 100

# 预期日志：
# [INFO] Activity started: p0_confirm, record_id=recXXX
# [INFO] Executing: claude -p /path/to/project --headless --output-format json ...
# [INFO] Claude response: {"total_cost_usd": 0.05, "usage": {...}}
# [INFO] Parsed P0 confirmation: estimated_hours=8, risks=[...]
```

#### Step 5: 飞书卡片发送
```
用户收到飞书卡片：

┌─────────────────────────────────┐
│ 📋 P0 需求确认                    │
├─────────────────────────────────┤
│ 需求：登录页面记住密码功能          │
│ 预估工时：8 小时                   │
│ 风险点：                          │
│ • 需要 Keychain 权限              │
│ • iOS 15+ 兼容性测试              │
├─────────────────────────────────┤
│ [✅ 确认执行]  [❌ 拒绝]  [✏️ 修改] │
└─────────────────────────────────┘
```

#### Step 6: 用户点击"确认执行"
```bash
# 飞书发送 POST 到：
# https://your-domain.com/feishu/card_action

# Ingress 解析 button value：
{
  "record_id": "recXXX",
  "signal": "p0_approved",
  "user_id": "ou_xxx"
}

# Temporal 接收 Signal：
# Workflow "recXXX" → Signal "p0_approved" → 进入 Phase 1
```

#### Step 7: Phase 1 - 技术方案设计
```bash
# Worker 执行 claude_plan activity
# 输出：docs/design/recXXX_login_remember.md

# Bitable 更新：
# current_phase: phase_1_plan
# plan_doc_url: https://...
# status: pending_approval
```

#### Step 8: Phase 1 审批卡片
```
用户收到新卡片：

┌─────────────────────────────────┐
│ 📐 技术方案审批                    │
├─────────────────────────────────┤
│ 方案文档：[查看详情]               │
│ 关键决策：                        │
│ • 使用 Keychain Services API     │
│ • 添加生物识别二次验证             │
│ • 数据加密存储                    │
├─────────────────────────────────┤
│ [✅ 批准]  [❌ 驳回]  [💬 讨论]    │
└─────────────────────────────────┘
```

#### Step 9: 后续 Phase 自动执行
```
Phase 2: codex_implement → 生成代码
Phase 3: git_commit → 提交到分支
Phase 4: ci_test → 触发 CI 流水线
Phase 5: release_build → 打包 TestFlight
Phase 6: 人工验收 → 用户测试
Phase 7: git_merge → 合并到 main
```

---

## 核心组件详解

### 1. Bitable 数据表操作

#### 查看所有记录
```bash
# 使用飞书 API
curl -X POST "https://open.feishu.cn/open-api/bitable/v1/apps/${BITABLE_APP_TOKEN}/tables/${BITABLE_TABLE_ID}/records/search" \
  -H "Authorization: Bearer $(get_tenant_access_token)" \
  -H "Content-Type: application/json" \
  -d '{
    "view_id": "vewP0Kanban",
    "page_size": 20
  }'
```

#### 手动更新记录状态
```bash
curl -X PUT "https://open.feishu.cn/open-api/bitable/v1/apps/${BITABLE_APP_TOKEN}/tables/${BITABLE_TABLE_ID}/records/${RECORD_ID}" \
  -H "Authorization: Bearer $(get_tenant_access_token)" \
  -H "Content-Type: application/json" \
  -d '{
    "fields": {
      "status": "in_progress",
      "current_phase": "phase_2_implement"
    }
  }'
```

### 2. Temporal Workflow 操作

#### 查询 Workflow 状态
```bash
# 使用 tctl（需在云端安装）
tctl workflow describe -w <workflow_id>

# 或通过 Web UI：
# http://43.162.125.16:8080/namespaces/default/workflows/<workflow_id>
```

#### 手动发送 Signal
```bash
tctl workflow signal -w <workflow_id> -n p0_approved -i '{"user_id":"ou_xxx"}'
```

#### 取消 Workflow
```bash
tctl workflow cancel -w <workflow_id> --reason "用户取消"
```

### 3. CLI 调用示例

#### Claude CLI（技术方案设计）
```bash
claude \
  -p /path/to/HealthAssist \
  --headless \
  --output-format json \
  --max-turns 5 \
  --prompt "根据需求文档 requirements.md 设计技术方案，输出 Markdown 格式" \
  > output.json

# 解析结果
jq '.total_cost_usd' output.json  # 成本
jq '.usage.output_tokens' output.json  # Token 数
```

#### Codex CLI（代码实现）
```bash
codex exec \
  --cwd /path/to/HealthAssist \
  --non-interactive \
  --output-format jsonl \
  "实现 LoginViewController 的记住密码功能，使用 Keychain 存储" \
  > output.jsonl

# 解析事件流
cat output.jsonl | jq -s 'map(select(.type=="completion"))'
```

### 4. 飞书卡片发送

#### 发送 P0 确认卡片
```bash
curl -X POST "https://open.feishu.cn/open-api/im/v1/messages" \
  -H "Authorization: Bearer $(get_tenant_access_token)" \
  -H "Content-Type: application/json" \
  -d '{
    "receive_id": "ou_xxx",
    "msg_type": "interactive",
    "content": "{\"type\":\"template\",\"data\":{\"template_id\":\"ctp_xxx\",\"template_variable\":{\"record_id\":\"recXXX\",\"requirement\":\"登录记住密码\",\"estimated_hours\":\"8\"}}}"
  }'
```

---

## 故障排查

### 问题 1: Ingress 收不到飞书 webhook

**症状**：用户 @机器人 后无响应

**排查步骤**：
```bash
# 1. 检查 Ingress 是否运行
docker ps | grep ingress

# 2. 检查端口监听
netstat -tlnp | grep 8000

# 3. 检查飞书 webhook 配置
# 登录 https://open.feishu.cn/app
# 进入应用 → 事件订阅 → 查看回调 URL

# 4. 测试公网连通性
curl -X POST https://your-domain.com/feishu/message \
  -H "Content-Type: application/json" \
  -d '{"test": true}'
```

**解决方案**：
- 确认域名 DNS 解析正确
- 检查防火墙规则（开放 8000 端口）
- 验证飞书 IP 白名单

### 问题 2: Worker 无法连接 Temporal

**症状**：Worker 日志显示 "connection refused"

**排查步骤**：
```bash
# 1. 检查 Temporal Server 状态
docker logs temporal-server --tail 50

# 2. 测试网络连通性
telnet 43.162.125.16 7233

# 3. 检查 Worker 配置
cat deploy/workers/m5.compose.yml | grep TEMPORAL_HOST
```

**解决方案**：
- 确认 `TEMPORAL_HOST_PORT=43.162.125.16:7233`
- 检查云端防火墙（开放 7233 端口）
- 验证 Worker 网络模式（host 或 bridge）

### 问题 3: Claude CLI 返回 401 Unauthorized

**症状**：Activity 执行失败，日志显示认证错误

**排查步骤**：
```bash
# 1. 检查登录状态
claude auth status

# 2. 重新登录
claude auth login

# 3. 测试 API 连通性（使用代理）
curl -X POST https://cc-vibe.com/v1/messages \
  -H "x-api-key: ${ANTHROPIC_API_KEY}" \
  -H "anthropic-version: 2023-06-01" \
  -d '{"model":"claude-opus-4","max_tokens":100,"messages":[{"role":"user","content":"test"}]}'
```

**解决方案**：
- 确认 `.env.cloud` 中 `ANTHROPIC_BASE_URL` 和 `ANTHROPIC_API_KEY` 正确
- 检查代理服务器状态
- 验证 API key 有效期

### 问题 4: Bitable webhook 未触发

**症状**：Phase 审批后 Workflow 未继续

**排查步骤**：
```bash
# 1. 检查 webhook 配置
# 飞书开放平台 → 多维表格 → 事件订阅

# 2. 查看 Ingress 日志
docker logs ingress | grep "/bitable/webhook"

# 3. 手动触发 Signal（绕过 webhook）
tctl workflow signal -w <workflow_id> -n phase_1_approved
```

**解决方案**：
- 确认 webhook URL 配置为 `https://your-domain.com/bitable/webhook`
- 检查 Bitable 表的"更改订阅"设置
- 验证 `verification_token` 匹配

### 问题 5: Codex CLI 输出解析失败

**症状**：`codex_implement` activity 报错 "invalid JSON"

**排查步骤**：
```bash
# 1. 手动执行 Codex CLI
codex exec --non-interactive --output-format jsonl "test" > test.jsonl

# 2. 检查输出格式
cat test.jsonl | jq .

# 3. 查看 Worker 解析逻辑
# activities/codex/implement.py → parse_jsonl_output()
```

**解决方案**：
- 确认 Codex CLI 版本 >= 0.121.0
- 使用 `--output-format jsonl`（不是 `json`）
- 逐行解析 JSONL（不要用 `json.load()`）

---

## 快速验证清单

### 端到端测试（5 分钟）

```bash
# 1. 云端服务健康检查
ssh -p 28022 ubuntu@43.162.125.16 "docker-compose -f /path/to/AIOperator/deploy/docker-compose.yml ps"

# 2. 本地 CLI 测试
claude --version && codex --version

# 3. 飞书 API 测试
curl -X POST "https://open.feishu.cn/open-api/auth/v3/tenant_access_token/internal" \
  -H "Content-Type: application/json" \
  -d "{\"app_id\":\"${FEISHU_APP_ID}\",\"app_secret\":\"${FEISHU_APP_SECRET}\"}"

# 4. Bitable 读取测试
# （使用上面获取的 tenant_access_token）
curl -X POST "https://open.feishu.cn/open-api/bitable/v1/apps/${BITABLE_APP_TOKEN}/tables/${BITABLE_TABLE_ID}/records/search" \
  -H "Authorization: Bearer <token>" \
  -d '{"page_size":1}'

# 5. Temporal UI 访问
# 浏览器打开：http://43.162.125.16:8080
```

**预期结果**：
- ✅ 所有 Docker 容器状态为 `Up (healthy)`
- ✅ Claude CLI 和 Codex CLI 版本正确
- ✅ 飞书 API 返回 `tenant_access_token`
- ✅ Bitable API 返回记录列表
- ✅ Temporal UI 显示 Workflows 列表

---

## 下一步

1. **Week 1 开发**：实现 Ingress 和 Orchestrator
2. **集成测试**：端到端链路验证
3. **监控配置**：Grafana + Prometheus
4. **文档完善**：API 文档 + Runbook

**参考文档**：
- [架构设计](ARCHITECTURE_v2.md)
- [CLI 调用规范](cli_contracts.md)
- [Bitable Schema](bitable_schema.md)
- [飞书卡片定义](feishu_cards.md)
