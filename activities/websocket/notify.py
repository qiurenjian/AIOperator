from __future__ import annotations

import logging

from temporalio import activity

log = logging.getLogger(__name__)


@activity.defn(name="notify_websocket")
async def notify_websocket(chat_id: str, message: dict) -> None:
    """Send notification to WebSocket client.

    Note: This is a placeholder. In production, use Redis pub/sub or message queue.
    For now, we'll just log the notification.
    """
    log.info("websocket notification for chat_id=%s: %s", chat_id, message)

    # TODO: Implement actual notification via Redis pub/sub
    # Example:
    # redis_client = await get_redis_client()
    # await redis_client.publish(f"ws:{chat_id}", json.dumps(message))
