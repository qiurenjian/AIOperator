# 多阶段对话系统 - 快速测试清单

## 🚀 快速开始

### 1. 启动系统

```bash
cd /Users/renjianqiu/projects/AIOperator/deploy
docker compose --env-file ../.env.cloud up -d
```

### 2. 运行检查脚本

```bash
cd /Users/renjianqiu/projects/AIOperator
./scripts/check_conversation_system.sh
```

### 3. 查看实时日志

```bash
cd /Users/renjianqiu/projects/AIOperator/deploy
docker compose logs -f feishu-connector
```

## ✅ 测试清单

### 测试 1：需求澄清（5 分钟）

- [ ] 在飞书发送：`我想在健康助手里加一个运动记录功能`
- [ ] 验证：收到澄清问题（例如："你想记录哪些类型的运动？"）
- [ ] 回复：`主要是跑步和骑行，记录距离、时间、消耗的卡路里`
- [ ] 验证：收到确认提示（"✅ 需求已明确。是否开始生成 PRD？"）
- [ ] 回复：`确认`
- [ ] 验证：收到启动消息（"✅ 已启动 PRD 生成流程，请稍候..."）

**日志验证：**
```bash
docker compose logs feishu-connector | grep "classified intent"
docker compose logs feishu-connector | grep "clarification result"
docker compose logs feishu-connector | grep "started workflow"
```

### 测试 2：PRD 审查（10 分钟）

- [ ] 等待收到需求捕获卡片（蓝色卡片，显示摘要、用户故事、验收提示）
- [ ] 点击卡片上的「进入 P1（生成 PRD）」按钮
- [ ] 等待收到 PRD 卡片（绿色卡片，显示摘要、验收条件数量）
- [ ] 在飞书发送：`这个功能需要 GPS 定位吗？`
- [ ] 验证：收到基于 PRD 的回答
- [ ] 在飞书发送：`看起来不错，批准`
- [ ] 验证：收到批准确认和 Git 提交卡片（青色卡片）

**日志验证：**
```bash
docker compose logs feishu-connector | grep "prd review result"
docker compose logs feishu-connector | grep "sent.*signal"
docker compose logs worker-cloud | grep "git commit"
```

**Temporal UI 验证：**
- 访问 http://localhost:8088
- 找到对应的 workflow
- 查看执行历史，应该看到：
  - P0 阶段完成
  - P1 阶段完成
  - lifecycle_state: approved

### 测试 3：状态查询（2 分钟）

- [ ] 在任意阶段发送：`当前状态`
- [ ] 验证：收到格式化的状态信息，包含：
  - 当前阶段
  - Workflow ID
  - 需求 ID
  - 成本信息
  - 会话时长

**日志验证：**
```bash
docker compose logs feishu-connector | grep "query.*status"
```

### 测试 4：拒绝 PRD（可选，5 分钟）

- [ ] 重新发起一个需求
- [ ] 完成需求澄清并启动 workflow
- [ ] 收到 PRD 卡片后，发送：`这个不行，需要重新做`
- [ ] 验证：收到拒绝确认
- [ ] 验证：workflow 被取消

**日志验证：**
```bash
docker compose logs feishu-connector | grep "p1_reject"
```

## 📊 验证结果

### 成功标准

- ✅ 所有服务正常运行
- ✅ 能够完成需求澄清对话
- ✅ 能够启动 workflow
- ✅ 能够审查和批准 PRD
- ✅ PRD 成功提交到 Git
- ✅ 状态查询返回正确信息

### 关键日志模式

**意图分类：**
```
[INFO] classified intent: REQUIREMENT (0.85)
```

**阶段变化：**
```
[INFO] update_phase: IDLE -> REQUIREMENT_CLARIFYING
[INFO] update_phase: REQUIREMENT_CLARIFYING -> REQUIREMENT_CONFIRMED
[INFO] update_phase: REQUIREMENT_CONFIRMED -> PRD_REVIEW
```

**需求澄清：**
```
[INFO] clarification result: is_ready=True, confidence=0.90
```

**PRD 审查：**
```
[INFO] prd review result: action=approve, confidence=0.95
```

**Workflow 操作：**
```
[INFO] started workflow req-chat-456-msg-789 for requirement
[INFO] sent p1_approve signal to workflow req-xxx
```

**状态同步：**
```
[INFO] synced workflow state: phase=P1 -> PRD_REVIEW
```

## 🐛 常见问题

### 问题：发送消息没反应

**解决方案：**
```bash
# 1. 检查 feishu-connector 状态
docker compose ps feishu-connector

# 2. 查看日志
docker compose logs --tail=50 feishu-connector

# 3. 重启服务
docker compose restart feishu-connector
```

### 问题：Workflow 没有启动

**解决方案：**
```bash
# 1. 检查 Temporal 服务
docker compose ps temporal

# 2. 检查 worker
docker compose ps worker-cloud

# 3. 查看 Temporal UI
# 访问 http://localhost:8088
```

### 问题：PRD 审查阶段无法进入

**解决方案：**
```bash
# 1. 发送任意消息触发状态同步
# 在飞书发送："状态"

# 2. 查看同步日志
docker compose logs feishu-connector | grep "sync_workflow"
```

## 📝 测试记录

### 测试日期：________

| 测试项 | 状态 | 备注 |
|--------|------|------|
| 需求澄清 | ⬜ 通过 / ⬜ 失败 | |
| PRD 审查 | ⬜ 通过 / ⬜ 失败 | |
| 状态查询 | ⬜ 通过 / ⬜ 失败 | |
| 拒绝 PRD | ⬜ 通过 / ⬜ 失败 | |

### 发现的问题：

1. 
2. 
3. 

### 改进建议：

1. 
2. 
3. 

## 📚 相关文档

- 详细验证指南：[docs/VERIFICATION_GUIDE.md](../docs/VERIFICATION_GUIDE.md)
- 系统架构：[docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md)
- API 文档：[docs/API.md](../docs/API.md)

## 🎯 下一步

完成测试后，可以：

1. **查看 Git 提交**
   ```bash
   cd /path/to/HealthAssit
   git log --oneline -5
   cat docs/PRDs/req-xxx.md
   ```

2. **查看成本统计**
   ```bash
   docker compose logs worker-cloud | grep "cost_usd"
   ```

3. **导出测试数据**
   ```bash
   # 导出 Temporal workflow 历史
   # 在 Temporal UI 中下载 workflow 执行历史
   ```

4. **准备生产部署**
   - 配置持久化存储
   - 设置监控告警
   - 优化资源配置
