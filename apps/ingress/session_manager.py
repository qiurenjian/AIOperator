from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

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
    active_workflow_id: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    last_active: datetime = field(default_factory=datetime.utcnow)

    def add_message(self, role: str, content: str):
        self.context.append(Message(role=role, content=content))
        self.last_active = datetime.utcnow()
        if len(self.context) > 20:
            self.context = self.context[-20:]

    def get_recent_context(self, n: int = 5) -> list[Message]:
        return self.context[-n:]


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
