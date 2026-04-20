from __future__ import annotations

import logging

from anthropic import Anthropic

from aiop.settings import get_settings
from apps.ingress.session_manager import Message, Session

log = logging.getLogger(__name__)


async def handle_chat(message: str, session: Session) -> str:
    """Handle chat intent using Claude for direct conversation."""
    settings = get_settings()
    client = Anthropic(api_key=settings.anthropic_api_key)

    # Build conversation history
    messages = []
    for msg in session.get_recent_context(n=10):
        messages.append({"role": msg.role, "content": msg.content})
    messages.append({"role": "user", "content": message})

    system_prompt = """你是 AIOP（AI Operator），一个帮助开发者管理需求和生成代码的 AI 助手。

你的职责：
1. 帮助用户讨论和澄清需求细节
2. 回答技术问题和提供建议
3. 当用户明确要实现某功能时，引导他们提交需求

注意：
- 保持简洁专业，避免冗长
- 如果用户在讨论需求，帮助他们梳理清楚后，询问是否要提交需求
- 如果用户问技术问题，直接回答
- 使用中文回复"""

    try:
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=2000,
            system=system_prompt,
            messages=messages,
        )

        reply = response.content[0].text
        log.info("chat response generated: %d chars", len(reply))
        return reply

    except Exception as e:
        log.error("chat handler failed: %s", e)
        return f"抱歉，处理消息时出错：{str(e)}"
