from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

from fastapi import Body, Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect

from aiop.settings import get_settings
from aiop.types import RequirementInput
from apps.ingress.chat_handler import handle_chat
from apps.ingress.feishu_signature import verify_feishu_signature
from apps.ingress.intent_classifier import IntentType, classify_intent
from apps.ingress.session_manager import SessionManager
from apps.ingress.temporal_client import get_temporal_client
from apps.ingress.websocket_notifier import WebSocketNotifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ingress")

app = FastAPI(title="AIOperator Ingress")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "ts": datetime.utcnow().isoformat()}


@app.websocket("/ws/{chat_id}")
async def websocket_endpoint(websocket: WebSocket, chat_id: str):
    """WebSocket endpoint for real-time chat with intent classification."""
    await websocket.accept()
    log.info("websocket connected: chat_id=%s", chat_id)

    user_id = "unknown"
    session = SessionManager.get_or_create(chat_id, user_id)
    WebSocketNotifier.register(chat_id, websocket)

    try:
        while True:
            data = await websocket.receive_json()
            message = data.get("message", "").strip()
            if not message:
                continue

            log.info("received message from %s: %s", chat_id, message[:100])

            # 1. Classify intent
            intent = await classify_intent(message, session.get_recent_context())

            # 2. Route based on intent
            if intent.type == IntentType.CHAT:
                response = await handle_chat(message, session)
                session.add_message("user", message)
                session.add_message("assistant", response)
                await websocket.send_json({"type": "message", "content": response})

            elif intent.type == IntentType.REQUIREMENT:
                session.add_message("user", message)
                req_id = await _start_requirement_workflow(message, session)
                response = f"✅ 需求已提交（{req_id}），正在生成 PRD..."
                session.add_message("assistant", response)
                await websocket.send_json(
                    {
                        "type": "workflow_started",
                        "req_id": req_id,
                        "message": response,
                    }
                )

            elif intent.type == IntentType.APPROVAL:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "审批功能暂未实现，请使用卡片按钮",
                    }
                )

            elif intent.type == IntentType.QUERY:
                await websocket.send_json(
                    {
                        "type": "error",
                        "message": "查询功能暂未实现",
                    }
                )

    except WebSocketDisconnect:
        log.info("websocket disconnected: chat_id=%s", chat_id)
        WebSocketNotifier.unregister(chat_id)
        SessionManager.remove(chat_id)
    except Exception as e:
        log.error("websocket error: %s", e)
        WebSocketNotifier.unregister(chat_id)
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except:
            pass


async def _start_requirement_workflow(message: str, session) -> str:
    """Start RequirementWorkflow from WebSocket message."""
    s = get_settings()
    req_id = _gen_req_id()
    title = message[:30]
    project = "healthassit"

    req = RequirementInput(
        req_id=req_id,
        title=title,
        raw_text=message,
        project=project,
        created_by=session.user_id,
        chat_id=session.chat_id,
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
    session.active_workflow_id = handle.id
    log.info("started workflow %s for req %s", handle.id, req_id)
    return req_id


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


@app.post("/feishu/callback")
async def feishu_callback(request: Request, body: bytes = Depends(verify_feishu_signature)) -> dict:
    payload = json.loads(body or b"{}")
    log.info("feishu callback payload: %s", payload)

    # 1. URL 验证 challenge
    if payload.get("type") == "url_verification":
        return {"challenge": payload.get("challenge")}

    # 2. 卡片交互回调 (schema 2.0)
    event_type = payload.get("header", {}).get("event_type") or payload.get("type")
    if event_type == "card.action.trigger":
        return await _handle_card_action(payload.get("event", payload))

    log.warning("unhandled callback type: %s", event_type)
    return {"status": "ignored"}


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
    log.info("card action event: %s", event)
    action = event.get("action") or {}
    value = action.get("value") or {}
    operator = event.get("operator") or {}

    action_name = value.get("action")
    req_id = value.get("req_id")
    log.info("parsed action=%s req_id=%s", action_name, req_id)
    if not (action_name and req_id):
        log.warning("missing action/req_id in card callback")
        raise HTTPException(status_code=400, detail="missing action/req_id")

    signal_map = {
        "p0_confirm": "p0_confirm",
        "p0_revise": "p0_revise",
        "p1_approve": "p1_approve",
        "p1_reject": "p1_reject",
    }
    signal = signal_map.get(action_name)
    if not signal:
        return {"toast": {"type": "error", "content": f"未知操作: {action_name}"}}

    client = await get_temporal_client()
    handle = client.get_workflow_handle(f"req-{req_id}")
    await handle.signal(signal, operator.get("open_id", ""))
    log.info("sent signal %s to req-%s", signal, req_id)

    action_text = {
        "p0_confirm": "✅ 已确认需求，开始生成 PRD",
        "p0_revise": "✏️ 已请求改写需求",
        "p1_approve": "✅ 已批准 PRD，准备提交代码",
        "p1_reject": "❌ 已拒绝 PRD",
    }.get(action_name, "操作成功")

    return {"toast": {"type": "success", "content": action_text}}


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
