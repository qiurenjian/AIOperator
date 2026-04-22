"""任务状态查询处理器 - 优化版本

优化点：
1. 添加超时控制
2. 改进错误处理和降级策略
3. 优化状态显示格式
4. 添加更多有用的状态信息
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from temporalio.client import WorkflowFailureError, RPCError

from apps.ingress.conversation_state import ConversationPhase
from apps.ingress.session_manager import Session, SessionManager
from apps.ingress.temporal_client import get_temporal_client

log = logging.getLogger(__name__)


async def handle_status_query(text: str, chat_id: str) -> str:
    """处理飞书查询请求"""
    session = SessionManager.get_or_create(chat_id)

    if not session.conversation.workflow_id:
        return "暂无进行中的需求任务"

    return await query_task_status(session, timeout=5.0)


PHASE_DISPLAY_NAMES = {
    ConversationPhase.IDLE: "空闲",
    ConversationPhase.REQUIREMENT_CLARIFYING: "需求澄清中",
    ConversationPhase.REQUIREMENT_CONFIRMED: "需求已确认，待启动",
    ConversationPhase.PRD_REVIEW: "PRD 审查中",
    ConversationPhase.DESIGN_DISCUSSION: "技术方案讨论中",
    ConversationPhase.IMPLEMENTATION: "实现中",
    ConversationPhase.CODE_REVIEW: "代码审查中",
}


async def query_task_status(session: Session, timeout: float = 5.0) -> str:
    """
    查询当前任务状态

    参数：
        session: 会话对象
        timeout: 查询超时时间（秒）

    返回：格式化的状态信息文本
    """
    phase = session.conversation.phase
    phase_name = PHASE_DISPLAY_NAMES.get(phase, str(phase))

    status_lines = [
        f"📊 **当前状态**：{phase_name}",
    ]

    # 如果有关联的 workflow，查询 workflow 状态
    if session.conversation.workflow_id:
        workflow_status = await _query_workflow_status(
            session.conversation.workflow_id,
            timeout=timeout,
        )

        if workflow_status:
            status_lines.extend(_format_workflow_status(workflow_status))
        else:
            status_lines.append("⚠️ 无法查询 workflow 状态")

    # 显示会话信息
    status_lines.extend(_format_session_info(session))

    return "\n".join(status_lines)


async def _query_workflow_status(
    workflow_id: str,
    timeout: float = 5.0,
) -> Optional[dict]:
    """
    查询 workflow 状态

    返回：workflow 状态字典，失败时返回 None
    """
    try:
        client = await get_temporal_client()
        handle = client.get_workflow_handle(workflow_id)
        status = await handle.query("status", timeout=timeout)
        return status

    except WorkflowFailureError as e:
        log.error("workflow %s failed: %s", workflow_id, e)
        return None

    except RPCError as e:
        log.error("temporal RPC error for workflow %s: %s", workflow_id, e)
        return None

    except Exception as e:
        log.error("failed to query workflow status: %s", e, exc_info=True)
        return None


def _format_workflow_status(status: dict) -> list[str]:
    """格式化 workflow 状态信息"""
    lines = []

    workflow_id = status.get("workflow_id", "N/A")
    lines.append(f"🔄 **Workflow ID**：`{workflow_id}`")

    req_id = status.get("req_id", "N/A")
    lines.append(f"📝 **需求 ID**：`{req_id}`")

    workflow_phase = status.get("phase", "unknown")
    lines.append(f"⚙️ **Workflow 阶段**：{workflow_phase}")

    lifecycle_state = status.get("lifecycle_state", "unknown")
    lines.append(f"🏷️ **生命周期**：{lifecycle_state}")

    # 成本信息
    cost = status.get("cost_used_usd", 0.0)
    if cost > 0:
        lines.append(f"💰 **已用成本**：${cost:.4f}")

    # PRD 信息
    prd_path = status.get("prd_path")
    if prd_path:
        lines.append(f"📄 **PRD 路径**：`{prd_path}`")

    # 提交信息
    commit_sha = status.get("commit_sha")
    if commit_sha:
        lines.append(f"✅ **提交 SHA**：`{commit_sha[:8]}`")

    # 需求捕获信息
    captured = status.get("captured")
    if captured:
        summary = captured.get("summary", "")
        if summary:
            lines.append(f"📥 **需求摘要**：{summary[:100]}...")

    return lines


def _format_session_info(session: Session) -> list[str]:
    """格式化会话信息"""
    lines = []

    phase = session.conversation.phase

    # 需求澄清阶段信息
    if phase == ConversationPhase.REQUIREMENT_CLARIFYING:
        rounds = session.conversation.clarification_rounds
        lines.append(f"🔄 **澄清轮次**：{rounds}")

    # PRD 审查阶段信息
    if phase == ConversationPhase.PRD_REVIEW:
        feedback_count = len(session.conversation.prd_feedback)
        if feedback_count > 0:
            lines.append(f"💬 **反馈条数**：{feedback_count}")

    # 会话活跃时间
    active_duration = (session.last_active - session.created_at).total_seconds() / 60
    lines.append(f"⏱️ **会话时长**：{active_duration:.1f} 分钟")

    # 消息数量
    message_count = len(session.context)
    lines.append(f"💬 **消息数量**：{message_count}")

    return lines


async def query_workflow_detail(workflow_id: str, timeout: float = 5.0) -> str:
    """
    查询指定 workflow 的详细状态

    用于用户直接查询某个 workflow ID

    参数：
        workflow_id: workflow ID
        timeout: 查询超时时间（秒）

    返回：格式化的详细状态信息
    """
    status = await _query_workflow_status(workflow_id, timeout=timeout)

    if not status:
        return f"❌ 无法查询 workflow `{workflow_id}`"

    lines = [
        f"🔄 **Workflow ID**：`{workflow_id}`",
        f"⚙️ **阶段**：{status.get('phase', 'unknown')}",
        f"🏷️ **生命周期**：{status.get('lifecycle_state', 'unknown')}",
    ]

    cost = status.get("cost_used_usd", 0.0)
    if cost > 0:
        lines.append(f"💰 **已用成本**：${cost:.4f}")

    captured = status.get("captured")
    if captured:
        lines.append(f"\n📥 **需求捕获**：")
        lines.append(f"  - 摘要：{captured.get('summary', 'N/A')}")
        lines.append(f"  - 风险：{captured.get('suggested_risk', 'N/A')}")

    prd_path = status.get("prd_path")
    if prd_path:
        lines.append(f"\n📄 **PRD**：`{prd_path}`")

    commit_sha = status.get("commit_sha")
    if commit_sha:
        lines.append(f"\n✅ **提交**：`{commit_sha[:8]}`")

    return "\n".join(lines)
