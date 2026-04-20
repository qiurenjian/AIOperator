# AIOperator V2 架构：长连接 + 意图识别

## 问题分析

### 当前架构（V1）的局限
1. **HTTP 回调不可靠**：飞书要求 3 秒响应，workflow 执行时间不可控
2. **无对话能力**：每条消息都触发 workflow，无法自然沟通需求细节
3. **交互体验差**：卡片按钮响应慢，用户不知道后台在做什么
4. **缺少流式反馈**：PRD 生成需要几分钟，用户只能等待

### V2 架构目标
- 支持多轮对话（讨论需求、技术方案、PRD 审查）
- 实时反馈（打字中状态、流式输出 PRD）
- 意图识别（自动判断是对话还是需求提交）
- 更好的用户体验（即时响应、进度可见）

---

## 架构设计

### 核心组件

```
┌─────────────────────────────────────────────────────────────┐
│                         飞书客户端                            │
└────────────────────┬────────────────────────────────────────┘
                     │ 长连接 WebSocket
                     ↓
┌─────────────────────────────────────────────────────────────┐
│                    Ingress (FastAPI)                         │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  WebSocket Handler                                    │   │
│  │  - 接收用户消息                                        │   │
│  │  - 维护会话上下文                                      │   │
│  │  - 发送实时反馈                                        │   │
│  └──────────────────────────────────────────────────────┘   │
│                     ↓                                        │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Intent Classifier (Claude Haiku)                     │   │
│  │  - 对话类：直接 LLM 回复                               │   │
│  │  - 需求类：启动 RequirementWorkflow                    │   │
│  │  - 审批类：发送 signal 到 workflow                     │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                     ↓
┌─────────────────────────────────────────────────────────────┐
│                    Temporal Workflows                        │
│  - RequirementWorkflow (P0-P4)                              │
│  - 通过 WebSocket 发送进度更新                               │
└─────────────────────────────────────────────────────────────┘
```

### 会话管理

每个飞书对话（chat_id）对应一个 WebSocket 连接和会话上下文：

```python
class Session:
    chat_id: str
    user_id: str
    context: list[Message]  # 对话历史
    active_workflow_id: str | None  # 当前关联的 workflow
    created_at: datetime
    last_active: datetime
```

### 意图分类

使用 Claude Haiku 快速分类（<1秒）：

```python
class Intent(Enum):
    CHAT = "chat"              # 普通对话：讨论、咨询、澄清
    REQUIREMENT = "requirement"  # 需求提交：明确要实现某功能
    APPROVAL = "approval"       # 审批操作：确认/拒绝 PRD
    QUERY = "query"            # 状态查询：查看进度、历史需求
```

**分类 Prompt 示例：**
```
用户消息："{user_message}"
当前上下文：{context_summary}

判断用户意图（返回 JSON）：
- chat: 讨论、咨询、澄清需求细节
- requirement: 明确提出要实现某功能（"帮我实现..."、"我需要..."）
- approval: 确认或拒绝某个方案
- query: 查询状态或历史

返回格式：{"intent": "...", "confidence": 0.0-1.0, "reason": "..."}
```

---

## 交互流程

### 场景 1：需求讨论 → 提交

```
用户: "我想做一个登录功能"
Bot:  [intent=chat] "好的，我来帮你梳理一下。你希望支持哪些登录方式？
      1. 用户名密码
      2. 手机号验证码
      3. 第三方登录（微信/GitHub）"

用户: "先做用户名密码，要支持记住登录状态"
Bot:  [intent=chat] "明白了。关于安全性：
      - 密码加密方式：bcrypt
      - 会话管理：JWT token
      - 记住登录：refresh token（7天有效期）
      这样可以吗？"

用户: "可以，就这样实现吧"
Bot:  [intent=requirement] "✅ 需求已确认，正在生成 PRD..."
      → 启动 RequirementWorkflow
      → 实时流式输出 PRD 内容
```

### 场景 2：纯对话咨询

```
用户: "JWT 和 Session 有什么区别？"
Bot:  [intent=chat] "JWT 和 Session 是两种不同的会话管理方式：
      
      JWT (JSON Web Token)：
      - 无状态，token 包含所有信息
      - 服务端不需要存储
      - 适合分布式系统
      
      Session：
      - 有状态，服务端存储会话数据
      - 客户端只保存 session_id
      - 需要共享存储（Redis）
      
      你的场景更适合用 JWT，因为..."

→ 不触发 workflow，直接对话
```

### 场景 3：PRD 审批

```
Bot:  [workflow 发送] "📄 PRD 已生成，请审阅：
      [PRD 内容...]
      
      请回复：
      - '通过' 或 '批准'：开始实现
      - '修改 XXX'：调整 PRD
      - '拒绝'：终止需求"

用户: "通过"
Bot:  [intent=approval] "✅ PRD 已批准，开始实现..."
      → 发送 p1_approve signal 到 workflow
```

---

## 技术实现

### 1. WebSocket 端点

```python
# apps/ingress/websocket.py
from fastapi import WebSocket

@app.websocket("/ws/{chat_id}")
async def websocket_endpoint(websocket: WebSocket, chat_id: str):
    await websocket.accept()
    session = SessionManager.get_or_create(chat_id)
    
    try:
        while True:
            data = await websocket.receive_json()
            message = data["message"]
            
            # 1. 意图识别
            intent = await classify_intent(message, session.context)
            
            # 2. 路由处理
            if intent.type == Intent.CHAT:
                response = await handle_chat(message, session)
                await websocket.send_json({"type": "message", "content": response})
            
            elif intent.type == Intent.REQUIREMENT:
                req_id = await start_requirement_workflow(message, session)
                await websocket.send_json({"type": "workflow_started", "req_id": req_id})
            
            elif intent.type == Intent.APPROVAL:
                await handle_approval(message, session)
            
            # 3. 更新上下文
            session.add_message(message, response)
    
    except WebSocketDisconnect:
        SessionManager.remove(chat_id)
```

### 2. 意图分类器

```python
# apps/ingress/intent_classifier.py
from anthropic import Anthropic

async def classify_intent(message: str, context: list[Message]) -> Intent:
    client = Anthropic(api_key=settings.anthropic_api_key)
    
    prompt = f"""
    用户消息："{message}"
    对话历史：{format_context(context[-3:])}  # 最近 3 轮
    
    判断意图并返回 JSON：
    {{
      "intent": "chat|requirement|approval|query",
      "confidence": 0.0-1.0,
      "reason": "判断依据"
    }}
    """
    
    response = client.messages.create(
        model="claude-haiku-4",
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}]
    )
    
    result = json.loads(response.content[0].text)
    return Intent(
        type=result["intent"],
        confidence=result["confidence"],
        reason=result["reason"]
    )
```

### 3. 会话管理

```python
# apps/ingress/session_manager.py
from datetime import datetime, timedelta

class SessionManager:
    _sessions: dict[str, Session] = {}
    
    @classmethod
    def get_or_create(cls, chat_id: str) -> Session:
        if chat_id not in cls._sessions:
            cls._sessions[chat_id] = Session(
                chat_id=chat_id,
                context=[],
                created_at=datetime.utcnow()
            )
        return cls._sessions[chat_id]
    
    @classmethod
    def cleanup_stale(cls, max_age: timedelta = timedelta(hours=2)):
        """清理超过 2 小时无活动的会话"""
        now = datetime.utcnow()
        stale = [
            cid for cid, sess in cls._sessions.items()
            if now - sess.last_active > max_age
        ]
        for cid in stale:
            del cls._sessions[cid]
```

### 4. Workflow 进度推送

```python
# workflows/requirement.py
@workflow.defn
class RequirementWorkflow:
    def __init__(self):
        self._ws_notifier = WebSocketNotifier()
    
    @workflow.run
    async def run(self, input: RequirementInput) -> str:
        # P0: 捕获需求
        await self._ws_notifier.send(input.chat_id, {
            "type": "progress",
            "phase": "P0",
            "message": "正在分析需求..."
        })
        
        capture_result = await workflow.execute_activity(
            claude_capture_requirement,
            input,
            task_queue="lite"
        )
        
        # P1: 生成 PRD（流式输出）
        await self._ws_notifier.send(input.chat_id, {
            "type": "progress",
            "phase": "P1",
            "message": "正在生成 PRD..."
        })
        
        async for chunk in workflow.execute_activity_stream(
            claude_generate_prd,
            capture_result
        ):
            await self._ws_notifier.send(input.chat_id, {
                "type": "prd_chunk",
                "content": chunk
            })
        
        # 等待审批
        await workflow.wait_condition(lambda: self.prd_approved)
        ...
```

---

## 迁移计划

### Phase 1: 基础设施（Week 1 Day 3-4）
- [ ] 实现 WebSocket 端点和会话管理
- [ ] 实现意图分类器（Claude Haiku）
- [ ] 添加 WebSocket 通知机制到 workflow

### Phase 2: 对话能力（Week 1 Day 5）
- [ ] 实现 chat intent 处理（直接 LLM 对话）
- [ ] 实现上下文管理（对话历史）
- [ ] 测试多轮对话流程

### Phase 3: 集成测试（Week 1 Day 6-7）
- [ ] 端到端测试：需求讨论 → 提交 → PRD → 审批
- [ ] 性能测试：并发会话、长连接稳定性
- [ ] 用户体验优化：打字中状态、错误处理

### Phase 4: 灰度发布（Week 2）
- [ ] 保留 HTTP webhook 作为降级方案
- [ ] 小范围测试长连接版本
- [ ] 收集反馈并迭代

---

## 成本估算

### API 调用成本
- **意图分类**：Claude Haiku，每次 ~200 tokens，$0.0002/次
- **对话回复**：Claude Sonnet，每次 ~1000 tokens，$0.003/次
- **PRD 生成**：Claude Opus（通过 CLI），每次 ~$0.50

假设每天 100 条消息：
- 意图分类：100 × $0.0002 = $0.02
- 对话回复（50%）：50 × $0.003 = $0.15
- PRD 生成（10%）：10 × $0.50 = $5.00
- **日成本：~$5.17**

### 基础设施成本
- 云服务器：$10/月（已有）
- Temporal Cloud：免费额度内
- **总成本：~$165/月**（$5.17 × 30 + $10）

---

## 风险与缓解

### 风险 1：WebSocket 连接不稳定
- **缓解**：实现自动重连机制，会话状态持久化到 Redis

### 风险 2：意图分类错误
- **缓解**：
  - 低置信度时询问用户确认
  - 提供 "撤销" 功能
  - 收集错误案例持续优化 prompt

### 风险 3：并发会话过多
- **缓解**：
  - 限制单用户并发会话数（3 个）
  - 自动清理超时会话
  - 使用连接池管理资源

---

## 下一步

1. **立即行动**：实现 WebSocket 基础框架
2. **并行开发**：意图分类器 + 会话管理
3. **快速验证**：先实现 chat intent，验证对话体验
4. **逐步迁移**：保留 HTTP webhook，灰度切换到长连接

预计 **3-4 天** 完成核心功能，**1 周** 完成端到端测试。
