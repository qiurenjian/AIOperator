from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

LifecycleState = Literal[
    "draft", "in_progress", "approved", "released", "closed", "cancelled", "paused"
]
PhaseName = Literal["P0", "P1", "P2", "P3", "P4", "P5"]
RiskLevel = Literal["low", "medium", "high", "release-critical"]


class RequirementInput(BaseModel):
    req_id: str
    title: str
    raw_text: str
    project_id: str = "healthassit"  # 项目ID，用于关联数据库中的项目
    created_by: str
    chat_id: Optional[str] = None
    cost_cap_usd: float = 20.0
    repo_url: str = ""
    branch: str = "main"


class CapturedRequirement(BaseModel):
    req_id: str
    summary: str
    user_story: str
    acceptance_hints: list[str]
    risk_signals: list[str] = Field(default_factory=list)
    suggested_risk: RiskLevel = "low"
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0


class PrdResult(BaseModel):
    req_id: str
    prd_path: str
    prd_markdown: str
    ac_count: int
    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0


class CardSendResult(BaseModel):
    message_id: str
    chat_id: str
    sent_at: datetime


class GitCommitResult(BaseModel):
    repo: str
    branch: str
    commit_sha: str
    files_changed: list[str]
    commit_url: Optional[str] = None
