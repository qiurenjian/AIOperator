"""项目和需求查询服务"""
from __future__ import annotations

import logging
from typing import Optional

from aiop.project_repository import Project, ProjectRepository
from aiop.requirement_repository import RequirementIndex, RequirementRepository

log = logging.getLogger(__name__)


class ProjectQueryService:
    """项目查询服务"""

    @staticmethod
    async def list_projects(status: Optional[str] = None) -> list[Project]:
        """列出所有项目"""
        return await ProjectRepository.list_all(status=status)

    @staticmethod
    async def get_project(project_id: str) -> Optional[Project]:
        """获取项目详情"""
        return await ProjectRepository.get(project_id)

    @staticmethod
    async def get_project_requirements(
        project_id: str,
        lifecycle_state: Optional[str] = None,
        limit: int = 50,
    ) -> list[RequirementIndex]:
        """获取项目的需求列表"""
        return await RequirementRepository.list_by_project(
            project_id=project_id,
            lifecycle_state=lifecycle_state,
            limit=limit,
        )

    @staticmethod
    async def get_project_summary(project_id: str) -> dict:
        """获取项目摘要信息"""
        project = await ProjectRepository.get(project_id)
        if not project:
            return {"error": "项目不存在"}

        stats = await RequirementRepository.get_project_stats(project_id)

        return {
            "project": project.model_dump(),
            "stats": stats,
        }

    @staticmethod
    async def get_user_requirements(
        created_by: str,
        lifecycle_state: Optional[str] = None,
        limit: int = 50,
    ) -> list[RequirementIndex]:
        """获取用户的需求列表"""
        return await RequirementRepository.list_by_user(
            created_by=created_by,
            lifecycle_state=lifecycle_state,
            limit=limit,
        )

    @staticmethod
    async def format_project_list(projects: list[Project]) -> str:
        """格式化项目列表为文本"""
        if not projects:
            return "暂无项目"

        lines = ["📋 **项目列表**\n"]
        for p in projects:
            lines.append(
                f"• **{p.name}** (`{p.project_id}`)\n"
                f"  需求数: {p.total_requirements} | 总成本: ${p.total_cost_usd:.2f}\n"
            )
        return "\n".join(lines)

    @staticmethod
    async def format_requirement_list(requirements: list[RequirementIndex]) -> str:
        """格式化需求列表为文本"""
        if not requirements:
            return "暂无需求"

        lines = ["📝 **需求列表**\n"]
        for req in requirements:
            status_emoji = {
                "draft": "📄",
                "in_progress": "⏳",
                "captured": "✅",
                "prd_generated": "📋",
                "approved": "🎉",
                "released": "🚀",
                "cancelled": "❌",
            }.get(req.lifecycle_state, "❓")

            lines.append(
                f"{status_emoji} **{req.title}** (`{req.req_id}`)\n"
                f"  状态: {req.lifecycle_state} | 阶段: {req.current_phase} | 成本: ${req.cost_used_usd:.2f}\n"
            )
        return "\n".join(lines)

    @staticmethod
    async def format_project_summary(summary: dict) -> str:
        """格式化项目摘要为文本"""
        if "error" in summary:
            return f"❌ {summary['error']}"

        project = summary["project"]
        stats = summary["stats"]

        lines = [
            f"📊 **{project['name']}** 项目概览\n",
            f"🆔 项目ID: `{project['project_id']}`",
            f"📦 仓库: {project['repo_url'] or 'N/A'}",
            f"🌿 分支: {project['default_branch'] or 'N/A'}",
            f"\n📈 **统计信息**",
            f"• 总需求数: {stats.get('total_count', 0)}",
            f"• 进行中: {stats.get('in_progress_count', 0)}",
            f"• 已批准: {stats.get('approved_count', 0)}",
            f"• 已发布: {stats.get('released_count', 0)}",
            f"• 总成本: ${stats.get('total_cost') or 0.0:.2f}",
        ]
        return "\n".join(lines)
