"""
Feishu WebSocket Connector - 使用长连接接收飞书事件和回调
"""
from __future__ import annotations

import asyncio
import json
import logging

import lark_oapi as lark
from lark_oapi.api.im.v1 import (
    CreateMessageRequest,
    CreateMessageRequestBody,
)

from aiop.settings import get_settings
from apps.ingress.chat_handler import handle_chat
from apps.ingress.intent_classifier import IntentType, classify_intent
from apps.ingress.session_manager import SessionManager
from apps.ingress.temporal_client import get_temporal_client
from aiop.types import RequirementInput

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

session_manager = SessionManager()


async def handle_message_event(event_dict: dict):
    """处理接收消息事件"""
    try:
        # 解析消息内容
        message = event_dict.get("message", {})
        sender = event_dict.get("sender", {})

        chat_id = message.get("chat_id")
        message_id = message.get("message_id")
        content = json.loads(message.get("content", "{}"))
        text = content.get("text", "").strip()

        sender_id = sender.get("sender_id", {}).get("user_id", "unknown")

        log.info(
            "received message from %s in chat %s: %s",
            sender_id,
            chat_id,
            text[:50],
        )

        if not text:
            return

        # 获取或创建会话
        session = session_manager.get_or_create_session(chat_id)
        session.add_message("user", text)

        # 意图分类
        intent = await classify_intent(text, session.get_recent_context(n=5))
        log.info("classified intent: %s (%.2f)", intent.type, intent.confidence)

        # 根据意图处理
        if intent.type == IntentType.CHAT:
            # 对话模式
            reply = await handle_chat(text, session)
            session.add_message("assistant", reply)
            await send_feishu_message(chat_id, reply)

        elif intent.type == IntentType.REQUIREMENT:
            # 需求提交模式
            reply = "收到需求，正在分析和生成 PRD，请稍候..."
            await send_feishu_message(chat_id, reply)

            # 启动 workflow
            settings = get_settings()
            client = await get_temporal_client()

            workflow_input = RequirementInput(
                raw_text=text,
                source="feishu",
                user_id=sender_id,
                chat_id=chat_id,
                message_id=message_id,
                repo_url=settings.healthassit_repo,
                branch=settings.healthassit_default_branch,
            )

            workflow_id = f"req-{chat_id}-{message_id}"

            await client.start_workflow(
                "RequirementWorkflow",
                workflow_input,
                id=workflow_id,
                task_queue="lite",
            )

            log.info("started workflow %s for requirement", workflow_id)

        elif intent.type == IntentType.QUERY:
            # 查询模式
            reply = "查询功能开发中，敬请期待..."
            await send_feishu_message(chat_id, reply)

        else:
            # 其他意图
            reply = "抱歉，我还不太理解你的意思，可以换个方式说吗？"
            await send_feishu_message(chat_id, reply)

    except Exception as e:
        log.error("failed to handle message event: %s", e, exc_info=True)


async def handle_card_callback(event_dict: dict):
    """处理消息卡片回调"""
    try:
        action = event_dict.get("action", {})
        value = action.get("value", {})

        log.info("received card callback: %s", value)

        # 解析回调数据
        action_type = value.get("action")
        workflow_id = value.get("workflow_id")

        if not workflow_id:
            log.warning("card callback missing workflow_id")
            return

        # 发送信号到 workflow
        client = await get_temporal_client()
        handle = client.get_workflow_handle(workflow_id)

        if action_type == "p0_approve":
            await handle.signal("p0_approve")
            log.info("sent signal p0_approve to workflow %s", workflow_id)

        elif action_type == "p0_revise":
            await handle.signal("p0_revise")
            log.info("sent signal p0_revise to workflow %s", workflow_id)

        elif action_type == "p1_approve":
            await handle.signal("p1_approve")
            log.info("sent signal p1_approve to workflow %s", workflow_id)

        elif action_type == "p1_reject":
            await handle.signal("p1_reject")
            log.info("sent signal p1_reject to workflow %s", workflow_id)

        else:
            log.warning("unknown card action: %s", action_type)

    except Exception as e:
        log.error("failed to handle card callback: %s", e, exc_info=True)


async def send_feishu_message(chat_id: str, text: str):
    """发送飞书消息"""
    try:
        settings = get_settings()
        client = lark.Client.builder() \
            .app_id(settings.feishu_app_id) \
            .app_secret(settings.feishu_app_secret) \
            .build()

        request = CreateMessageRequest.builder() \
            .receive_id_type("chat_id") \
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type("text")
                .content(json.dumps({"text": text}))
                .build()
            ) \
            .build()

        response = client.im.v1.message.create(request)

        if not response.success():
            log.error(
                "failed to send message: code=%s, msg=%s",
                response.code,
                response.msg,
            )
        else:
            log.info("sent message to chat %s", chat_id)

    except Exception as e:
        log.error("failed to send feishu message: %s", e, exc_info=True)


def do_p2_im_message_receive_v1(data: lark.P2ImMessageReceiveV1) -> None:
    """处理接收消息事件"""
    log.info("received im.message.receive_v1 event")
    event_dict = data.event.__dict__ if hasattr(data.event, '__dict__') else {}
    asyncio.create_task(handle_message_event(event_dict))


def do_p2_card_action_trigger(data: lark.P2CardActionTrigger) -> None:
    """处理卡片回调事件"""
    log.info("received card.action.trigger event")
    event_dict = data.event.__dict__ if hasattr(data.event, '__dict__') else {}
    asyncio.create_task(handle_card_callback(event_dict))


async def main():
    """启动飞书长连接客户端"""
    settings = get_settings()

    log.info("starting feishu connector...")
    log.info("app_id: %s", settings.feishu_app_id)

    # 创建飞书客户端
    client = lark.Client.builder() \
        .app_id(settings.feishu_app_id) \
        .app_secret(settings.feishu_app_secret) \
        .log_level(lark.LogLevel.DEBUG) \
        .build()

    # 创建事件处理器
    handler = lark.EventDispatcherHandler.builder() \
        .register_p2_im_message_receive_v1(do_p2_im_message_receive_v1) \
        .register_p2_card_action_trigger(do_p2_card_action_trigger) \
        .build()

    # 启动长连接
    client.ws.start(handler)

    log.info("feishu connector started, waiting for events...")

    # 保持运行
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        log.info("shutting down...")


if __name__ == "__main__":
    asyncio.run(main())

