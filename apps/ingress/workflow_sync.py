"""Workflow 状态同步 - 优化版本

优化点：
1. 添加超时控制
2. 添加缓存机制（避免频繁查询）
3. 改进错误处理
4. 添加状态变化通知
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from temporalio.client import WorkflowFailureError, RPCError

from apps.ingress.conversation_state import ConversationPhase
from apps.ingress.session_manager import Session
from apps.ingress.temporal_client import get_temporal_client

log = logging.getLogger(__name__)

# 状态缓存（简单实现，生产环境应使用 Redis）
_status_cache: dict[str, tuple[dict, float]] = {}
_CACHE_TTL = 10.0  # 10 秒缓存


async def sync_workflow_to_session(
    session: Session,
    force_refresh: bool = False,
) -> bool:
    """
    同步 workflow 状态到会话

    参数：
        session: 会话对象
        force_refresh: 强制刷新，忽略缓存

    返回：是否有状态更新
    """
    if not session.conversation.workflow_id:
        return False

    workflow_id = session.conversation.workflow_id

    # 检查缓存
    if not force_refresh and workflow_id in _status_cache:
        cached_status, cached_time = _status_cache[workflow_id]
        if time.time() - cached_time < _CACHE_TTL:
            log.debug("using cached workflow status for %s", workflow_id)
            return _update_session_from_status(session, cached_status)

    try:
        client = await get_temporal_client()
        handle = client.get_workflow_handle(workflow_id)

        # 设置查询超时
        status = await handle.query("status", timeout=5.0)

        # 更新缓存
        _status_cache[workflow_id] = (status, time.time())

        return _update_session_from_status(session, status)

    except WorkflowFailureError as e:
        log.error("workflow %s failed: %s", workflow_id, e)
        # Workflow 失败，回到空闲状态
        if session.conversation.phase != ConversationPhase.IDLE:
            session.conversation.update_phase(ConversationPhase.IDLE)
            return True
        return False

    except RPCError as e:
        log.error("temporal RPC error for workflow %s: %s", workflow_id, e)
        return False

    except Exception as e:
        log.error("failed to sync workflow state: %s", e, exc_info=True)
        return False


def _update_session_from_status(session: Session, status: dict) -> bool:
    """
    根据 workflow 状态更新会话阶段

    返回：是否有状态更新
    """
    workflow_phase = status.get("phase", "")
    lifecycle_state = status.get("lifecycle_state", "")

    updated = False

    # 如果 workflow 在 P1 阶段且 PRD 已生成，进入 PRD 审查阶段
    if workflow_phase == "P1" and lifecycle_state == "in_progress":
        if session.conversation.phase != ConversationPhase.PRD_REVIEW:
            session.conversation.update_phase(ConversationPhase.PRD_REVIEW)

            # 保存 PRD 摘要到会话
            captured = status.get("captured")
            if captured:
                summary = captured.get("summary", "")
                # 获取验收条件数量
                prd_result = status.get("prd")
                if prd_result and isinstance(prd_result, dict):
                    ac_count = prd_result.get("ac_count", 0)
                else:
                    ac_count = "N/A"
                session.conversation.prd_content = f"{summary}\n验收条件：{ac_count} 条"

            updated = True
            log.info("synced workflow state: phase=%s -> PRD_REVIEW", workflow_phase)

    # 如果 workflow 已完成，进入设计讨论阶段
    elif workflow_phase == "P1-DONE" and lifecycle_state == "approved":
        if session.conversation.phase != ConversationPhase.DESIGN_DISCUSSION:
            session.conversation.update_phase(ConversationPhase.DESIGN_DISCUSSION)
            updated = True
            log.info("synced workflow state: phase=%s -> DESIGN_DISCUSSION", workflow_phase)

    # 如果 workflow 被取消，回到空闲状态
    elif lifecycle_state in ["cancelled", "revision_requested"]:
        if session.conversation.phase != ConversationPhase.IDLE:
            session.conversation.update_phase(ConversationPhase.IDLE)
            updated = True
            log.info("synced workflow state: lifecycle=%s -> IDLE", lifecycle_state)

    return updated


def clear_workflow_cache(workflow_id: str) -> None:
    """清除指定 workflow 的缓存"""
    if workflow_id in _status_cache:
        del _status_cache[workflow_id]
        log.debug("cleared cache for workflow %s", workflow_id)
