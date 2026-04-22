"""需求索引同步 Activity"""
from __future__ import annotations

import logging

from temporalio import activity

from aiop.requirement_repository import RequirementRepository

log = logging.getLogger(__name__)


@activity.defn(name="sync_requirement_index_create")
async def sync_requirement_index_create(
    req_id: str,
    project_id: str,
    workflow_id: str,
    title: str,
    created_by: str,
    cost_cap_usd: float,
) -> None:
    """创建需求索引"""
    try:
        await RequirementRepository.create(
            req_id=req_id,
            project_id=project_id,
            workflow_id=workflow_id,
            title=title,
            created_by=created_by,
            cost_cap_usd=cost_cap_usd,
        )
        log.info("synced requirement index (create): %s", req_id)
    except Exception as e:
        log.error("failed to sync requirement index (create): %s - %s", req_id, e)
        raise


@activity.defn(name="sync_requirement_index_state")
async def sync_requirement_index_state(
    req_id: str,
    lifecycle_state: str | None = None,
    current_phase: str | None = None,
    cost_used_usd: float | None = None,
    risk_level: str | None = None,
    summary: str | None = None,
) -> None:
    """更新需求状态"""
    try:
        await RequirementRepository.update_state(
            req_id=req_id,
            lifecycle_state=lifecycle_state,
            current_phase=current_phase,
            cost_used_usd=cost_used_usd,
            risk_level=risk_level,
            summary=summary,
        )
        log.info("synced requirement index (state): %s", req_id)
    except Exception as e:
        log.error("failed to sync requirement index (state): %s - %s", req_id, e)
        raise


@activity.defn(name="sync_requirement_index_deliverables")
async def sync_requirement_index_deliverables(
    req_id: str,
    prd_path: str | None = None,
    commit_sha: str | None = None,
    commit_url: str | None = None,
    ac_count: int | None = None,
) -> None:
    """更新需求交付物"""
    try:
        await RequirementRepository.update_deliverables(
            req_id=req_id,
            prd_path=prd_path,
            commit_sha=commit_sha,
            commit_url=commit_url,
            ac_count=ac_count,
        )
        log.info("synced requirement index (deliverables): %s", req_id)
    except Exception as e:
        log.error("failed to sync requirement index (deliverables): %s - %s", req_id, e)
        raise
