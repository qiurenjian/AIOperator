"""需求澄清对话处理器"""
from __future__ import annotations

import json
import logging
from typing import Optional

from anthropic import AsyncAnthropic

from aiop.settings import get_settings
from apps.ingress.session_manager import Session

log = logging.getLogger(__name__)

CLARIFICATION_SYSTEM_PROMPT = """你是 AIOperator 的需求澄清助手。用户提出了一个初步需求，你的任务是通过对话帮助用户完善需求。

**你的目标**：
1. 理解用户的核心目标和使用场景
2. 识别需求中的模糊点、缺失信息
3. 通过提问引导用户补充关键细节
4. 判断需求是否已经足够清晰，可以进入 PRD 生成阶段

**对话策略**：
- 每次只问 1-2 个最关键的问题
- 问题要具体、易回答
- 避免技术术语，用用户能理解的语言
- 当需求已经足够清晰时，主动建议进入下一阶段

**输出格式**：
返回 JSON，包含：
{
  "response": "回复用户的文本",
  "is_ready": true/false,  // 需求是否已足够清晰
  "confidence": 0.0-1.0,   // 对需求理解的信心度
  "missing_info": ["缺失的信息1", "缺失的信息2"]  // 如果 is_ready=false
}

**历史对话**：
{history}

**用户最新消息**：
{user_message}"""


async def clarify_requirement(
    user_message: str,
    session: Session,
) -> dict:
    """
    处理需求澄清对话

    返回：
    {
        "response": str,      # 回复用户的文本
        "is_ready": bool,     # 需求是否已足够清晰
        "confidence": float,  # 信心度
        "missing_info": list  # 缺失的信息
    }
    """
    settings = get_settings()
    client = AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        base_url=settings.anthropic_base_url,
    )

    # 构建历史对话上下文
    history_text = "\n".join(
        f"{msg.role}: {msg.content}"
        for msg in session.get_recent_context(n=10)
    )

    prompt = CLARIFICATION_SYSTEM_PROMPT.format(
        history=history_text,
        user_message=user_message,
    )

    try:
        resp = await client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=1024,
            system=prompt,
            messages=[{"role": "user", "content": user_message}],
        )

        text = "".join(
            block.text for block in resp.content
            if getattr(block, "type", None) == "text"
        )

        # 解析 JSON 响应
        text = text.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json\n"):
                text = text[5:]

        result = json.loads(text)

        log.info(
            "clarification result: is_ready=%s, confidence=%.2f",
            result.get("is_ready", False),
            result.get("confidence", 0.0),
        )

        return result

    except Exception as e:
        log.error("failed to clarify requirement: %s", e, exc_info=True)
        # 降级：返回简单确认
        return {
            "response": "我理解了。还有其他需要补充的吗？如果没有，我可以开始生成 PRD。",
            "is_ready": True,
            "confidence": 0.5,
            "missing_info": [],
        }


async def generate_requirement_summary(session: Session) -> str:
    """
    基于澄清对话生成需求摘要

    用于在确认需求后，生成一个结构化的需求描述，传递给 workflow
    """
    settings = get_settings()
    client = AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        base_url=settings.anthropic_base_url,
    )

    history_text = "\n".join(
        f"{msg.role}: {msg.content}"
        for msg in session.context  # 使用完整对话历史
    )

    prompt = f"""基于以下对话，生成一个结构化的需求描述。

对话历史：
{history_text}

请输出一个清晰、完整的需求描述（200-500字），包含：
1. 核心目标
2. 使用场景
3. 关键功能点
4. 验收标准

直接输出需求描述文本，不要 JSON 格式。"""

    try:
        resp = await client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )

        text = "".join(
            block.text for block in resp.content
            if getattr(block, "type", None) == "text"
        )

        return text.strip()

    except Exception as e:
        log.error("failed to generate requirement summary: %s", e, exc_info=True)
        # 降级：使用最后一条用户消息
        user_messages = [msg.content for msg in session.context if msg.role == "user"]
        return user_messages[-1] if user_messages else "需求描述生成失败"
