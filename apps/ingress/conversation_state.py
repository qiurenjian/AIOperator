"""会话状态管理"""
from enum import Enum
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime


class ConversationPhase(str, Enum):
    """对话阶段"""
    IDLE = "idle"                           # 空闲状态
    REQUIREMENT_CLARIFYING = "req_clarify"  # 需求澄清中
    REQUIREMENT_CONFIRMED = "req_confirmed" # 需求已确认，待提交
    PRD_REVIEW = "prd_review"              # PRD 审查中
    DESIGN_DISCUSSION = "design_discuss"    # 技术方案讨论中
    IMPLEMENTATION = "implementing"         # 实现中
    CODE_REVIEW = "code_review"            # 代码审查中


@dataclass
class ConversationContext:
    """对话上下文"""
    phase: ConversationPhase = ConversationPhase.IDLE
    workflow_id: Optional[str] = None       # 关联的 workflow ID
    req_id: Optional[str] = None            # 需求 ID

    # 需求澄清阶段的数据
    requirement_draft: Optional[str] = None  # 需求草稿
    clarification_rounds: int = 0            # 澄清轮次

    # PRD 审查阶段的数据
    prd_content: Optional[str] = None        # PRD 内容
    prd_feedback: list[str] = field(default_factory=list)  # 用户反馈

    # 技术方案阶段的数据
    design_doc: Optional[str] = None         # 设计文档
    design_decisions: list[str] = field(default_factory=list)  # 设计决策

    # 元数据
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    def update_phase(self, new_phase: ConversationPhase):
        """更新阶段"""
        self.phase = new_phase
        self.updated_at = datetime.now()

    def is_in_requirement_phase(self) -> bool:
        """是否在需求相关阶段"""
        return self.phase in [
            ConversationPhase.REQUIREMENT_CLARIFYING,
            ConversationPhase.REQUIREMENT_CONFIRMED,
        ]

    def is_in_prd_phase(self) -> bool:
        """是否在 PRD 相关阶段"""
        return self.phase == ConversationPhase.PRD_REVIEW

    def is_in_design_phase(self) -> bool:
        """是否在设计相关阶段"""
        return self.phase == ConversationPhase.DESIGN_DISCUSSION

    def can_start_workflow(self) -> bool:
        """是否可以启动 workflow"""
        return self.phase == ConversationPhase.REQUIREMENT_CONFIRMED
