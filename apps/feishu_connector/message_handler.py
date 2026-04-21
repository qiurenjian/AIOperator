"""飞书消息处理器 - 优化版本

优化点：
1. 统一错误处理和降级策略
2. 添加消息处理超时控制
3. 改进日志记录
4. 添加消息处理状态跟踪
5. 支持消息重试
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

from apps.feishu_connector.main import send_feishu_message
from apps.ingress.conversation_state import ConversationPhase
from apps.ingress.intent_classifier import classify_intent, IntentType
from apps.ingress.requirement_clarifier import (
    clarify_requirement,
    generate_requirement_summary,
)
from apps.ingress.prd_reviewer import review_prd, generate_prd_revision_request
from apps.ingress.status_query import query_task_status, query_workflow_detail
from apps.ingress.workflow_sync import sync_workflow_to_session
from apps.ingress.session_manager import Session, session_manager
from apps.ingress.temporal_client import get_temporal_client
from apps.ingress.chat_handler import handle_chat
from aiop.settings import get_settings
from workflows.requirement import RequirementInput

log = logging.getLogger(__name__)

# 消息处理超时时间（秒）
MESSAGE_TIMEOUT = 30.0


async def handle_message_with_timeout(
    chat_id: str,
    sender_id: str,
    message_id: str,
    text: str,
    timeout: float = MESSAGE_TIMEOUT,
) -> None:
    """
    处理消息（带超时控制）

    参数：
        chat_id: 聊天 ID
        sender_id: 发送者 ID
        message_id: 消息 ID
        text: 消息文本
        timeout: 超时时间（秒）
    """
    try:
        await asyncio.wait_for(
            handle_message(chat_id, sender_id, message_id, text),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        log.error("message handling timeout after %.1fs: chat_id=%s", timeout, chat_id)
        await send_feishu_message(
            chat_id,
            "⚠️ 处理超时，请稍后重试或联系管理员。",
        )
    except Exception as e:
        log.error("unexpected error in message handling: %s", e, exc_info=True)
        await send_feishu_message(
            chat_id,
            "❌ 处理失败，请稍后重试。",
        )


async def handle_message(
    chat_id: str,
    sender_id: str,
    message_id: str,
    text: str,
) -> None:
    """
    处理飞书消息

    参数：
        chat_id: 聊天 ID
        sender_id: 发送者 ID
        message_id: 消息 ID
        text: 消息文本
    """
    log.info(
        "handling message: chat_id=%s, sender_id=%s, text=%s",
        chat_id,
        sender_id,
        text[:50],
    )

    if not text or not text.strip():
        log.warning("received empty message, ignoring")
        return

    text = text.strip()

    # 获取或创建会话
    session = session_manager.get_or_create(chat_id, sender_id)
    session.add_message("user", text)

    # 同步 workflow 状态（如果有关联的 workflow）
    if session.conversation.workflow_id:
        try:
            state_updated = await sync_workflow_to_session(session)
            if state_updated:
                log.info("workflow state synced: chat_id=%s", chat_id)
        except Exception as e:
            log.error("failed to sync workflow state: %s", e)

    # 检查是否为状态查询（优先处理）
    if _is_status_query(text):
        await _handle_status_query(chat_id, session, text)
        return

    # 根据会话阶段路由消息
    phase = session.conversation.phase

    try:
        if phase == ConversationPhase.REQUIREMENT_CLARIFYING:
            await _handle_requirement_clarifying(chat_id, sender_id, message_id, text, session)

        elif phase == ConversationPhase.REQUIREMENT_CONFIRMED:
            await _handle_requirement_confirmed(chat_id, sender_id, message_id, text, session)

        elif phase == ConversationPhase.PRD_REVIEW:
            await _handle_prd_review(chat_id, text, session)

        elif phase == ConversationPhase.DESIGN_DISCUSSION:
            await _handle_design_discussion(chat_id, text, session)

        else:
            # 空闲状态：进行意图分类
            await _handle_idle_state(chat_id, sender_id, message_id, text, session)

    except Exception as e:
        log.error("error handling message in phase %s: %s", phase, e, exc_info=True)
        await send_feishu_message(
            chat_id,
            f"❌ 处理失败：{str(e)}\n\n请稍后重试或联系管理员。",
        )


def _is_status_query(text: str) -> bool:
    """判断是否为状态查询"""
    keywords = ["状态", "进度", "进展", "怎么样了", "到哪了", "任务", "workflow"]
    return any(keyword in text.lower() for keyword in keywords)


async def _handle_status_query(chat_id: str, session: Session, text: str) -> None:
    """处理状态查询"""
    try:
        # 检查是否查询特定 workflow
        if text.startswith("req-"):
            status_text = await query_workflow_detail(text.strip())
        else:
            status_text = await query_task_status(session)

        await send_feishu_message(chat_id, status_text)
        session.add_message("assistant", status_text)

    except Exception as e:
        log.error("failed to query status: %s", e, exc_info=True)
        await send_feishu_message(chat_id, "❌ 查询状态失败，请稍后重试。")


async def _handle_requirement_clarifying(
    chat_id: str,
    sender_id: str,
    message_id: str,
    text: str,
    session: Session,
) -> None:
    """处理需求澄清阶段"""
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


async def _handle_requirement_confirmed(
    chat_id: str,
    sender_id: str,
    message_id: str,
    text: str,
    session: Session,
) -> None:
    """处理需求确认阶段"""
    # 检查是否为确认关键词
    confirm_keywords = ["确认", "开始", "好的", "可以", "是的", "yes", "ok", "开始吧"]

    if any(keyword in text.lower() for keyword in confirm_keywords):
        # 启动 workflow
        await _start_requirement_workflow(chat_id, sender_id, message_id, session)
    else:
        # 用户想继续修改需求
        session.conversation.update_phase(ConversationPhase.REQUIREMENT_CLARIFYING)
        reply = "好的，请告诉我需要调整的地方。"
        await send_feishu_message(chat_id, reply)
        session.add_message("assistant", reply)


async def _start_requirement_workflow(
    chat_id: str,
    sender_id: str,
    message_id: str,
    session: Session,
) -> None:
    """启动需求处理 workflow"""
    try:
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

        reply = f"✅ 已启动 PRD 生成流程\n\n📝 需求 ID：`{req_id}`\n🔄 Workflow ID：`{workflow_id}`\n\n请稍候..."
        await send_feishu_message(chat_id, reply)
        session.add_message("assistant", reply)

        session.conversation.update_phase(ConversationPhase.PRD_REVIEW)

    except Exception as e:
        log.error("failed to start workflow: %s", e, exc_info=True)
        await send_feishu_message(
            chat_id,
            f"❌ 启动 workflow 失败：{str(e)}\n\n请稍后重试。",
        )


async def _handle_prd_review(chat_id: str, text: str, session: Session) -> None:
    """处理 PRD 审查阶段"""
    # 获取 PRD 摘要
    prd_summary = session.conversation.prd_content or "PRD 生成中..."

    result = await review_prd(text, session, prd_summary)
    reply = result["response"]

    session.add_message("assistant", reply)
    await send_feishu_message(chat_id, reply)

    action = result.get("action", "discuss")

    if action == "approve":
        await _approve_prd(chat_id, session)

    elif action == "revise":
        await _request_prd_revision(chat_id, session, result)


async def _approve_prd(chat_id: str, session: Session) -> None:
    """批准 PRD"""
    if not session.conversation.workflow_id:
        log.error("no workflow_id in session, cannot approve PRD")
        return

    try:
        client = await get_temporal_client()
        handle = client.get_workflow_handle(session.conversation.workflow_id)
        await handle.signal("p1_approve")

        log.info("sent p1_approve signal to workflow %s", session.conversation.workflow_id)

        confirm_msg = "\n\n✅ 已批准 PRD，正在提交到代码库..."
        await send_feishu_message(chat_id, confirm_msg)
        session.add_message("assistant", confirm_msg)

        session.conversation.update_phase(ConversationPhase.DESIGN_DISCUSSION)

    except Exception as e:
        log.error("failed to approve PRD: %s", e, exc_info=True)
        await send_feishu_message(chat_id, f"❌ 批准失败：{str(e)}")


async def _request_prd_revision(chat_id: str, session: Session, result: dict) -> None:
    """请求 PRD 修改"""
    feedback_items = result.get("feedback_items", [])
    session.conversation.prd_feedback.extend(feedback_items)

    # 生成修改请求
    revision_request = await generate_prd_revision_request(session)

    # 发送拒绝信号（目前 workflow 不支持修改）
    if session.conversation.workflow_id:
        try:
            client = await get_temporal_client()
            handle = client.get_workflow_handle(session.conversation.workflow_id)
            await handle.signal("p1_reject")

            log.info("sent p1_reject signal to workflow %s", session.conversation.workflow_id)

            reject_msg = "\n\n❌ 已拒绝当前 PRD。修改建议已记录，需要重新提交需求。"
            await send_feishu_message(chat_id, reject_msg)
            session.add_message("assistant", reject_msg)

            session.conversation.update_phase(ConversationPhase.IDLE)

        except Exception as e:
            log.error("failed to reject PRD: %s", e, exc_info=True)
            await send_feishu_message(chat_id, f"❌ 拒绝失败：{str(e)}")


async def _handle_design_discussion(chat_id: str, text: str, session: Session) -> None:
    """处理设计讨论阶段（暂未实现）"""
    reply = "设计讨论阶段暂未实现，敬请期待。"
    await send_feishu_message(chat_id, reply)
    session.add_message("assistant", reply)


async def _handle_idle_state(
    chat_id: str,
    sender_id: str,
    message_id: str,
    text: str,
    session: Session,
) -> None:
    """处理空闲状态（意图分类）"""
    # 进行意图分类
    intent = await classify_intent(text, session.get_recent_context(n=5))
    log.info("classified intent: %s (%.2f)", intent.type, intent.confidence)

    if intent.type == IntentType.REQUIREMENT:
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
        # 查询模式
        await _handle_status_query(chat_id, session, text)

    else:
        # 对话模式
        reply = await handle_chat(text, session)
        session.add_message("assistant", reply)
        await send_feishu_message(chat_id, reply)
