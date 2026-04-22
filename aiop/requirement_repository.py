"""需求索引数据访问层"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from aiop.db import get_db_connection

log = logging.getLogger(__name__)


class RequirementIndex(BaseModel):
    req_id: str
    project_id: str
    workflow_id: str
    title: str
    created_by: str
    created_at: datetime
    updated_at: datetime
    lifecycle_state: str = "draft"
    current_phase: str = "P0"
    cost_used_usd: float = 0.0
    cost_cap_usd: float = 20.0
    risk_level: str = "low"
    prd_path: Optional[str] = None
    commit_sha: Optional[str] = None
    commit_url: Optional[str] = None
    summary: Optional[str] = None
    ac_count: int = 0


class RequirementRepository:
    """需求索引数据访问"""

    @staticmethod
    async def create(
        req_id: str,
        project_id: str,
        workflow_id: str,
        title: str,
        created_by: str,
        cost_cap_usd: float = 20.0,
    ) -> RequirementIndex:
        """创建需求索引"""
        async with get_db_connection() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO requirements (req_id, project_id, workflow_id, title, created_by, cost_cap_usd)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING *
                """,
                req_id,
                project_id,
                workflow_id,
                title,
                created_by,
                cost_cap_usd,
            )
            log.info("created requirement index: %s", req_id)
            return RequirementIndex(**dict(row))

    @staticmethod
    async def get(req_id: str) -> Optional[RequirementIndex]:
        """获取需求索引"""
        async with get_db_connection() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM requirements WHERE req_id = $1",
                req_id,
            )
            if row:
                return RequirementIndex(**dict(row))
            return None

    @staticmethod
    async def get_by_workflow_id(workflow_id: str) -> Optional[RequirementIndex]:
        """通过 workflow_id 获取需求索引"""
        async with get_db_connection() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM requirements WHERE workflow_id = $1",
                workflow_id,
            )
            if row:
                return RequirementIndex(**dict(row))
            return None

    @staticmethod
    async def update_state(
        req_id: str,
        lifecycle_state: Optional[str] = None,
        current_phase: Optional[str] = None,
        cost_used_usd: Optional[float] = None,
        risk_level: Optional[str] = None,
        summary: Optional[str] = None,
    ) -> None:
        """更新需求状态"""
        async with get_db_connection() as conn:
            updates = []
            params = []
            param_idx = 2

            if lifecycle_state is not None:
                updates.append(f"lifecycle_state = ${param_idx}")
                params.append(lifecycle_state)
                param_idx += 1

            if current_phase is not None:
                updates.append(f"current_phase = ${param_idx}")
                params.append(current_phase)
                param_idx += 1

            if cost_used_usd is not None:
                updates.append(f"cost_used_usd = ${param_idx}")
                params.append(cost_used_usd)
                param_idx += 1

            if risk_level is not None:
                updates.append(f"risk_level = ${param_idx}")
                params.append(risk_level)
                param_idx += 1

            if summary is not None:
                updates.append(f"summary = ${param_idx}")
                params.append(summary)
                param_idx += 1

            if updates:
                query = f"UPDATE requirements SET {', '.join(updates)} WHERE req_id = $1"
                await conn.execute(query, req_id, *params)
                log.info("updated requirement state: %s", req_id)

    @staticmethod
    async def update_deliverables(
        req_id: str,
        prd_path: Optional[str] = None,
        commit_sha: Optional[str] = None,
        commit_url: Optional[str] = None,
        ac_count: Optional[int] = None,
    ) -> None:
        """更新需求交付物"""
        async with get_db_connection() as conn:
            updates = []
            params = []
            param_idx = 2

            if prd_path is not None:
                updates.append(f"prd_path = ${param_idx}")
                params.append(prd_path)
                param_idx += 1

            if commit_sha is not None:
                updates.append(f"commit_sha = ${param_idx}")
                params.append(commit_sha)
                param_idx += 1

            if commit_url is not None:
                updates.append(f"commit_url = ${param_idx}")
                params.append(commit_url)
                param_idx += 1

            if ac_count is not None:
                updates.append(f"ac_count = ${param_idx}")
                params.append(ac_count)
                param_idx += 1

            if updates:
                query = f"UPDATE requirements SET {', '.join(updates)} WHERE req_id = $1"
                await conn.execute(query, req_id, *params)
                log.info("updated requirement deliverables: %s", req_id)

    @staticmethod
    async def list_by_project(
        project_id: str,
        lifecycle_state: Optional[str] = None,
        limit: int = 50,
    ) -> list[RequirementIndex]:
        """按项目列出需求"""
        async with get_db_connection() as conn:
            if lifecycle_state:
                rows = await conn.fetch(
                    """
                    SELECT * FROM requirements
                    WHERE project_id = $1 AND lifecycle_state = $2
                    ORDER BY created_at DESC
                    LIMIT $3
                    """,
                    project_id,
                    lifecycle_state,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT * FROM requirements
                    WHERE project_id = $1
                    ORDER BY created_at DESC
                    LIMIT $2
                    """,
                    project_id,
                    limit,
                )
            return [RequirementIndex(**dict(row)) for row in rows]

    @staticmethod
    async def list_by_user(
        created_by: str,
        lifecycle_state: Optional[str] = None,
        limit: int = 50,
    ) -> list[RequirementIndex]:
        """按用户列出需求"""
        async with get_db_connection() as conn:
            if lifecycle_state:
                rows = await conn.fetch(
                    """
                    SELECT * FROM requirements
                    WHERE created_by = $1 AND lifecycle_state = $2
                    ORDER BY created_at DESC
                    LIMIT $3
                    """,
                    created_by,
                    lifecycle_state,
                    limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT * FROM requirements
                    WHERE created_by = $1
                    ORDER BY created_at DESC
                    LIMIT $2
                    """,
                    created_by,
                    limit,
                )
            return [RequirementIndex(**dict(row)) for row in rows]

    @staticmethod
    async def get_project_stats(project_id: str) -> dict:
        """获取项目统计信息"""
        async with get_db_connection() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) as total_count,
                    SUM(cost_used_usd) as total_cost,
                    COUNT(*) FILTER (WHERE lifecycle_state = 'in_progress') as in_progress_count,
                    COUNT(*) FILTER (WHERE lifecycle_state = 'approved') as approved_count,
                    COUNT(*) FILTER (WHERE lifecycle_state = 'released') as released_count
                FROM requirements
                WHERE project_id = $1
                """,
                project_id,
            )
            return dict(row) if row else {}
