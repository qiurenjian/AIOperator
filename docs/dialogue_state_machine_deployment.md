# 对话状态机部署指南

## 概述

对话状态机已完成开发和测试，本文档说明如何部署到生产环境。

## 已完成的工作

### 1. 核心模块
- `apps/ingress/dialogue_state.py` - 状态定义和数据结构
- `apps/ingress/dialogue_manager.py` - 状态管理器
- `apps/ingress/intent_analyzer.py` - 增强意图识别
- `apps/ingress/confirmation_handler.py` - 确认处理
- `apps/ingress/session_manager.py` - Session扩展

### 2. 集成点
- `apps/feishu_connector/main.py` - 已集成DialogueStateManager

### 3. 测试
- `test_dialogue_flow.py` - 集成测试（已通过）

## 部署步骤

### 1. 环境准备

确保已安装所有依赖：
```bash
pip install -r requirements.txt
```

关键依赖：
- anthropic >= 0.40.0 (用于Claude API调用)
- 其他现有依赖

### 2. 环境变量

确保配置了以下环境变量：
```bash
# Claude API密钥（用于意图识别和澄清）
ANTHROPIC_API_KEY=your_api_key_here

# 数据库连接（已有）
DATABASE_URL=postgresql://...

# 飞书配置（已有）
FEISHU_APP_ID=...
FEISHU_APP_SECRET=...
```

### 3. 数据库迁移

Session表已扩展，需要确保数据库schema包含新字段：
- dialogue_state (默认: "idle")
- requirement_draft (JSON, 可选)
- clarification_questions (JSON数组, 默认: [])
- clarification_answers (JSON数组, 默认: [])
- clarification_round (整数, 默认: 0)
- state_entered_at (时间戳)

如果使用ORM迁移工具，运行迁移脚本。如果手动管理，当前代码使用内存Session，无需立即迁移。

### 4. 重启服务

```bash
# 如果使用Docker
docker-compose restart feishu-connector

# 如果直接运行
pkill -f "uvicorn apps.feishu_connector.main:app"
uvicorn apps.feishu_connector.main:app --host 0.0.0.0 --port 8000
```

### 5. 验证部署

发送测试消息到飞书机器人：

**测试1：探索性对话**
```
用户: 帮我分析一下当前项目的架构
预期: 进入DISCUSSING状态，机器人询问项目信息
```

**测试2：需求提交**
```
用户: 帮我实现一个用户注册功能
预期: 进入CLARIFYING状态，机器人开始澄清需求
```

**测试3：查询**
```
用户: 当前有哪些任务？
预期: 执行查询，返回任务列表
```

## 回滚方案

如果出现问题，可以快速回滚：

### 方案1：禁用状态机
在 `apps/feishu_connector/main.py` 中注释掉DialogueStateManager的调用，恢复原有的简单意图分类逻辑。

### 方案2：完全回滚
```bash
git revert <commit_hash>
docker-compose restart feishu-connector
```

## 监控指标

建议监控以下指标：

1. **状态转换频率**
   - IDLE -> DISCUSSING
   - IDLE -> CLARIFYING
   - CLARIFYING -> CONFIRMING
   - CONFIRMING -> EXECUTING

2. **意图识别准确率**
   - 用户反馈的误判情况
   - 澄清轮次分布

3. **API调用**
   - Claude API调用次数和延迟
   - 错误率

4. **用户体验**
   - 平均澄清轮次
   - 从需求提交到确认的时间
   - 用户取消率

## 已知限制

1. **Session持久化**
   - 当前Session存储在内存中
   - 服务重启会丢失对话状态
   - 建议后续迁移到Redis或数据库

2. **并发处理**
   - 当前实现未考虑同一用户的并发消息
   - 建议添加消息队列

3. **Claude API依赖**
   - 意图识别和澄清依赖Claude API
   - API不可用时会降级到简单规则匹配
   - 建议添加降级策略和缓存

## 后续优化建议

1. **Session持久化**
   - 迁移到Redis，支持分布式部署
   - 添加Session过期机制

2. **意图识别优化**
   - 收集真实对话数据
   - 微调Prompt提升准确率
   - 添加意图识别缓存

3. **澄清流程优化**
   - 支持多轮澄清的上下文记忆
   - 智能判断何时停止澄清
   - 支持用户主动跳过澄清

4. **监控和日志**
   - 添加详细的状态转换日志
   - 集成APM工具
   - 添加用户行为分析

## 技术支持

如有问题，请查看：
- 技术方案文档: `docs/dialogue_state_machine_proposal.md`
- 测试脚本: `test_dialogue_flow.py`
- 代码注释: 各模块内的详细注释
