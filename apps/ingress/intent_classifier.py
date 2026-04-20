from __future__ import annotations

import json
import logging
from enum import Enum

from anthropic import Anthropic

from aiop.settings import get_settings
from apps.ingress.session_manager import Message

log = logging.getLogger(__name__)


class IntentType(str, Enum):
    CHAT = "chat"
    REQUIREMENT = "requirement"
    APPROVAL = "approval"
    QUERY = "query"


class Intent:
    def __init__(self, type: IntentType, confidence: float, reason: str):
        self.type = type
        self.confidence = confidence
        self.reason = reason


def format_context(messages: list[Message]) -> str:
    if not messages:
        return "无历史对话"
    lines = []
    for msg in messages:
        lines.append(f"{msg.role}: {msg.content[:100]}")
    return "\n".join(lines)


async def classify_intent(message: str, context: list[Message]) -> Intent:
    settings = get_settings()
    client = Anthropic(api_key=settings.anthropic_api_key)

    context_str = format_context(context[-3:])

    prompt = f"""用户消息："{message}"
对话历史：
{context_str}

判断用户意图并返回 JSON：
- chat: 讨论、咨询、澄清需求细节、技术问题
- requirement: 明确提出要实现某功能（"帮我实现..."、"我需要..."、"做一个..."）
- approval: 确认或拒绝某个方案（"通过"、"批准"、"拒绝"、"修改..."）
- query: 查询状态或历史（"进度如何"、"有哪些需求"）

返回格式：
{{
  "intent": "chat|requirement|approval|query",
  "confidence": 0.0-1.0,
  "reason": "判断依据"
}}

只返回 JSON，不要其他内容。"""

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        result = json.loads(text)

        intent = Intent(
            type=IntentType(result["intent"]),
            confidence=result["confidence"],
            reason=result.get("reason", ""),
        )

        log.info(
            "classified intent: %s (%.2f) - %s",
            intent.type,
            intent.confidence,
            intent.reason,
        )
        return intent

    except Exception as e:
        log.error("intent classification failed: %s", e)
        return Intent(type=IntentType.CHAT, confidence=0.5, reason=f"fallback: {e}")
