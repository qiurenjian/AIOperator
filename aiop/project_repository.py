"""项目管理数据访问层"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from aiop.db import get_db_connection

log = logging.getLogger(__name__)


class Project(BaseModel):
    project_id: str
    name: str
    description: Optional[str] = None
    repo_url: Optional[str] = None
    default_branch: str = "main"
    created_by: str
    created_at: datetime
    updated_at: datetime
    status: str = "active"
    total_requirements: int = 0
    total_cost_usd: float = 0.0


class ProjectRepository:
    """项目数据访问"""

    @staticmethod
    async def create(
        project_id: str,
        name: str,
        created_by: str,
        description: Optional[str] = None,
        repo_url: Optional[str] = None,
        default_branch: str = "main",
    ) -> Project:
        """创建项目"""
        async with get_db_connection() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO projects (project_id, name, description, repo_url, default_branch, created_by)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING *
                """,
                project_id,
                name,
                description,
                repo_url,
                default_branch,
                created_by,
            )
            log.info("created project: %s", project_id)
            return Project(**dict(row))

    @staticmethod
    async def get(project_id: str) -> Optional[Project]:
        """获取项目"""
        async with get_db_connection() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM projects WHERE project_id = $1",
                project_id,
            )
            if row:
                return Project(**dict(row))
            return None

    @staticmethod
    async def list_all(status: Optional[str] = None) -> list[Project]:
        """列出所有项目"""
        async with get_db_connection() as conn:
            if status:
                rows = await conn.fetch(
                    "SELECT * FROM projects WHERE status = $1 ORDER BY created_at DESC",
                    status,
                )
            else:
                rows = await conn.fetch(
                    "SELECT * FROM projects ORDER BY created_at DESC"
                )
            return [Project(**dict(row)) for row in rows]

    @staticmethod
    async def update_stats(project_id: str, total_requirements: int, total_cost_usd: float) -> None:
        """更新项目统计信息"""
        async with get_db_connection() as conn:
            await conn.execute(
                """
                UPDATE projects
                SET total_requirements = $2, total_cost_usd = $3
                WHERE project_id = $1
                """,
                project_id,
                total_requirements,
                total_cost_usd,
            )
            log.info("updated project stats: %s", project_id)

    @staticmethod
    async def archive(project_id: str) -> None:
        """归档项目"""
        async with get_db_connection() as conn:
            await conn.execute(
                "UPDATE projects SET status = 'archived' WHERE project_id = $1",
                project_id,
            )
            log.info("archived project: %s", project_id)
