from __future__ import annotations

from datetime import timedelta
from typing import Optional

from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from activities.claude.capture_requirement import claude_capture_requirement
    from activities.claude.generate_prd import claude_generate_prd
    from activities.feishu.cards import captured_card, commit_card, prd_card
    from activities.feishu.send_card import SendCardInput, feishu_send_card
    from activities.git.commit import GitCommitInput, git_commit
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
        self.captured = await workflow.execute_activity(
            claude_capture_requirement,
            req,
            task_queue="llm-cloud",
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=retry,
        )
        self.cost_used_usd += self.captured.cost_usd

        if req.chat_id:
            await workflow.execute_activity(
                feishu_send_card,
                SendCardInput(
                    chat_id=req.chat_id,
                    card=captured_card(
                        req_id=req.req_id,
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

        await workflow.wait_condition(lambda: self._p0_confirmed or self._p0_revise_requested, timeout=timedelta(hours=24))

        if self._p0_revise_requested:
            self.lifecycle_state = "revision_requested"
            return self.status()

        # ---------- P1: 生成 PRD ----------
        self.current_phase = "P1"
        self.prd = await workflow.execute_activity(
            claude_generate_prd,
            self.captured,
            task_queue="llm-cloud",
            start_to_close_timeout=timedelta(minutes=20),
            heartbeat_timeout=timedelta(minutes=3),
            retry_policy=RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=10)),
        )
        self.cost_used_usd += self.prd.cost_usd

        if req.chat_id:
            await workflow.execute_activity(
                feishu_send_card,
                SendCardInput(
                    chat_id=req.chat_id,
                    card=prd_card(
                        req_id=req.req_id,
                        summary=self.captured.summary,
                        ac_count=self.prd.ac_count,
                    ),
                ),
                task_queue="lite",
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=retry,
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


