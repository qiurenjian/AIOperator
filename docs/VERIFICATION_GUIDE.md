# 多阶段对话系统验证指南

## 系统架构概览

```
用户（飞书）
    ↓
feishu-connector (WebSocket 长连接)
    ↓
SessionManager (会话状态管理)
    ↓
ConversationContext (阶段状态机)
    ↓
├─ REQUIREMENT_CLARIFYING → requirement_clarifier.py
├─ REQUIREMENT_CONFIRMED → 启动 Workflow
├─ PRD_REVIEW → prd_reviewer.py
└─ 状态查询 → status_query.py
    ↓
Temporal Workflow (RequirementWorkflow)
    ↓
Git Commit (PRD 入库)
```

## 前置检查

### 1. 检查服务状态

```bash
cd /Users/renjianqiu/projects/AIOperator/deploy

# 启动所有服务
docker compose --env-file ../.env.cloud up -d

# 检查服务状态
docker compose ps

# 预期输出：
# aiop-postgres          running
# aiop-temporal          running (healthy)
# aiop-temporal-ui       running
# aiop-ingress           running
# aiop-worker-cloud      running
# aiop-feishu-connector  running
```

### 2. 检查日志

```bash
# 查看 feishu-connector 启动日志
docker compose logs feishu-connector | tail -20

# 预期看到：
# [INFO] starting feishu connector...
# [INFO] app_id: cli_xxxxx
# [INFO] feishu connector started, waiting for events...

# 查看 worker 启动日志
docker compose logs worker-cloud | tail -20

# 预期看到：
# [INFO] worker started, task_queues=['lite', 'llm-cloud', 'git-ops']
```

### 3. 检查 Temporal UI

访问：http://localhost:8088

- 确认可以访问
- 检查 namespace: `aioperator`
- 查看是否有历史 workflow

## 验证场景

### 场景 1：需求澄清流程（REQUIREMENT_CLARIFYING）

#### 步骤 1：发送初步需求

**在飞书中发送：**
```
我想在健康助手里加一个运动记录功能
```

**预期行为：**
1. feishu-connector 收到消息
2. 意图分类识别为 `REQUIREMENT`
3. 会话进入 `REQUIREMENT_CLARIFYING` 阶段
4. AI 回复澄清问题

**验证命令：**
```bash
# 查看意图分类日志
docker compose logs feishu-connector | grep "classified intent"
# 预期：classified intent: REQUIREMENT (0.85)

# 查看阶段变化
docker compose logs feishu-connector | grep "phase"
# 预期：update_phase: IDLE -> REQUIREMENT_CLARIFYING
```

**预期 AI 回复示例：**
```
好的，我来帮你完善这个需求。请问：
1. 你想记录哪些类型的运动？（跑步、骑行、游泳等）
2. 需要记录哪些数据？（距离、时间、心率等）
```

#### 步骤 2：补充需求信息

**在飞书中发送：**
```
主要是跑步和骑行，记录距离、时间、消耗的卡路里
```

**预期行为：**
1. 继续澄清对话
2. AI 判断需求是否足够清晰
3. 如果足够清晰，进入 `REQUIREMENT_CONFIRMED` 阶段

**验证命令：**
```bash
# 查看澄清结果
docker compose logs feishu-connector | grep "clarification result"
# 预期：clarification result: is_ready=True, confidence=0.90
```

**预期 AI 回复示例：**
```
明白了。你想要一个运动记录功能，支持：
- 运动类型：跑步、骑行
- 记录数据：距离、时间、卡路里消耗

✅ 需求已明确。是否开始生成 PRD？（回复「确认」或「开始」）
```

#### 步骤 3：确认启动 Workflow

**在飞书中发送：**
```
确认
```

**预期行为：**
1. 启动 RequirementWorkflow
2. 会话进入 `PRD_REVIEW` 阶段
3. Workflow 开始 P0 需求捕获

**验证命令：**
```bash
# 查看 workflow 启动日志
docker compose logs feishu-connector | grep "started workflow"
# 预期：started workflow req-chat-xxx-msg-xxx for requirement

# 在 Temporal UI 查看
# 访问 http://localhost:8088
# 应该看到新的 workflow 实例
```

**预期 AI 回复：**
```
✅ 已启动 PRD 生成流程，请稍候...
```

### 场景 2：PRD 审查流程（PRD_REVIEW）

#### 步骤 4：等待 PRD 生成

**预期行为：**
1. Workflow 执行 P0 阶段（需求捕获）
2. 发送需求捕获卡片（带确认按钮）
3. 点击「进入 P1」按钮
4. Workflow 执行 P1 阶段（生成 PRD）
5. 发送 PRD 卡片
6. 会话自动同步到 `PRD_REVIEW` 阶段

**验证命令：**
```bash
# 查看 workflow 进度
docker compose logs worker-cloud | grep "phase"
# 预期：current_phase: P0 -> P1

# 查看状态同步
docker compose logs feishu-connector | grep "synced workflow state"
# 预期：synced workflow state: phase=P1 -> PRD_REVIEW
```

**预期卡片内容：**
```
📝 PRD 已生成 · req-xxx

摘要：运动记录功能
验收条件：5 条

[✅ 批准并入库] [❌ 拒绝]
```

#### 步骤 5：提问和讨论

**在飞书中发送：**
```
这个功能需要 GPS 定位吗？
```

**预期行为：**
1. 系统识别为 PRD 审查对话
2. AI 基于 PRD 内容回答
3. 保持在 `PRD_REVIEW` 阶段

**验证命令：**
```bash
# 查看审查日志
docker compose logs feishu-connector | grep "prd review result"
# 预期：prd review result: action=discuss, confidence=0.85
```

**预期 AI 回复示例：**
```
根据当前 PRD，这个功能暂时不需要 GPS 定位。用户手动输入距离和时间即可。

如果未来需要自动记录运动轨迹，可以在后续版本中添加 GPS 功能。

还有其他问题吗？
```

#### 步骤 6：批准 PRD

**在飞书中发送：**
```
看起来不错，批准
```

**预期行为：**
1. AI 识别为批准意图
2. 发送 `p1_approve` 信号到 workflow
3. Workflow 提交 PRD 到 Git
4. 发送提交成功卡片

**验证命令：**
```bash
# 查看信号发送
docker compose logs feishu-connector | grep "sent.*signal"
# 预期：sent p1_approve signal to workflow req-xxx

# 查看 Git 提交
docker compose logs worker-cloud | grep "git commit"
# 预期：git commit success: sha=abc123...
```

**预期卡片内容：**
```
🚀 PRD 已入库 · req-xxx

提交：abc123
下一步：等待 P2 设计阶段（Week 1 Day 2 启用）。
```

#### 步骤 7：拒绝 PRD（可选测试）

**在飞书中发送：**
```
这个不行，需要重新做
```

**预期行为：**
1. AI 识别为拒绝意图
2. 发送 `p1_reject` 信号到 workflow
3. Workflow 取消
4. 会话回到 `IDLE` 状态

**验证命令：**
```bash
# 查看信号发送
docker compose logs feishu-connector | grep "sent.*signal"
# 预期：sent p1_reject signal to workflow req-xxx

# 查看 workflow 状态
# 在 Temporal UI 中应该看到 lifecycle_state: cancelled
```

### 场景 3：状态查询（任意阶段）

#### 查询当前状态

**在飞书中发送：**
```
当前状态
```
或
```
进度怎么样了
```
或
```
到哪了
```

**预期行为：**
1. 系统识别为状态查询
2. 查询会话和 workflow 状态
3. 返回格式化的状态信息

**验证命令：**
```bash
# 查看查询日志
docker compose logs feishu-connector | grep "query.*status"
```

**预期 AI 回复示例：**
```
📊 **当前状态**：PRD 审查中
🔄 **Workflow ID**：`req-chat-456-msg-789`
📝 **需求 ID**：`req-msg-789`
⚙️ **Workflow 阶段**：P1
🏷️ **生命周期**：in_progress
💰 **已用成本**：$0.0234
⏱️ **会话时长**：5.3 分钟
```

#### 查询特定 Workflow

**在飞书中发送：**
```
req-chat-456-msg-789
```

**预期行为：**
1. 系统识别为 workflow ID
2. 查询该 workflow 的详细状态
3. 返回详细信息

**预期 AI 回复示例：**
```
🔄 **Workflow ID**：`req-chat-456-msg-789`
⚙️ **阶段**：P1
🏷️ **生命周期**：in_progress
💰 **已用成本**：$0.0234

📥 **需求捕获**：
  - 摘要：运动记录功能
  - 风险：low

📄 **PRD**：`docs/PRDs/req-msg-789.md`
```

## 边界情况测试

### 测试 1：中途修改需求

```
1. 发送："加个用户登录功能"
2. AI 澄清："需要支持哪些登录方式？"
3. 回复："不对，我想要的是注册功能"
4. 验证：系统继续澄清，不启动 workflow
```

### 测试 2：多轮澄清

```
1. 发送模糊需求："优化性能"
2. AI 追问："哪个模块的性能？"
3. 回复："首页加载"
4. AI 追问："目标是什么？"
5. 回复："3秒内加载完成"
6. 验证：经过多轮澄清后才确认需求
```

### 测试 3：会话超时

```
1. 发送需求并澄清
2. 等待 2 小时以上
3. 再次发送消息
4. 验证：会话可能被清理（当前实现 2 小时超时）
```

### 测试 4：多会话隔离

```
1. 在飞书群 A 发送需求 A
2. 在飞书群 B 发送需求 B
3. 在群 A 查询状态
4. 验证：只看到需求 A 的状态
```

## 日志分析

### 关键日志模式

```bash
# 1. 意图分类
docker compose logs feishu-connector | grep "classified intent"
# 输出格式：classified intent: REQUIREMENT (0.85)

# 2. 阶段变化
docker compose logs feishu-connector | grep "update_phase"
# 输出格式：update_phase: IDLE -> REQUIREMENT_CLARIFYING

# 3. 需求澄清
docker compose logs feishu-connector | grep "clarification result"
# 输出格式：clarification result: is_ready=True, confidence=0.90

# 4. PRD 审查
docker compose logs feishu-connector | grep "prd review result"
# 输出格式：prd review result: action=approve, confidence=0.95

# 5. Workflow 启动
docker compose logs feishu-connector | grep "started workflow"
# 输出格式：started workflow req-chat-456-msg-789 for requirement

# 6. 信号发送
docker compose logs feishu-connector | grep "sent.*signal"
# 输出格式：sent p1_approve signal to workflow req-xxx

# 7. 状态同步
docker compose logs feishu-connector | grep "synced workflow state"
# 输出格式：synced workflow state: phase=P1 -> PRD_REVIEW
```

### 完整流程日志示例

```
[INFO] received message from user-123 in chat-456: 我想加个运动记录功能
[INFO] classified intent: REQUIREMENT (0.85)
[INFO] update_phase: IDLE -> REQUIREMENT_CLARIFYING
[INFO] clarification result: is_ready=False, confidence=0.60
[INFO] sent message to chat-456

[INFO] received message from user-123 in chat-456: 记录跑步和骑行
[INFO] clarification result: is_ready=True, confidence=0.90
[INFO] update_phase: REQUIREMENT_CLARIFYING -> REQUIREMENT_CONFIRMED
[INFO] sent message to chat-456

[INFO] received message from user-123 in chat-456: 确认
[INFO] started workflow req-chat-456-msg-789 for requirement
[INFO] update_phase: REQUIREMENT_CONFIRMED -> PRD_REVIEW
[INFO] sent message to chat-456

[INFO] workflow state synced for chat_id=chat-456
[INFO] synced workflow state: phase=P1 -> PRD_REVIEW

[INFO] received message from user-123 in chat-456: 批准
[INFO] prd review result: action=approve, confidence=0.95
[INFO] sent p1_approve signal to workflow req-chat-456-msg-789
[INFO] update_phase: PRD_REVIEW -> DESIGN_DISCUSSION
```

## 故障排查

### 问题 1：发送消息没反应

**症状：**
- 在飞书发送消息，没有任何回复

**排查步骤：**
```bash
# 1. 检查 feishu-connector 是否运行
docker compose ps feishu-connector
# 应该显示 running

# 2. 查看最近日志
docker compose logs --tail=50 feishu-connector
# 查找错误信息

# 3. 检查飞书 WebSocket 连接
docker compose logs feishu-connector | grep "feishu connector started"
# 应该看到启动成功日志

# 4. 检查飞书配置
docker compose exec feishu-connector env | grep FEISHU
# 确认 app_id, app_secret 等配置正确
```

### 问题 2：Workflow 没有启动

**症状：**
- 确认需求后，没有启动 workflow

**排查步骤：**
```bash
# 1. 检查 Temporal 服务
docker compose ps temporal
# 应该显示 healthy

# 2. 检查 worker 是否在线
docker compose logs worker-cloud | grep "worker started"

# 3. 查看 Temporal UI
# 访问 http://localhost:8088
# 检查是否有 workflow 实例

# 4. 查看错误日志
docker compose logs feishu-connector | grep -i error
docker compose logs worker-cloud | grep -i error
```

### 问题 3：PRD 审查阶段无法进入

**症状：**
- Workflow 生成 PRD 后，会话没有进入 PRD_REVIEW 阶段

**排查步骤：**
```bash
# 1. 检查 workflow 状态
# 在 Temporal UI 查看 workflow 是否在 P1 阶段

# 2. 检查状态同步
docker compose logs feishu-connector | grep "sync_workflow_to_session"

# 3. 手动触发同步
# 在飞书发送任意消息，会触发状态同步

# 4. 查看会话状态
docker compose logs feishu-connector | grep "phase"
```

### 问题 4：状态查询返回错误

**症状：**
- 发送「状态」后，返回错误信息

**排查步骤：**
```bash
# 1. 检查 workflow 是否存在
# 在 Temporal UI 查看 workflow 列表

# 2. 检查 query 是否支持
docker compose logs worker-cloud | grep "query.*status"

# 3. 查看错误详情
docker compose logs feishu-connector | grep "failed to query"
```

## 性能监控

### 关键指标

```bash
# 1. 响应时间
docker compose logs feishu-connector | grep "response_time"

# 2. Claude API 调用成本
docker compose logs worker-cloud | grep "cost_usd"

# 3. 内存使用
docker stats --no-stream

# 4. Workflow 执行时间
# 在 Temporal UI 查看 workflow 执行历史
```

### 资源限制

根据 docker-compose.yml 配置：
- postgres: 512MB
- temporal: 768MB
- temporal-ui: 128MB
- ingress: 320MB
- worker-cloud: 1024MB
- feishu-connector: 256MB

总计：~3GB（适合 3.6GB RAM 的云服务器）

## 下一步

### 已实现功能
- ✅ 需求澄清对话（多轮）
- ✅ 需求确认和 workflow 启动
- ✅ PRD 审查对话
- ✅ 状态查询
- ✅ Workflow 状态同步

### 待实现功能（Week 1）
- ⏳ 技术方案讨论阶段（DESIGN_DISCUSSION）
- ⏳ 实现阶段（IMPLEMENTATION）
- ⏳ 代码审查阶段（CODE_REVIEW）
- ⏳ PRD 修改和迭代
- ⏳ 会话持久化（当前是内存存储）

## 联系方式

如有问题，请查看：
- GitHub Issues: https://github.com/qiurenjian/AIOperator/issues
- 项目文档: /Users/renjianqiu/projects/AIOperator/docs/
