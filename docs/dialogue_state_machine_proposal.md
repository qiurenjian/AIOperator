# AIOperator 对话状态机方案

## 一、问题分析

### 1.1 当前系统的核心问题

**症状**：
- 用户发送"梳理当前项目的整体结构，并给出优化分析建议"被误判为需求提交
- 系统立即触发 RequirementWorkflow，开始生成 PRD
- 用户无法进行自然的分析讨论，必须明确说"先出方案，不要改代码"

**根本原因**：
```python
# 当前的意图分类过于简单
class IntentType(str, Enum):
    CHAT = "chat"           # 闲聊
    REQUIREMENT = "requirement"  # 需求提交
    QUERY = "query"         # 状态查询
```

这种三分类无法区分：
- **探索性对话**："帮我分析一下..."
- **确认性需求**："我要实现用户登录功能"

### 1.2 用户期望

> "我需要支持灵活的自然语言沟通，不然都没法推进"

用户希望能够：
1. 自由讨论和分析问题
2. 在充分讨论后再决定是否提交需求
3. 系统能理解对话的上下文和意图演变
4. 避免误触发耗时的 workflow

---

## 二、解决方案：对话状态机

### 2.1 核心设计思想

**引入对话状态（Dialogue State）**，而不仅仅是意图分类（Intent Classification）：

```
意图分类（Intent）：单次消息的语义理解
对话状态（State）：多轮对话的上下文管理
```

**关键原则**：
1. **明确确认**：只有用户明确确认后才触发 workflow
2. **状态记忆**：系统记住对话处于哪个阶段
3. **灵活切换**：用户可以随时改变对话方向
4. **渐进式**：从讨论 → 澄清 → 确认 → 执行

### 2.2 状态定义

```python
class DialogueState(str, Enum):
    """对话状态"""
    
    # 空闲状态
    IDLE = "idle"
    # 初始状态，无活跃对话
    
    # 讨论状态
    DISCUSSING = "discussing"
    # 用户正在探索、分析、讨论问题
    # 特征：开放式问题、分析请求、方案探讨
    
    # 需求澄清状态
    CLARIFYING = "clarifying"
    # 用户表达了需求意图，系统正在澄清细节
    # 特征：系统主动提问，用户回答具体问题
    
    # 需求确认状态
    CONFIRMING = "confirming"
    # 需求已澄清，等待用户最终确认
    # 特征：系统展示需求摘要，询问是否提交
    
    # 执行状态
    EXECUTING = "executing"
    # workflow 已启动，正在执行
    # 特征：系统发送进度通知，用户可查询状态
    
    # 查询状态
    QUERYING = "querying"
    # 用户正在查询项目/需求状态
    # 特征：项目列表、需求详情、进度查询
```

### 2.3 状态转换图

```
                    ┌─────────────┐
                    │    IDLE     │
                    │   (空闲)     │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │            │            │
         讨论请求      需求意图      查询请求
              │            │            │
              ▼            ▼            ▼
      ┌──────────┐  ┌──────────┐  ┌──────────┐
      │DISCUSSING│  │CLARIFYING│  │ QUERYING │
      │  (讨论)   │  │  (澄清)   │  │  (查询)   │
      └────┬─────┘  └────┬─────┘  └────┬─────┘
           │             │             │
      继续讨论       澄清完成      查询完成
           │             │             │
           │             ▼             │
           │      ┌──────────┐        │
           │      │CONFIRMING│        │
           │      │  (确认)   │        │
           │      └────┬─────┘        │
           │           │              │
           │      用户确认            │
           │           │              │
           │           ▼              │
           │      ┌──────────┐        │
           └─────▶│EXECUTING │◀───────┘
                  │  (执行)   │
                  └────┬─────┘
                       │
                  workflow完成
                       │
                       ▼
                  ┌─────────┐
                  │  IDLE   │
                  └─────────┘
```

### 2.4 意图识别增强

**当前问题**：
- 只有 CHAT/REQUIREMENT/QUERY 三种意图
- 无法区分"讨论"和"需求"

**改进方案**：

```python
class EnhancedIntent:
    """增强的意图识别"""
    
    type: IntentType  # CHAT, REQUIREMENT, QUERY, DISCUSSION
    confidence: float  # 置信度 0-1
    signals: list[str]  # 识别信号
    
    # 新增字段
    is_exploratory: bool  # 是否是探索性对话
    is_actionable: bool   # 是否是可执行的需求
    requires_clarification: bool  # 是否需要澄清

# 意图识别 Prompt 优化
INTENT_CLASSIFICATION_PROMPT = """
分析用户消息的意图，区分以下类型：

1. **DISCUSSION（讨论）**：
   - 探索性问题："帮我分析..."、"你觉得..."、"有什么建议..."
   - 开放式请求："梳理一下..."、"评估一下..."
   - 方案探讨："如果...会怎样"、"我们可以..."
   
2. **REQUIREMENT（需求）**：
   - 明确的实现请求："实现..."、"开发..."、"添加..."
   - 具体的功能描述："用户可以..."、"系统需要..."
   - 带有明确目标的请求："我要..."、"帮我做..."
   
3. **QUERY（查询）**：
   - 状态查询："当前进度"、"项目详情"、"需求列表"
   - 信息获取："有哪些..."、"显示..."
   
4. **CHAT（闲聊）**：
   - 问候、感谢、确认等

关键判断：
- 如果用户说"先出方案"、"分析一下"、"评估"，一定是 DISCUSSION
- 如果用户说"实现"、"开发"、"添加功能"，才是 REQUIREMENT
- 如果不确定，倾向于 DISCUSSION，避免误触发 workflow

用户消息：{message}

最近对话：
{context}

返回 JSON：
{{
  "type": "DISCUSSION|REQUIREMENT|QUERY|CHAT",
  "confidence": 0.0-1.0,
  "is_exploratory": true/false,
  "is_actionable": true/false,
  "requires_clarification": true/false,
  "reasoning": "判断理由"
}}
"""
```

### 2.5 确认机制

**核心原则**：只有用户明确确认后才启动 workflow

**确认消息格式**：

```python
def _format_confirmation_message(self, summary: RequirementSummary) -> str:
    """格式化确认消息"""
    return f"""
📋 **需求摘要**

**标题**：{summary.title}

**描述**：
{summary.description}

**关键功能**：
{self._format_features(summary.features)}

**预估成本**：${summary.estimated_cost:.2f}

**预估时间**：{summary.estimated_time}

---

请确认是否提交此需求：
• 回复「确认」或「提交」→ 开始生成 PRD
• 回复「修改」或「重新描述」→ 重新澄清
• 回复「取消」→ 取消本次需求
"""
```

### 2.6 Session 扩展

```python
@dataclass
class Session:
    """会话状态"""
    
    # 现有字段
    chat_id: str
    user_id: str
    project_id: Optional[str]
    active_workflow_id: Optional[str]
    context: list[dict]
    conversation: list[dict]
    
    # 新增字段
    dialogue_state: DialogueState = DialogueState.IDLE
    state_entered_at: datetime = field(default_factory=datetime.now)
    
    # 澄清过程数据
    clarification_questions: list[str] = field(default_factory=list)
    clarification_answers: list[str] = field(default_factory=list)
    
    # 需求草稿
    requirement_draft: Optional[RequirementDraft] = None
    
    def enter_state(self, new_state: DialogueState):
        """进入新状态"""
        self.dialogue_state = new_state
        self.state_entered_at = datetime.now()
    
    def add_clarification(self, question: str, answer: str):
        """添加澄清问答"""
        self.clarification_questions.append(question)
        self.clarification_answers.append(answer)
```

---

## 三、实现方案

### 3.1 文件结构

```
apps/ingress/
├── dialogue_state.py          # 状态定义
├── dialogue_manager.py        # 状态管理器
├── intent_analyzer.py         # 增强的意图分析
├── confirmation_handler.py    # 确认处理
├── session_manager.py         # 会话管理（扩展）
└── main.py                    # 主入口（修改）
```

### 3.2 核心代码框架

**dialogue_state.py**:
```python
from enum import Enum
from dataclasses import dataclass
from typing import Optional

class DialogueState(str, Enum):
    IDLE = "idle"
    DISCUSSING = "discussing"
    CLARIFYING = "clarifying"
    CONFIRMING = "confirming"
    EXECUTING = "executing"
    QUERYING = "querying"

class Action(str, Enum):
    CHAT = "chat"
    DISCUSS = "discuss"
    CLARIFY = "clarify"
    CONFIRM = "confirm"
    EXECUTE = "execute"
    QUERY = "query"
    CANCEL = "cancel"
    COMPLETE = "complete"
    WAIT = "wait"

@dataclass
class StateTransition:
    next_state: DialogueState
    action: Action
    response: str
    metadata: Optional[dict] = None
```

**dialogue_manager.py**:
```python
class DialogueStateManager:
    """对话状态管理器"""
    
    async def handle_message(
        self,
        session: Session,
        message: str,
    ) -> StateTransition:
        """处理消息并返回状态转换"""
        
        current_state = session.dialogue_state
        
        # 1. 分析消息意图
        intent = await self._analyze_intent(message, session)
        
        # 2. 根据当前状态和意图决定转换
        if current_state == DialogueState.IDLE:
            return await self._handle_idle(intent, message, session)
        
        elif current_state == DialogueState.DISCUSSING:
            return await self._handle_discussing(intent, message, session)
        
        elif current_state == DialogueState.CLARIFYING:
            return await self._handle_clarifying(intent, message, session)
        
        elif current_state == DialogueState.CONFIRMING:
            return await self._handle_confirming(intent, message, session)
        
        elif current_state == DialogueState.EXECUTING:
            return await self._handle_executing(intent, message, session)
        
        elif current_state == DialogueState.QUERYING:
            return await self._handle_querying(intent, message, session)
```

### 3.3 集成点

**修改 apps/feishu_connector/main.py**:

```python
from apps.ingress.dialogue_manager import DialogueStateManager

dialogue_mgr = DialogueStateManager()

async def handle_message_event(event):
    """处理接收消息事件"""
    # ... 解析消息 ...
    
    # 获取或创建会话
    session = session_manager.get_or_create(chat_id, sender_id)
    session.add_message("user", text)
    
    # 使用对话状态管理器处理消息
    transition = await dialogue_mgr.handle_message(session, text)
    
    # 执行状态转换
    session.enter_state(transition.next_state)
    
    # 执行动作
    if transition.action == Action.EXECUTE:
        # 启动 workflow
        workflow_id = await start_requirement_workflow(session)
        session.active_workflow_id = workflow_id
    
    # 发送响应
    await send_feishu_message(chat_id, transition.response)
```

### 3.4 实现阶段

**阶段 1：核心状态机（1-2 天）**
- 实现 `DialogueState` 枚举
- 实现 `DialogueStateManager` 核心逻辑
- 扩展 `Session` 数据结构
- 单元测试

**阶段 2：意图识别增强（1 天）**
- 优化意图分类 Prompt
- 添加 `DISCUSSION` 意图类型
- 添加探索性/可执行性判断
- 测试意图识别准确率

**阶段 3：确认机制（1 天）**
- 实现确认消息格式化
- 实现确认/拒绝判断逻辑
- 实现需求摘要生成
- 测试确认流程

**阶段 4：集成测试（1 天）**
- 端到端测试
- 边界情况测试
- 性能测试
- 部署到测试环境

**阶段 5：生产部署（0.5 天）**
- 灰度发布
- 监控和调优
- 文档更新

**总计：4.5-5.5 天**

---

## 四、示例对话流程

### 4.1 探索性对话（不触发 workflow）

```
用户：梳理当前项目的整体结构，并给出优化分析建议

[状态：IDLE → DISCUSSING]

系统：好的，我来分析一下当前项目结构：

当前架构：
• apps/feishu_connector：飞书消息接收
• apps/ingress：意图分类和路由
• workflows/requirement.py：需求处理流程
• activities/：各种执行单元

主要问题：
1. 意图分类过于简单，容易误判
2. 缺少对话状态管理
3. 确认机制不够明确

优化建议：
1. 引入对话状态机
2. 增强意图识别
3. 添加明确确认步骤

你想深入了解哪个方面？

[状态：DISCUSSING]
```

### 4.2 需求提交（触发 workflow）

```
用户：实现用户登录功能

[状态：IDLE → CLARIFYING]

系统：好的，我需要了解一些细节：

1. 支持哪些登录方式？
   • 用户名密码
   • 手机号验证码
   • 第三方登录（微信、支付宝等）

[状态：CLARIFYING]

用户：用户名密码和手机号验证码

[状态：CLARIFYING → CLARIFYING]

系统：明白了。还有几个问题：

2. 是否需要记住登录状态？
3. 密码复杂度要求？
4. 验证码有效期？

[状态：CLARIFYING]

用户：需要记住登录状态，密码至少8位包含字母数字，验证码5分钟有效

[状态：CLARIFYING → CONFIRMING]

系统：
📋 **需求摘要**

**标题**：用户登录功能

**描述**：
实现用户登录功能，支持用户名密码和手机号验证码两种方式

**关键功能**：
• 用户名密码登录（密码≥8位，含字母数字）
• 手机号验证码登录（验证码5分钟有效）
• 记住登录状态
• 登录失败提示

**预估成本**：$2.50
**预估时间**：30-40 分钟

---

请确认是否提交此需求：
• 回复「确认」或「提交」→ 开始生成 PRD
• 回复「修改」→ 重新澄清
• 回复「取消」→ 取消本次需求

[状态：CONFIRMING]

用户：确认

[状态：CONFIRMING → EXECUTING]

系统：✅ 需求已提交，正在处理...
Workflow ID: req-oc_xxx-om_xxx

🔍 正在分析需求...

[状态：EXECUTING]
```

---

## 五、风险与缓解

### 5.1 风险 1：状态转换逻辑复杂

**影响**：难以维护，容易出 bug

**缓解**：
- 使用状态机库（如 `python-statemachine`）
- 完善的单元测试
- 状态转换日志记录
- 可视化状态转换图

### 5.2 风险 2：意图识别准确率

**影响**：仍然可能误判

**缓解**：
- 使用更强的模型（Claude Sonnet）
- 优化 Prompt 工程
- 添加人工反馈循环
- 记录误判案例并持续优化

### 5.3 风险 3：用户不理解确认机制

**影响**：用户不知道如何确认

**缓解**：
- 清晰的确认消息格式
- 提供明确的操作指引
- 支持多种确认方式（"确认"、"提交"、"ok"等）
- 添加帮助命令

### 5.4 风险 4：状态持久化失败

**影响**：服务重启后状态丢失

**缓解**：
- 使用 Redis 持久化会话
- 定期保存状态快照
- 添加状态恢复机制

---

## 六、成功标准

### 6.1 功能指标

- ✅ 探索性对话不触发 workflow（准确率 > 95%）
- ✅ 明确需求正确触发 workflow（准确率 > 95%）
- ✅ 用户可以在讨论中自然过渡到需求提交
- ✅ 确认机制清晰，用户理解如何操作
- ✅ 状态转换逻辑正确，无死循环

### 6.2 用户体验指标

- ✅ 用户可以自由讨论和分析问题
- ✅ 系统响应符合对话上下文
- ✅ 误触发率 < 5%
- ✅ 用户满意度显著提升

### 6.3 技术指标

- ✅ 状态转换延迟 < 500ms
- ✅ 意图识别延迟 < 2s
- ✅ 会话持久化成功率 > 99.9%
- ✅ 系统稳定性无下降

---

## 七、总结

### 7.1 核心价值

**解决的核心问题**：
- 系统过于死板，无法支持灵活的自然语言沟通
- 探索性对话被误判为需求，触发不必要的 workflow
- 缺少明确的确认机制，用户体验差

**带来的改进**：
- 用户可以自由讨论和分析问题
- 系统理解对话上下文和意图演变
- 只有明确确认后才执行耗时操作
- 对话流程更自然、更符合人类交互习惯

### 7.2 实施建议

**优先级**：
1. **P0（必须）**：核心状态机 + 意图识别增强
2. **P1（重要）**：确认机制 + Session 扩展
3. **P2（优化）**：状态持久化 + 监控告警

**时间规划**：
- 第 1-2 天：核心状态机实现
- 第 3 天：意图识别增强
- 第 4 天：确认机制和集成测试
- 第 5 天：部署和优化

**下一步行动**：
1. 确认方案
2. 创建开发分支
3. 实施阶段 1：核心状态机
4. 单元测试和集成测试
5. 灰度发布和监控

---

**方案版本**：v1.0  
**创建时间**：2026-04-23  
**作者**：Claude (Opus 4.7)  
**状态**：待确认
