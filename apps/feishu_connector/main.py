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
from apps.ingress.status_query import handle_status_query
from apps.ingress.temporal_client import get_temporal_client
from aiop.types import RequirementInput

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

session_manager = SessionManager()


async def handle_message_event(event):
    """处理接收消息事件"""
    try:
        # 解析消息内容（event 是 lark SDK 对象，不是字典）
        message = event.message
        sender = event.sender

        chat_id = message.chat_id
        message_id = message.message_id
        content = json.loads(message.content)
        text = content.get("text", "").strip()

        sender_id = sender.sender_id.open_id or "unknown"

        log.info(
            "received message from %s in chat %s: %s",
            sender_id,
            chat_id,
            text[:50],
        )

        if not text:
            return

        # 获取或创建会话
        session = session_manager.get_or_create(chat_id, sender_id)
        session.add_message("user", text)

        # 检查是否是项目切换命令
        if "切换到" in text or "切换项目" in text:
            # 提取项目ID
            import re
            match = re.search(r'切换到?\s*([a-zA-Z0-9_-]+)', text)
            if match:
                project_id = match.group(1)
                session.project_id = project_id
                await send_feishu_message(chat_id, f"✅ 已切换到项目: {project_id}")
                return
            else:
                await send_feishu_message(chat_id, "❌ 请指定项目ID，例如：切换到 HealthAssit")
                return

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
            # 检查是否已设置项目
            if not session.project_id:
                await send_feishu_message(
                    chat_id,
                    "❌ 请先切换到具体项目\n提示：发送「切换到 [项目ID]」\n例如：切换到 HealthAssit"
                )
                return

            reply = "收到需求，正在分析和生成 PRD，请稍候..."
            await send_feishu_message(chat_id, reply)

            # 启动 workflow
            settings = get_settings()
            client = await get_temporal_client()

            req_id = f"req-{message_id}"
            workflow_input = RequirementInput(
                req_id=req_id,
                title=text[:100],  # 使用前100字符作为标题
                raw_text=text,
                created_by=sender_id,
                chat_id=chat_id,
                repo_url=settings.healthassit_repo,
                branch=settings.healthassit_default_branch,
                project_id=session.project_id,  # 使用 session 中的项目ID
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
            reply = await handle_status_query(text, chat_id)
            session.add_message("assistant", reply)
            await send_feishu_message(chat_id, reply)

        else:
            # 其他意图
            reply = "抱歉，我还不太理解你的意思，可以换个方式说吗？"
            await send_feishu_message(chat_id, reply)

    except Exception as e:
        log.error("failed to handle message event: %s", e, exc_info=True)


async def handle_card_callback(event):
    """处理消息卡片回调"""
    chat_id = None
    try:
        # event 是 lark SDK 对象
        action = event.action
        value = json.loads(action.value) if isinstance(action.value, str) else action.value

        log.info("received card callback: %s", value)

        # 解析回调数据
        action_type = value.get("action")
        workflow_id = value.get("workflow_id")
        chat_id = event.context.open_chat_id if hasattr(event, 'context') else None

        if not workflow_id:
            log.warning("card callback missing workflow_id")
            if chat_id:
                await send_feishu_message(chat_id, "❌ 操作失败：缺少工作流ID")
            return

        # 发送信号到 workflow
        client = await get_temporal_client()
        handle = client.get_workflow_handle(workflow_id)

        # 检查 workflow 状态
        try:
            desc = await handle.describe()
            workflow_status = desc.status

            # 如果 workflow 已完成或取消，不能再发送信号
            if workflow_status in ["COMPLETED", "FAILED", "CANCELED", "TERMINATED", "TIMED_OUT"]:
                log.warning("workflow %s is in %s state, cannot send signal", workflow_id, workflow_status)
                if chat_id:
                    await send_feishu_message(
                        chat_id,
                        f"❌ 操作失败：该需求已处于 {workflow_status} 状态，无法再修改"
                    )
                return
        except Exception as e:
            log.error("failed to describe workflow %s: %s", workflow_id, e)
            if chat_id:
                await send_feishu_message(chat_id, "❌ 操作失败：无法查询工作流状态")
            return

        if action_type == "p0_confirm":
            await handle.signal("p0_confirm")
            log.info("sent signal p0_confirm to workflow %s", workflow_id)
            if chat_id:
                await send_feishu_message(chat_id, "✅ 已确认需求，开始生成 PRD")

        elif action_type == "p0_revise":
            await handle.signal("p0_revise")
            log.info("sent signal p0_revise to workflow %s", workflow_id)
            if chat_id:
                await send_feishu_message(chat_id, "✅ 已标记为需要修改，请重新描述需求")

        elif action_type == "p1_approve":
            await handle.signal("p1_approve")
            log.info("sent signal p1_approve to workflow %s", workflow_id)
            if chat_id:
                await send_feishu_message(chat_id, "✅ 已批准 PRD，开始技术设计")

        elif action_type == "p1_reject":
            await handle.signal("p1_reject")
            log.info("sent signal p1_reject to workflow %s", workflow_id)
            if chat_id:
                await send_feishu_message(chat_id, "✅ 已拒绝 PRD，请提供修改意见")

        else:
            log.warning("unknown card action: %s", action_type)
            if chat_id:
                await send_feishu_message(chat_id, f"❌ 未知操作：{action_type}")

    except Exception as e:
        log.error("failed to handle card callback: %s", e, exc_info=True)
        if chat_id:
            await send_feishu_message(chat_id, f"❌ 操作失败：{str(e)}")


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
    asyncio.create_task(handle_message_event(data.event))


def do_p2_card_action_trigger(data: lark.P2CardActionTrigger) -> None:
    """处理卡片回调事件"""
    log.info("received card.action.trigger event")
    asyncio.create_task(handle_card_callback(data.event))


def main():
    """启动飞书长连接客户端"""
    settings = get_settings()

    log.info("starting feishu connector...")
    log.info("app_id: %s", settings.feishu_app_id)

    # 创建事件处理器
    handler = lark.EventDispatcherHandler.builder(
        encrypt_key=settings.feishu_encrypt_key or "",
        verification_token=settings.feishu_verification_token,
    ) \
        .register_p2_im_message_receive_v1(do_p2_im_message_receive_v1) \
        .register_p2_card_action_trigger(do_p2_card_action_trigger) \
        .build()

    # 创建 WebSocket 客户端并启动长连接
    ws_client = lark.ws.Client(
        app_id=settings.feishu_app_id,
        app_secret=settings.feishu_app_secret,
        event_handler=handler,
        log_level=lark.LogLevel.DEBUG,
    )

    log.info("feishu connector started, waiting for events...")

    # 启动长连接（阻塞调用）
    ws_client.start()


if __name__ == "__main__":
    main()

