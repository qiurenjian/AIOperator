from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel
from temporalio import activity

from aiop.feishu_client import FeishuClient
from aiop.types import CardSendResult


class SendCardInput(BaseModel):
    chat_id: str
    receive_id_type: str = "chat_id"
    card: dict[str, Any]


@activity.defn(name="feishu_send_card")
async def feishu_send_card(payload: SendCardInput) -> CardSendResult:
    client = FeishuClient()
    try:
        data = await client.send_card(
            receive_id=payload.chat_id,
            receive_id_type=payload.receive_id_type,
            card=payload.card,
        )
        return CardSendResult(
            message_id=data["message_id"],
            chat_id=payload.chat_id,
            sent_at=datetime.utcnow(),
        )
    finally:
        await client.aclose()
