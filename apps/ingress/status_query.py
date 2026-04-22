"""状态查询处理"""
from __future__ import annotations

import logging

from apps.ingress.project_query import ProjectQueryService
from apps.ingress.session_manager import SessionManager
from temporalio.client import WorkflowExecutionStatus

from aiop.temporal_client import get_temporal_client

log = logging.getLogger(__name__)


async def handle_status_query(text: str, chat_id: str) -> str:
    """处理飞书查询请求"""
    text_lower = text.lower().strip()

    # 项目列表查询
    if "项目列表" in text or "所有项目" in text:
        projects = await ProjectQueryService.list_projects(status="active")
        return await ProjectQueryService.format_project_list(projects)

    # 项目详情查询
    if "项目详情" in text or "项目概览" in text or "项目统计" in text:
        session = SessionManager.get_or_create(chat_id, user_id="")
        if not session.project_id:
            return "❌ 请先切换到具体项目\n提示：发送「切换到 [项目ID]」"

        summary = await ProjectQueryService.get_project_summary(session.project_id)
        return await ProjectQueryService.format_project_summary(summary)

    # 项目需求列表
    if "需求列表" in text or "项目需求" in text:
        session = SessionManager.get_or_create(chat_id, user_id="")
        if not session.project_id:
            return "❌ 请先切换到具体项目\n提示：发送「切换到 [项目ID]」"

        requirements = await ProjectQueryService.get_project_requirements(session.project_id)
        return await ProjectQueryService.format_requirement_list(requirements)

    # 当前任务状态（原有功能）
    if "当前" in text or "进度" in text or "状态" in text:
        session = SessionManager.get_or_create(chat_id, user_id="")
        if not session.active_workflow_id:
            return "❌ 暂无进行中的需求任务"

        return await query_task_status(session.active_workflow_id)

    return "❓ 支持的查询命令：\n• 项目列表\n• 项目详情\n• 需求列表\n• 当前进度"


async def query_task_status(workflow_id: str) -> str:
    """查询任务状态"""
    try:
        client = await get_temporal_client()
        handle = client.get_workflow_handle(workflow_id)

        desc = await handle.describe()
        status = desc.status

        if status == WorkflowExecutionStatus.RUNNING:
            result = await handle.query("status")
            phase = result.get("phase", "unknown")
            lifecycle = result.get("lifecycle_state", "unknown")
            cost = result.get("cost_used_usd", 0.0)

            return (
                f"📊 **任务进行中**\n"
                f"• 阶段: {phase}\n"
                f"• 状态: {lifecycle}\n"
                f"• 成本: ${cost:.4f}"
            )
        elif status == WorkflowExecutionStatus.COMPLETED:
            return "✅ 任务已完成"
        elif status == WorkflowExecutionStatus.FAILED:
            return "❌ 任务执行失败"
        else:
            return f"ℹ️ 任务状态: {status.name}"

    except Exception as e:
        log.error("failed to query task status: %s", e)
        return f"❌ 查询失败: {str(e)}"
