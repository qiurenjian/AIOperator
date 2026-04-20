from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class WebSocketNotifier:
    """Notifier for sending progress updates from workflows to WebSocket clients.

    Note: This is a placeholder implementation. In production, you would:
    1. Use Redis pub/sub or similar message broker
    2. Maintain WebSocket connection registry
    3. Handle connection failures gracefully
    """

    _connections: dict[str, Any] = {}  # chat_id -> websocket

    @classmethod
    def register(cls, chat_id: str, websocket: Any):
        """Register a WebSocket connection for a chat."""
        cls._connections[chat_id] = websocket
        log.info("registered websocket for chat_id=%s", chat_id)

    @classmethod
    def unregister(cls, chat_id: str):
        """Unregister a WebSocket connection."""
        if chat_id in cls._connections:
            del cls._connections[chat_id]
            log.info("unregistered websocket for chat_id=%s", chat_id)

    @classmethod
    async def send(cls, chat_id: str, message: dict):
        """Send a message to a WebSocket client."""
        ws = cls._connections.get(chat_id)
        if not ws:
            log.warning("no websocket connection for chat_id=%s", chat_id)
            return

        try:
            await ws.send_json(message)
            log.debug("sent message to chat_id=%s: %s", chat_id, message.get("type"))
        except Exception as e:
            log.error("failed to send message to chat_id=%s: %s", chat_id, e)
            cls.unregister(chat_id)
