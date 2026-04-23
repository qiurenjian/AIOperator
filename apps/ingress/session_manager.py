from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from apps.ingress.conversation_state import ConversationContext
from apps.ingress.dialogue_state import DialogueState, RequirementDraft

log = logging.getLogger(__name__)


@dataclass
class Message:
    role: str  # "user" | "assistant"
    content: str
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class Session:
    chat_id: str
    user_id: str
    context: list[Message] = field(default_factory=list)
    conversation: ConversationContext = field(default_factory=ConversationContext)
    active_workflow_id: str | None = None
    project_id: str | None = None  # 当前项目上下文
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_active: datetime = field(default_factory=datetime.utcnow)

    # 对话状态机相关字段
    dialogue_state: DialogueState = DialogueState.IDLE
    state_entered_at: datetime = field(default_factory=datetime.utcnow)

    # 澄清过程数据
    clarification_questions: list[str] = field(default_factory=list)
    clarification_answers: list[str] = field(default_factory=list)

    # 需求草稿
    requirement_draft: Optional[RequirementDraft] = None

    def add_message(self, role: str, content: str):
        self.context.append(Message(role=role, content=content))
        self.last_active = datetime.utcnow()
        if len(self.context) > 20:
            self.context = self.context[-20:]

    def get_recent_context(self, n: int = 5) -> list[Message]:
        return self.context[-n:]

    def enter_state(self, new_state: DialogueState):
        """进入新状态"""
        self.dialogue_state = new_state
        self.state_entered_at = datetime.utcnow()
        log.info("chat_id=%s entered state %s", self.chat_id, new_state)

    def add_clarification(self, question: str, answer: str):
        """添加澄清问答"""
        self.clarification_questions.append(question)
        self.clarification_answers.append(answer)

    def get_state_duration(self) -> timedelta:
        """获取当前状态持续时间"""
        return datetime.utcnow() - self.state_entered_at

    def reset_clarification(self):
        """重置澄清数据"""
        self.clarification_questions = []
        self.clarification_answers = []
        self.requirement_draft = None


class SessionManager:
    _sessions: dict[str, Session] = {}

    @classmethod
    def get_or_create(cls, chat_id: str, user_id: str = "unknown") -> Session:
        if chat_id not in cls._sessions:
            cls._sessions[chat_id] = Session(chat_id=chat_id, user_id=user_id)
            log.info("created session for chat_id=%s", chat_id)
        session = cls._sessions[chat_id]
        session.last_active = datetime.utcnow()
        return session

    @classmethod
    def get(cls, chat_id: str) -> Session | None:
        return cls._sessions.get(chat_id)

    @classmethod
    def remove(cls, chat_id: str):
        if chat_id in cls._sessions:
            del cls._sessions[chat_id]
            log.info("removed session for chat_id=%s", chat_id)

    @classmethod
    def cleanup_stale(cls, max_age: timedelta = timedelta(hours=2)):
        now = datetime.utcnow()
        stale = [
            cid
            for cid, sess in cls._sessions.items()
            if now - sess.last_active > max_age
        ]
        for cid in stale:
            cls.remove(cid)
        if stale:
            log.info("cleaned up %d stale sessions", len(stale))


# 全局会话管理器实例
session_manager = SessionManager()
