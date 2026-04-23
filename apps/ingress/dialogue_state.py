"""对话状态定义"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class DialogueState(str, Enum):
    """对话状态"""

    IDLE = "idle"  # 空闲状态
    DISCUSSING = "discussing"  # 讨论状态
    CLARIFYING = "clarifying"  # 需求澄清状态
    CONFIRMING = "confirming"  # 需求确认状态
    EXECUTING = "executing"  # 执行状态
    QUERYING = "querying"  # 查询状态


class Action(str, Enum):
    """动作类型"""

    CHAT = "chat"  # 闲聊
    DISCUSS = "discuss"  # 讨论
    CLARIFY = "clarify"  # 澄清
    CONFIRM = "confirm"  # 确认
    EXECUTE = "execute"  # 执行
    QUERY = "query"  # 查询
    CANCEL = "cancel"  # 取消
    COMPLETE = "complete"  # 完成
    WAIT = "wait"  # 等待


@dataclass
class StateTransition:
    """状态转换"""

    next_state: DialogueState
    action: Action
    response: str
    metadata: Optional[dict] = None


@dataclass
class RequirementDraft:
    """需求草稿"""

    title: str
    description: str
    features: list[str] = field(default_factory=list)
    clarifications: dict[str, str] = field(default_factory=dict)
    estimated_cost: float = 0.0
    estimated_time: str = ""
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def add_clarification(self, question: str, answer: str):
        """添加澄清问答"""
        self.clarifications[question] = answer
        self.updated_at = datetime.now()

    def to_summary(self) -> str:
        """生成需求摘要"""
        features_text = "\n".join(f"• {f}" for f in self.features)
        return f"""📋 **需求摘要**

**标题**：{self.title}

**描述**：
{self.description}

**关键功能**：
{features_text}

**预估成本**：${self.estimated_cost:.2f}

**预估时间**：{self.estimated_time}

---

请确认是否提交此需求：
• 回复「确认」或「提交」→ 开始生成 PRD
• 回复「修改」或「重新描述」→ 重新澄清
• 回复「取消」→ 取消本次需求
"""
