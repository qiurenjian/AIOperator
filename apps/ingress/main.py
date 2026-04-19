from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from fastapi import Body, Depends, FastAPI, HTTPException, Request

from aiop.settings import get_settings
from aiop.types import RequirementInput
from apps.ingress.feishu_signature import verify_feishu_signature
from apps.ingress.temporal_client import get_temporal_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ingress")

app = FastAPI(title="AIOperator Ingress")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "ts": datetime.utcnow().isoformat()}


@app.post("/feishu/webhook")
async def feishu_webhook(request: Request, body: bytes = Depends(verify_feishu_signature)) -> dict:
    payload = json.loads(body or b"{}")

    # 1. URL 验证 challenge
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}

    # 2. 事件回调（v2 schema）
    header = payload.get("header") or {}
    event_type = header.get("event_type") or payload.get("event", {}).get("type")
    event = payload.get("event") or {}

    log.info("feishu event: %s", event_type)

    if event_type == "im.message.receive_v1":
        return await _handle_message(event)
    if event_type == "card.action.trigger":
        return await _handle_card_action(event)

    return {"status": "ignored", "event_type": event_type}


async def _handle_message(event: dict[str, Any]) -> dict:
    s = get_settings()
    msg = event.get("message") or {}
    sender = (event.get("sender") or {}).get("sender_id") or {}

    # Filter: only react to @mentions of our bot in group, or any DM
    chat_type = msg.get("chat_type")
    mentions = msg.get("mentions") or []
    bot_open_id = s.feishu_bot_open_id
    is_mentioned = any((m.get("id") or {}).get("open_id") == bot_open_id for m in mentions)

    if chat_type == "group" and not is_mentioned:
        return {"status": "ignored", "reason": "not mentioned"}

    raw_text = _extract_text(msg.get("content") or "{}", mentions)
    if not raw_text.strip():
        return {"status": "ignored", "reason": "empty"}

    req_id = _gen_req_id()
    title = raw_text[:30]

    project = "healthassit"
    req = RequirementInput(
        req_id=req_id,
        title=title,
        raw_text=raw_text,
        project=project,
        created_by=sender.get("open_id", "unknown"),
        chat_id=msg.get("chat_id"),
        repo_url=_project_repo(project),
        branch=_project_branch(project),
    )

    client = await get_temporal_client()
    handle = await client.start_workflow(
        "RequirementWorkflow",
        req,
        id=f"req-{req_id}",
        task_queue="lite",
    )
    log.info("started workflow %s for req %s", handle.id, req_id)
    return {"status": "started", "req_id": req_id, "workflow_id": handle.id}


async def _handle_card_action(event: dict[str, Any]) -> dict:
    action = event.get("action") or {}
    value = action.get("value") or {}
    operator = event.get("operator") or {}

    action_name = value.get("action")
    req_id = value.get("req_id")
    if not (action_name and req_id):
        raise HTTPException(status_code=400, detail="missing action/req_id")

    signal_map = {
        "p0_confirm": "p0_confirm",
        "p1_approve": "p1_approve",
        "p1_reject": "p1_reject",
    }
    signal = signal_map.get(action_name)
    if not signal:
        return {"toast": {"type": "info", "content": f"未知操作: {action_name}"}}

    client = await get_temporal_client()
    handle = client.get_workflow_handle(f"req-{req_id}")
    await handle.signal(signal, operator.get("open_id", ""))
    log.info("sent signal %s to req-%s", signal, req_id)

    return {"toast": {"type": "success", "content": f"已记录: {action_name}"}}


_AT_RE = re.compile(r"@_user_\d+")


def _extract_text(content_json: str, mentions: list[dict]) -> str:
    try:
        content = json.loads(content_json)
    except json.JSONDecodeError:
        return content_json
    text = content.get("text", "")
    text = _AT_RE.sub("", text).strip()
    return text


def _gen_req_id() -> str:
    return "REQ-" + datetime.utcnow().strftime("%Y%m%d-%H%M%S")


def _project_repo(project: str) -> str:
    s = get_settings()
    return {
        "healthassit": s.healthassit_repo,
    }.get(project, "")


def _project_branch(project: str) -> str:
    s = get_settings()
    return {
        "healthassit": s.healthassit_default_branch,
    }.get(project, "main")


@app.post("/dev/start")
async def dev_start(payload: dict = Body(...)) -> dict:
    """Manual trigger for local testing without Feishu."""
    project = payload.get("project", "healthassit")
    req = RequirementInput(
        req_id=payload.get("req_id") or _gen_req_id(),
        title=payload["title"],
        raw_text=payload["raw_text"],
        project=project,
        created_by=payload.get("created_by", "dev"),
        chat_id=payload.get("chat_id"),
        repo_url=payload.get("repo_url") or _project_repo(project),
        branch=payload.get("branch") or _project_branch(project),
    )
    client = await get_temporal_client()
    handle = await client.start_workflow(
        "RequirementWorkflow",
        req,
        id=f"req-{req.req_id}",
        task_queue="lite",
    )
    return {"workflow_id": handle.id, "req_id": req.req_id}
