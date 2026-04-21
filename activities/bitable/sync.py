"""飞书多维表格同步 Activity

功能：
1. 同步需求到飞书表格
2. 更新需求状态
3. 更新交付物链接
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from temporalio import activity
from lark_oapi import Client
from lark_oapi.api.bitable.v1 import (
    CreateAppTableRecordRequest,
    CreateAppTableRecordRequestBody,
    UpdateAppTableRecordRequest,
    UpdateAppTableRecordRequestBody,
    ListAppTableRecordRequest,
)

from aiop.settings import get_settings

log = logging.getLogger(__name__)


async def _find_record_by_req_id(
    client: Client,
    app_token: str,
    table_id: str,
    req_id: str,
) -> Optional[dict]:
    """根据 req_id 查找记录"""
    try:
        # 使用筛选条件查询
        request = ListAppTableRecordRequest.builder() \
            .app_token(app_token) \
            .table_id(table_id) \
            .filter(f'CurrentValue.[req_id]="{req_id}"') \
            .build()

        response = client.bitable.v1.app_table_record.list(request)

        if not response.success():
            log.error("failed to list records: %s", response.msg)
            return None

        if response.data and response.data.items and len(response.data.items) > 0:
            item = response.data.items[0]
            return {
                "record_id": item.record_id,
                "fields": item.fields,
            }

        return None

    except Exception as e:
        log.error("failed to find record by req_id: %s", e, exc_info=True)
        return None


@activity.defn(name="bitable_sync_requirement")
async def bitable_sync_requirement(req_data: dict) -> dict:
    """
    同步需求到飞书表格

    参数：
        req_data: 需求数据
            - req_id: 需求 ID
            - title: 标题
            - project: 项目名称
            - created_by: 创建人
            - lifecycle_state: 生命周期状态
            - current_phase: 当前阶段
            - cost_used_usd: 已用成本
            - cost_cap_usd: 成本上限
            - priority: 优先级
            - risk_level: 风险等级
            - prd_doc_url: PRD 文档链接
            - design_doc_url: 设计文档链接
            - code_pr_url: 代码 PR 链接
            - created_at: 创建时间
            - updated_at: 更新时间

    返回：
        {
            "success": bool,
            "record_id": str,
            "action": "created" | "updated"
        }
    """
    settings = get_settings()

    activity.heartbeat({"req_id": req_data["req_id"], "stage": "connecting"})

    client = Client.builder() \
        .app_id(settings.feishu_app_id) \
        .app_secret(settings.feishu_app_secret) \
        .build()

    # 构建记录数据
    fields = {
        "req_id": req_data["req_id"],
        "title": req_data.get("title", ""),
        "project": req_data.get("project", "HealthAssit"),
        "created_by": req_data.get("created_by", ""),
        "lifecycle_state": req_data.get("lifecycle_state", ""),
        "current_phase": req_data.get("current_phase", ""),
        "cost_used_usd": req_data.get("cost_used_usd", 0.0),
        "created_at": req_data.get("created_at", datetime.now().isoformat()),
        "updated_at": req_data.get("updated_at", datetime.now().isoformat()),
    }

    # 可选字段
    if "cost_cap_usd" in req_data:
        fields["cost_cap_usd"] = req_data["cost_cap_usd"]
    if "priority" in req_data:
        fields["priority"] = req_data["priority"]
    if "risk_level" in req_data:
        fields["risk_level"] = req_data["risk_level"]
    if "prd_doc_url" in req_data:
        fields["prd_doc_url"] = req_data["prd_doc_url"]
    if "design_doc_url" in req_data:
        fields["design_doc_url"] = req_data["design_doc_url"]
    if "code_pr_url" in req_data:
        fields["code_pr_url"] = req_data["code_pr_url"]
    if "rework_count" in req_data:
        fields["rework_count"] = req_data["rework_count"]

    activity.heartbeat({"req_id": req_data["req_id"], "stage": "checking_existing"})

    # 检查记录是否存在
    existing = await _find_record_by_req_id(
        client,
        settings.feishu_bitable_app_token,
        settings.feishu_bitable_kanban_table_id,
        req_data["req_id"]
    )

    try:
        if existing:
            # 更新记录
            activity.heartbeat({"req_id": req_data["req_id"], "stage": "updating"})

            request = UpdateAppTableRecordRequest.builder() \
                .app_token(settings.feishu_bitable_app_token) \
                .table_id(settings.feishu_bitable_kanban_table_id) \
                .record_id(existing["record_id"]) \
                .request_body(
                    UpdateAppTableRecordRequestBody.builder()
                    .fields(fields)
                    .build()
                ) \
                .build()

            response = client.bitable.v1.app_table_record.update(request)

            if not response.success():
                raise Exception(f"Failed to update bitable record: {response.msg}")

            log.info("updated bitable record for req_id=%s", req_data["req_id"])

            return {
                "success": True,
                "record_id": existing["record_id"],
                "action": "updated",
            }

        else:
            # 创建记录
            activity.heartbeat({"req_id": req_data["req_id"], "stage": "creating"})

            request = CreateAppTableRecordRequest.builder() \
                .app_token(settings.feishu_bitable_app_token) \
                .table_id(settings.feishu_bitable_kanban_table_id) \
                .request_body(
                    CreateAppTableRecordRequestBody.builder()
                    .fields(fields)
                    .build()
                ) \
                .build()

            response = client.bitable.v1.app_table_record.create(request)

            if not response.success():
                raise Exception(f"Failed to create bitable record: {response.msg}")

            log.info("created bitable record for req_id=%s", req_data["req_id"])

            return {
                "success": True,
                "record_id": response.data.record.record_id,
                "action": "created",
            }

    except Exception as e:
        log.error("failed to sync to bitable: %s", e, exc_info=True)
        raise


@activity.defn(name="bitable_update_cost")
async def bitable_update_cost(req_id: str, cost_used_usd: float) -> dict:
    """
    更新飞书表格中的成本信息

    参数：
        req_id: 需求 ID
        cost_used_usd: 已用成本

    返回：
        {"success": bool}
    """
    return await bitable_sync_requirement({
        "req_id": req_id,
        "cost_used_usd": cost_used_usd,
        "updated_at": datetime.now().isoformat(),
    })


@activity.defn(name="bitable_update_links")
async def bitable_update_links(
    req_id: str,
    prd_doc_url: Optional[str] = None,
    design_doc_url: Optional[str] = None,
    code_pr_url: Optional[str] = None,
) -> dict:
    """
    更新飞书表格中的交付物链接

    参数：
        req_id: 需求 ID
        prd_doc_url: PRD 文档链接
        design_doc_url: 设计文档链接
        code_pr_url: 代码 PR 链接

    返回：
        {"success": bool}
    """
    data = {
        "req_id": req_id,
        "updated_at": datetime.now().isoformat(),
    }

    if prd_doc_url:
        data["prd_doc_url"] = prd_doc_url
    if design_doc_url:
        data["design_doc_url"] = design_doc_url
    if code_pr_url:
        data["code_pr_url"] = code_pr_url

    return await bitable_sync_requirement(data)
