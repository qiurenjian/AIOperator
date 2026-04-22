from __future__ import annotations

from datetime import timedelta
from typing import Optional

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from activities.claude.capture_requirement import claude_capture_requirement
    from activities.claude.generate_prd import claude_generate_prd
    from activities.db import (
        sync_requirement_index_create,
        sync_requirement_index_deliverables,
        sync_requirement_index_state,
    )
    from activities.feishu.cards import captured_card, commit_card, prd_card
    from activities.feishu.send_card import SendCardInput, feishu_send_card
    from activities.feishu.send_message import feishu_send_message
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

        # ---------- 创建需求索引 ----------
        await workflow.execute_activity(
            sync_requirement_index_create,
            args=[
                req.req_id,
                req.project_id,
                workflow.info().workflow_id,
                req.title,
                req.created_by,
                req.cost_cap_usd,
            ],
            task_queue="lite",
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=retry,
        )

        # ---------- P0: 捕获需求 ----------
        self.current_phase = "P0"
        self.lifecycle_state = "in_progress"

        # 同步状态到数据库
        await workflow.execute_activity(
            sync_requirement_index_state,
            args=[req.req_id],
            kwargs={"lifecycle_state": "in_progress", "current_phase": "P0"},
            task_queue="lite",
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=retry,
        )

        # Cost control check
        if req.cost_cap_usd and req.cost_cap_usd > 0:
            if self.cost_used_usd >= req.cost_cap_usd:
                if req.chat_id:
                    await workflow.execute_activity(
                        feishu_send_message,
                        args=[req.chat_id, f"⚠️ 预算已用尽 (${self.cost_used_usd:.2f}/${req.cost_cap_usd:.2f})，流程暂停"],
                        task_queue="lite",
                        start_to_close_timeout=timedelta(seconds=30),
                        retry_policy=retry,
                    )
                raise ApplicationError("Cost cap exceeded", non_retryable=True)

        if req.chat_id:
            await workflow.execute_activity(
                feishu_send_message,
                args=[req.chat_id, f"📝 开始处理需求 {req.req_id}"],
                task_queue="lite",
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=retry,
            )
            await workflow.execute_activity(
                notify_websocket,
                args=[req.chat_id, {"type": "progress", "phase": "P0", "message": "正在分析需求..."}],
                task_queue="lite",
                start_to_close_timeout=timedelta(seconds=10),
            )

        try:
            self.captured = await workflow.execute_activity(
                claude_capture_requirement,
                req,
                task_queue="llm-cloud",
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry,
            )
            self.cost_used_usd += self.captured.cost_usd

            # 同步 P0 结果到数据库
            await workflow.execute_activity(
                sync_requirement_index_state,
                args=[req.req_id],
                kwargs={
                    "lifecycle_state": "captured",
                    "cost_used_usd": self.cost_used_usd,
                    "risk_level": self.captured.suggested_risk,
                    "summary": self.captured.summary,
                },
                task_queue="lite",
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=retry,
            )
        except Exception as e:
            if req.chat_id:
                await workflow.execute_activity(
                    feishu_send_message,
                    args=[req.chat_id, f"❌ 需求分析失败: {str(e)}"],
                    task_queue="lite",
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=retry,
                )
            raise

        # Cost control check after P0
        if req.cost_cap_usd and req.cost_cap_usd > 0:
            if self.cost_used_usd >= req.cost_cap_usd:
                if req.chat_id:
                    await workflow.execute_activity(
                        feishu_send_message,
                        args=[req.chat_id, f"⚠️ 预算已用尽 (${self.cost_used_usd:.2f}/${req.cost_cap_usd:.2f})，流程暂停"],
                        task_queue="lite",
                        start_to_close_timeout=timedelta(seconds=30),
                        retry_policy=retry,
                    )
                raise ApplicationError("Cost cap exceeded", non_retryable=True)

        if req.chat_id:
            await workflow.execute_activity(
                feishu_send_message,
                args=[req.chat_id, f"✅ 需求分析完成 | 成本: ${self.cost_used_usd:.4f}"],
                task_queue="lite",
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=retry,
            )
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
                feishu_send_message,
                args=[req.chat_id, "📝 开始生成 PRD（预计 3-5 分钟）..."],
                task_queue="lite",
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=retry,
            )
            await workflow.execute_activity(
                notify_websocket,
                args=[req.chat_id, {"type": "progress", "phase": "P1", "message": "正在生成 PRD..."}],
                task_queue="lite",
                start_to_close_timeout=timedelta(seconds=10),
            )

        try:
            self.prd = await workflow.execute_activity(
                claude_generate_prd,
                self.captured,
                task_queue="llm-cloud",
                start_to_close_timeout=timedelta(minutes=20),
                heartbeat_timeout=timedelta(minutes=3),
                retry_policy=RetryPolicy(maximum_attempts=2, initial_interval=timedelta(seconds=10)),
            )
            self.cost_used_usd += self.prd.cost_usd

            # 同步 P1 结果到数据库
            await workflow.execute_activity(
                sync_requirement_index_state,
                args=[req.req_id],
                kwargs={
                    "lifecycle_state": "prd_generated",
                    "current_phase": "P1",
                    "cost_used_usd": self.cost_used_usd,
                },
                task_queue="lite",
                start_to_close_timeout=timedelta(seconds=10),
                retry_policy=retry,
            )
        except Exception as e:
            if req.chat_id:
                await workflow.execute_activity(
                    feishu_send_message,
                    args=[req.chat_id, f"❌ PRD 生成失败: {str(e)}"],
                    task_queue="lite",
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=retry,
                )
            raise

        # Cost control check after P1
        if req.cost_cap_usd and req.cost_cap_usd > 0:
            if self.cost_used_usd >= req.cost_cap_usd:
                if req.chat_id:
                    await workflow.execute_activity(
                        feishu_send_message,
                        args=[req.chat_id, f"⚠️ 预算已用尽 (${self.cost_used_usd:.2f}/${req.cost_cap_usd:.2f})，流程暂停"],
                        task_queue="lite",
                        start_to_close_timeout=timedelta(seconds=30),
                        retry_policy=retry,
                    )
                raise ApplicationError("Cost cap exceeded", non_retryable=True)

        if req.chat_id:
            await workflow.execute_activity(
                feishu_send_message,
                args=[req.chat_id, f"✅ PRD 生成完成 | 验收条件: {self.prd.ac_count} 条 | 累计成本: ${self.cost_used_usd:.4f}"],
                task_queue="lite",
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=retry,
            )
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

        try:
            self.commit = await workflow.execute_activity(
                git_commit,
                commit_input,
                task_queue="git-ops",
                start_to_close_timeout=timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=5)),
            )
        except Exception as e:
            if req.chat_id:
                await workflow.execute_activity(
                    feishu_send_message,
                    args=[req.chat_id, f"❌ Git 提交失败: {str(e)}"],
                    task_queue="lite",
                    start_to_close_timeout=timedelta(seconds=30),
                    retry_policy=retry,
                )
            raise

        # 同步交付物链接到数据库
        prd_doc_url = f"{self.commit.commit_url.rsplit('/commit/', 1)[0]}/blob/{req.branch}/docs/PRDs/{req.req_id}.md"
        await workflow.execute_activity(
            sync_requirement_index_state,
            args=[req.req_id],
            kwargs={
                "lifecycle_state": "approved",
                "current_phase": "P1-DONE",
                "prd_doc_url": prd_doc_url,
                "commit_url": self.commit.commit_url,
            },
            task_queue="lite",
            start_to_close_timeout=timedelta(seconds=10),
            retry_policy=retry,
        )

        if req.chat_id:
            await workflow.execute_activity(
                feishu_send_message,
                args=[req.chat_id, f"🎉 PRD 已提交到代码仓库\n📄 文档: docs/PRDs/{req.req_id}.md\n🔗 查看: {self.commit.commit_url}"],
                task_queue="lite",
                start_to_close_timeout=timedelta(seconds=30),
                retry_policy=retry,
            )
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


