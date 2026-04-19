from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from temporalio import activity
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from activities.feishu.send_card import SendCardInput
from activities.git.commit import GitCommitInput
from aiop.types import (
    CapturedRequirement,
    CardSendResult,
    GitCommitResult,
    PrdResult,
    RequirementInput,
)
from workflows.requirement import RequirementWorkflow


# ---- Mock activities (registered with the same names as production) ----

@activity.defn(name="claude_capture_requirement")
async def mock_capture(req: RequirementInput) -> CapturedRequirement:
    return CapturedRequirement(
        req_id=req.req_id,
        summary="登录页记住密码",
        user_story="作为用户，我想勾选记住密码，以便下次登录免输入。",
        acceptance_hints=["勾选后下次自动填充", "未勾选则不保存", "退出登录后清除"],
        risk_signals=["涉及凭据存储"],
        suggested_risk="medium",
        cost_usd=0.001,
        input_tokens=120,
        output_tokens=60,
    )


@activity.defn(name="claude_generate_prd")
async def mock_prd(captured: CapturedRequirement) -> PrdResult:
    return PrdResult(
        req_id=captured.req_id,
        prd_path=f"/tmp/aiop/{captured.req_id}/p1/PRD.md",
        prd_markdown="# PRD\n\n## 摘要\n登录页记住密码\n\n## 验收\n- AC-1\n- AC-2\n",
        ac_count=5,
        cost_usd=0.05,
        input_tokens=8000,
        output_tokens=1500,
    )


@activity.defn(name="feishu_send_card")
async def mock_send_card(payload: SendCardInput) -> CardSendResult:
    return CardSendResult(
        message_id=f"om_{uuid4().hex[:12]}",
        chat_id=payload.chat_id,
        sent_at=datetime.utcnow(),
    )


@activity.defn(name="git_commit")
async def mock_git_commit(payload: GitCommitInput) -> GitCommitResult:
    return GitCommitResult(
        repo=payload.repo_url,
        branch=payload.branch,
        commit_sha="deadbeef" * 5,
        files_changed=[f for f, _ in payload.files],
        commit_url="https://example.com/commit/deadbeef",
    )


@pytest.mark.asyncio
async def test_p0_p1_happy_path() -> None:
    async with await WorkflowEnvironment.start_time_skipping(
        data_converter=pydantic_data_converter,
    ) as env:
        client: Client = env.client
        async with (
            Worker(
                client, task_queue="lite",
                workflows=[RequirementWorkflow],
                activities=[mock_send_card],
            ),
            Worker(
                client, task_queue="llm-cloud",
                activities=[mock_capture, mock_prd],
            ),
            Worker(
                client, task_queue="git-ops",
                activities=[mock_git_commit],
            ),
        ):
            handle = await client.start_workflow(
                RequirementWorkflow.run,
                RequirementInput(
                    req_id="REQ-TEST-001",
                    title="登录页记住密码",
                    raw_text="希望登录页支持记住密码勾选",
                    project="healthassit",
                    created_by="dev",
                    chat_id="oc_test_chat",
                    repo_url="https://example.com/test/repo.git",
                    branch="main",
                ),
                id=f"req-test-{uuid4().hex[:8]}",
                task_queue="lite",
            )

            # Pre-queue both signals — workflow consumes them in order, no race with time-skipping.
            await handle.signal("p0_confirm", "tester")
            await handle.signal("p1_approve", "tester")

            result = await handle.result()
            assert result["lifecycle_state"] == "approved"
            assert result["captured"]["summary"] == "登录页记住密码"
            assert result["prd_path"].endswith("PRD.md")
            assert result["commit_sha"].startswith("deadbeef")
            assert result["cost_used_usd"] > 0
