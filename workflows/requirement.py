from __future__ import annotations

from datetime import timedelta
from typing import Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from activities.bitable.sync import bitable_sync_requirement
    from activities.claude.capture_requirement import claude_capture_requirement
    from activities.claude.generate_prd import claude_generate_prd
    from activities.feishu.cards import captured_card, commit_card, prd_card
    from activities.feishu.send_card import SendCardInput, feishu_send_card
    from activities.git.commit import GitCommitInput, git_commit
    from activities.websocket.notify import notify_websocket
    from aiop.types import (
        CapturedRequirement,
        GitCommitResult,
        PrdResult,
        RequirementInput,
    )


@workflow.defn(name="RequirementWorkflow")
class RequirementWorkflow:
    def __init__(self) -> None:
        self.current_phase: str = "P0"
        self.lifecycle_state: str = "draft"
        self.captured: Optional[CapturedRequirement] = None
        self.prd: Optional[PrdResult] = None
        self.commit: Optional[GitCommitResult] = None
        self._p0_confirmed: bool = False
        self._p0_revise_requested: bool = False
        self._p1_decision: Optional[str] = None  # "approve" | "reject"
        self.cost_used_usd: float = 0.0

    @workflow.signal
    def p0_confirm(self, by: str = "") -> None:
        self._p0_confirmed = True

    @workflow.signal
    def p0_revise(self, by: str = "") -> None:
        self._p0_revise_requested = True

    @workflow.signal
    def p1_approve(self, by: str = "") -> None:
        self._p1_decision = "approve"

    @workflow.signal
    def p1_reject(self, by: str = "") -> None:
        self._p1_decision = "reject"

    @workflow.query
    def status(self) -> dict:
        return {
            "phase": self.current_phase,
            "lifecycle_state": self.lifecycle_state,
            "cost_used_usd": self.cost_used_usd,
            "captured": self.captured.model_dump() if self.captured else None,
            "prd_path": self.prd.prd_path if self.prd else None,
            "commit_sha": self.commit.commit_sha if self.commit else None,
        }

    @workflow.run
    async def run(self, req: RequirementInput) -> dict:
        retry = RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=2))

        # ---------- P0: 捕获需求 ----------
        self.current_phase = "P0"
        self.lifecycle_state = "in_progress"

        if req.chat_id:
            await workflow.execute_activity(
                notify_websocket,
                args=[req.chat_id, {"type": "progress", "phase": "P0", "message": "正在分析需求..."}],
                task_queue="lite",
                start_to_close_timeout=timedelta(seconds=10),
            )

        self.captured = await workflow.execute_activity(
            claude_capture_requirement,
            req,
            task_queue="llm-cloud",
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=retry,
        )
        self.cost_used_usd += self.captured.cost_usd

        # 同步到飞书表格
        await workflow.execute_activity(
            bitable_sync_requirement,
            {
                "req_id": req.req_id,
                "title": self.captured.summary,
                "project": "HealthAssit",
                "created_by": req.created_by or "unknown",
                "lifecycle_state": "captured",
                "current_phase": "P0",
                "cost_used_usd": self.cost_used_usd,
                "risk_level": self.captured.suggested_risk,
                "created_at": workflow.now().isoformat(),
                "updated_at": workflow.now().isoformat(),
            },
            task_queue="bitable-sync",
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=2)),
        )

        if req.chat_id:
            await workflow.execute_activity(
                feishu_send_card,
                SendCardInput(
                    chat_id=req.chat_id,
                    card=captured_card(
                        req_id=req.req_id,
                        workflow_id=workflow.info().workflow_id,
                        summary=self.captured.summary,
                        user_story=self.captured.user_story,
                        hints=self.captured.acceptance_hints,
                        risk=self.captured.suggested_risk,
                    ),
                ),
                task_queue="lite",
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=retry,
            )
            await workflow.execute_activity(
                notify_websocket,
                args=[req.chat_id, {"type": "progress", "phase": "P0", "message": "✅ 需求已捕获，等待确认"}],
                task_queue="lite",
                start_to_close_timeout=timedelta(seconds=10),
            )

        await workflow.wait_condition(lambda: self._p0_confirmed or self._p0_revise_requested, timeout=timedelta(hours=24))

        if self._p0_revise_requested:
            self.lifecycle_state = "revision_requested"
            return self.status()

        # ---------- P1: 生成 PRD ----------
        self.current_phase = "P1"

        if req.chat_id:
            await workflow.execute_activity(
                notify_websocket,
                args=[req.chat_id, {"type": "progress", "phase": "P1", "message": "正在生成 PRD..."}],
                task_queue="lite",
                start_to_close_timeout=timedelta(seconds=10),
            )

        self.prd = await workflow.execute_activity(
            claude_generate_prd,
            self.captured,
            task_queue="llm-cloud",
            start_to_close_timeout=timedelta(minutes=20),
            heartbeat_timeout=timedelta(minutes=3),
            retry_policy=RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=10)),
        )
        self.cost_used_usd += self.prd.cost_usd

        # 同步到飞书表格（更新 PRD 阶段）
        await workflow.execute_activity(
            bitable_sync_requirement,
            {
                "req_id": req.req_id,
                "lifecycle_state": "prd_generated",
                "current_phase": "P1",
                "cost_used_usd": self.cost_used_usd,
                "updated_at": workflow.now().isoformat(),
            },
            task_queue="bitable-sync",
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=2)),
        )

        if req.chat_id:
            await workflow.execute_activity(
                feishu_send_card,
                SendCardInput(
                    chat_id=req.chat_id,
                    card=prd_card(
                        req_id=req.req_id,
                        workflow_id=workflow.info().workflow_id,
                        summary=self.captured.summary,
                        ac_count=self.prd.ac_count,
                    ),
                ),
                task_queue="lite",
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=retry,
            )
            await workflow.execute_activity(
                notify_websocket,
                args=[req.chat_id, {
                    "type": "prd_ready",
                    "phase": "P1",
                    "req_id": req.req_id,
                    "workflow_id": workflow.info().workflow_id,
                    "summary": self.captured.summary,
                    "ac_count": self.prd.ac_count,
                }],
                task_queue="lite",
                start_to_close_timeout=timedelta(seconds=10),
            )

        await workflow.wait_condition(lambda: self._p1_decision is not None, timeout=timedelta(hours=48))
        if self._p1_decision == "reject":
            self.lifecycle_state = "cancelled"
            return self.status()

        # ---------- git commit (PRD 入库) ----------
        commit_input = GitCommitInput(
            req_id=req.req_id,
            repo_url=req.repo_url,
            branch=req.branch,
            files=[
                (f"docs/PRDs/{req.req_id}.md", self.prd.prd_markdown),
            ],
            commit_message=f"docs(PRD): {req.req_id} {self.captured.summary}\n\nGenerated by AIOperator P1.",
        )
        self.commit = await workflow.execute_activity(
            git_commit,
            commit_input,
            task_queue="git-ops",
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=5)),
        )

        # 同步 PRD 文档链接到飞书表格
        if self.commit.commit_url:
            prd_doc_url = f"{self.commit.commit_url.rsplit('/commit/', 1)[0]}/blob/{req.branch}/docs/PRDs/{req.req_id}.md"
            await workflow.execute_activity(
                bitable_sync_requirement,
                {
                    "req_id": req.req_id,
                    "lifecycle_state": "approved",
                    "current_phase": "P1-DONE",
                    "prd_doc_url": prd_doc_url,
                    "updated_at": workflow.now().isoformat(),
                },
                task_queue="bitable-sync",
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=2)),
            )

        if req.chat_id:
            await workflow.execute_activity(
                feishu_send_card,
                SendCardInput(
                    chat_id=req.chat_id,
                    card=commit_card(
                        req_id=req.req_id,
                        commit_sha=self.commit.commit_sha,
                        commit_url=self.commit.commit_url,
                    ),
                ),
                task_queue="lite",
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=retry,
            )

        self.lifecycle_state = "approved"
        self.current_phase = "P1-DONE"
        return self.status()


