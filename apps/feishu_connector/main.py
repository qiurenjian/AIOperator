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
from apps.ingress.conversation_state import ConversationPhase
from apps.ingress.intent_classifier import IntentType, classify_intent
from apps.ingress.prd_reviewer import review_prd, generate_prd_revision_request
from apps.ingress.requirement_clarifier import clarify_requirement, generate_requirement_summary
from apps.ingress.session_manager import SessionManager
from apps.ingress.status_query import query_task_status, query_workflow_detail
from apps.ingress.temporal_client import get_temporal_client
from apps.ingress.workflow_sync import sync_workflow_to_session
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

        # 同步 workflow 状态到会话（如果有关联的 workflow）
        if session.conversation.workflow_id:
            state_updated = await sync_workflow_to_session(session)
            if state_updated:
                log.info("workflow state synced for chat_id=%s", chat_id)

        # 检查当前会话阶段
        phase = session.conversation.phase

        # 如果在需求澄清阶段，继续澄清对话
        if phase == ConversationPhase.REQUIREMENT_CLARIFYING:
            result = await clarify_requirement(text, session)
            reply = result["response"]
            session.add_message("assistant", reply)
            await send_feishu_message(chat_id, reply)

            # 如果需求已足够清晰，进入确认阶段
            if result.get("is_ready", False):
                session.conversation.update_phase(ConversationPhase.REQUIREMENT_CONFIRMED)

                # 生成需求摘要
                summary = await generate_requirement_summary(session)
                session.conversation.requirement_draft = summary

                # 询问是否开始生成 PRD
                confirm_msg = "\n\n✅ 需求已明确。是否开始生成 PRD？（回复「确认」或「开始」）"
                await send_feishu_message(chat_id, confirm_msg)
                session.add_message("assistant", confirm_msg)

            return

        # 如果在需求确认阶段，等待用户确认
        if phase == ConversationPhase.REQUIREMENT_CONFIRMED:
            if text in ["确认", "开始", "好的", "可以", "是的", "yes", "ok"]:
                # 启动 workflow
                settings = get_settings()
                client = await get_temporal_client()

                req_id = f"req-{message_id}"
                workflow_input = RequirementInput(
                    req_id=req_id,
                    title=session.conversation.requirement_draft[:100],
                    raw_text=session.conversation.requirement_draft,
                    created_by=sender_id,
                    chat_id=chat_id,
                    repo_url=settings.healthassit_repo,
                    branch=settings.healthassit_default_branch,
                )

                workflow_id = f"req-{chat_id}-{message_id}"
                session.conversation.workflow_id = workflow_id
                session.conversation.req_id = req_id

                await client.start_workflow(
                    "RequirementWorkflow",
                    workflow_input,
                    id=workflow_id,
                    task_queue="lite",
                )

                log.info("started workflow %s for requirement", workflow_id)

                reply = "✅ 已启动 PRD 生成流程，请稍候..."
                await send_feishu_message(chat_id, reply)
                session.add_message("assistant", reply)

                session.conversation.update_phase(ConversationPhase.PRD_REVIEW)
                return
            else:
                # 用户想继续修改需求
                session.conversation.update_phase(ConversationPhase.REQUIREMENT_CLARIFYING)
                reply = "好的，请告诉我需要调整的地方。"
                await send_feishu_message(chat_id, reply)
                session.add_message("assistant", reply)
                return

        # 如果在 PRD 审查阶段，处理审查对话
        if phase == ConversationPhase.PRD_REVIEW:
            # 获取 PRD 摘要（从会话上下文中提取）
            prd_summary = session.conversation.prd_content or "PRD 生成中..."

            result = await review_prd(text, session, prd_summary)
            reply = result["response"]
            session.add_message("assistant", reply)
            await send_feishu_message(chat_id, reply)

            action = result.get("action", "discuss")

            if action == "approve":
                # 用户批准 PRD，发送信号到 workflow
                if session.conversation.workflow_id:
                    client = await get_temporal_client()
                    handle = client.get_workflow_handle(session.conversation.workflow_id)
                    await handle.signal("p1_approve")
                    log.info("sent p1_approve signal to workflow %s", session.conversation.workflow_id)

                    confirm_msg = "\n\n✅ 已批准 PRD，正在提交到代码库..."
                    await send_feishu_message(chat_id, confirm_msg)
                    session.add_message("assistant", confirm_msg)

                    session.conversation.update_phase(ConversationPhase.DESIGN_DISCUSSION)

            elif action == "revise":
                # 用户要求修改 PRD
                feedback_items = result.get("feedback_items", [])
                session.conversation.prd_feedback.extend(feedback_items)

                # 生成修改请求
                revision_request = await generate_prd_revision_request(session)

                # 发送信号到 workflow（目前 workflow 不支持修改，先拒绝）
                if session.conversation.workflow_id:
                    client = await get_temporal_client()
                    handle = client.get_workflow_handle(session.conversation.workflow_id)
                    await handle.signal("p1_reject")
                    log.info("sent p1_reject signal to workflow %s", session.conversation.workflow_id)

                    reject_msg = "\n\n❌ 已拒绝当前 PRD。修改建议已记录，需要重新提交需求。"
                    await send_feishu_message(chat_id, reject_msg)
                    session.add_message("assistant", reject_msg)

                    session.conversation.update_phase(ConversationPhase.IDLE)

            return

        # 空闲状态：进行意图分类
        intent = await classify_intent(text, session.get_recent_context(n=5))
        log.info("classified intent: %s (%.2f)", intent.type, intent.confidence)

        # 根据意图处理
        if intent.type == IntentType.CHAT:
            # 对话模式
            reply = await handle_chat(text, session)
            session.add_message("assistant", reply)
            await send_feishu_message(chat_id, reply)

        elif intent.type == IntentType.REQUIREMENT:
            # 进入需求澄清阶段
            session.conversation.update_phase(ConversationPhase.REQUIREMENT_CLARIFYING)

            result = await clarify_requirement(text, session)
            reply = result["response"]
            session.add_message("assistant", reply)
            await send_feishu_message(chat_id, reply)

            # 如果首次就足够清晰，直接进入确认阶段
            if result.get("is_ready", False):
                session.conversation.update_phase(ConversationPhase.REQUIREMENT_CONFIRMED)
                summary = await generate_requirement_summary(session)
                session.conversation.requirement_draft = summary

                confirm_msg = "\n\n✅ 需求已明确。是否开始生成 PRD？（回复「确认」或「开始」）"
                await send_feishu_message(chat_id, confirm_msg)
                session.add_message("assistant", confirm_msg)

        elif intent.type == IntentType.QUERY:
            # 查询模式 - 检查是否是状态查询
            if any(keyword in text for keyword in ["状态", "进度", "进展", "怎么样了", "到哪了"]):
                status_text = await query_task_status(session)
                await send_feishu_message(chat_id, status_text)
                session.add_message("assistant", status_text)
            elif text.startswith("req-"):
                # 查询特定 workflow
                detail_text = await query_workflow_detail(text.strip())
                await send_feishu_message(chat_id, detail_text)
                session.add_message("assistant", detail_text)
            else:
                reply = "查询功能开发中，敬请期待..."
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

