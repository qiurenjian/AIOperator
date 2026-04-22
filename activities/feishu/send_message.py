"""飞书文本消息发送 Activity"""
from __future__ import annotations

import logging

from lark_oapi import Client
from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody
from temporalio import activity

from aiop.settings import get_settings

log = logging.getLogger(__name__)


@activity.defn(name="feishu_send_message")
async def feishu_send_message(chat_id: str, message: str) -> None:
    """
    发送文本消息到飞书

    Args:
        chat_id: 飞书会话 ID
        message: 消息内容
    """
    settings = get_settings()

    activity.heartbeat({"chat_id": chat_id, "stage": "sending"})

    client = Client.builder() \
        .app_id(settings.feishu_app_id) \
        .app_secret(settings.feishu_app_secret) \
        .build()

    request = CreateMessageRequest.builder() \
        .receive_id_type("chat_id") \
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("text")
            .content(f'{{"text":"{message}"}}')
            .build()
        ) \
        .build()

    response = client.im.v1.message.create(request)

    if not response.success():
        log.error(
            "failed to send feishu message: code=%s msg=%s",
            response.code,
            response.msg,
        )
        raise RuntimeError(f"feishu API error: {response.code} {response.msg}")

    log.info("sent feishu message to chat_id=%s", chat_id)
