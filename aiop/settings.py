from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", ".env.cloud"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    temporal_host: str = Field("localhost:7233")
    temporal_namespace: str = Field("aiop")

    database_url: str = Field("postgresql+asyncpg://aiop:changeme_aiop_pw@postgres:5432/aiop")

    anthropic_api_key: str = Field("")
    anthropic_base_url: str = Field("https://api.anthropic.com")

    feishu_app_id: str = Field("")
    feishu_app_secret: str = Field("")
    feishu_verification_token: str = Field("")
    feishu_encrypt_key: str = Field("")
    feishu_bitable_app_token: str = Field("")
    feishu_bitable_kanban_table_id: str = Field("")
    feishu_bot_open_id: str = Field("")
    feishu_doc_parent_token: str = Field("")

    healthassit_repo: str = Field("")
    healthassit_default_branch: str = Field("main")
    github_token: str = Field("")
    git_author_name: str = Field("AIOperator Bot")
    git_author_email: str = Field("aiop-bot@local")

    aiop_workdir_base: str = Field("/tmp/aiop")
    aiop_log_level: str = Field("INFO")

    worker_task_queues: str = Field("lite,llm-cloud,git-ops,feishu-callback")
    worker_max_concurrent_activities: int = Field(4)
    worker_node_name: str = Field("local")

    ingress_host: str = Field("0.0.0.0")
    ingress_port: int = Field(8000)
    ingress_public_url: str = Field("")
    ingress_webhook_secret: str = Field("")

    def workdir_for(self, req_id: str, phase: str) -> Path:
        path = Path(self.aiop_workdir_base) / req_id / phase
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache
def get_settings() -> Settings:
    return Settings()
