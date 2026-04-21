"""PRD 审查对话处理器"""
from __future__ import annotations

import json
import logging
from typing import Optional

from anthropic import AsyncAnthropic

from aiop.settings import get_settings
from apps.ingress.session_manager import Session

log = logging.getLogger(__name__)

PRD_REVIEW_SYSTEM_PROMPT = """你是 AIOperator 的 PRD 审查助手。系统已经生成了一份 PRD，现在用户正在审查。

**你的任务**：
1. 回答用户关于 PRD 的问题
2. 记录用户的反馈和修改建议
3. 判断用户是否满意当前 PRD
4. 如果用户提出修改建议，整理成结构化的反馈

**对话策略**：
- 理解用户的关注点（功能完整性、技术可行性、优先级等）
- 如果用户提出模糊的反馈，追问具体细节
- 当用户表示满意或明确批准时，确认可以进入下一阶段

**输出格式**：
返回 JSON：
{
  "response": "回复用户的文本",
  "action": "discuss|approve|revise",  // discuss=继续讨论, approve=批准, revise=需要修改
  "feedback_items": ["反馈1", "反馈2"],  // 如果 action=revise
  "confidence": 0.0-1.0
}

**PRD 摘要**：
{prd_summary}

**历史对话**：
{history}

**用户最新消息**：
{user_message}"""


async def review_prd(
    user_message: str,
    session: Session,
    prd_summary: str,
    max_retries: int = 2,
) -> dict:
    """
    处理 PRD 审查对话

    返回：
    {
        "response": str,
        "action": "discuss" | "approve" | "revise",
        "feedback_items": list,
        "confidence": float
    }
    """
    settings = get_settings()
    client = AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        base_url=settings.anthropic_base_url,
        timeout=30.0,
    )

    # 构建历史对话上下文
    history_text = "\n".join(
        f"{msg.role}: {msg.content}"
        for msg in session.get_recent_context(n=10)
    )

    prompt = PRD_REVIEW_SYSTEM_PROMPT.format(
        prd_summary=prd_summary,
        history=history_text,
        user_message=user_message,
    )

    last_error = None

    for attempt in range(max_retries + 1):
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

            # 验证必需字段
            if "response" not in result:
                raise ValueError("响应缺少 'response' 字段")

            # 设置默认值
            result.setdefault("action", "discuss")
            result.setdefault("feedback_items", [])
            result.setdefault("confidence", 0.5)

            log.info(
                "prd review result: action=%s, confidence=%.2f, attempt=%d",
                result["action"],
                result["confidence"],
                attempt + 1,
            )

            return result

        except Exception as e:
            last_error = e
            log.error("failed to review prd: %s, attempt %d/%d", e, attempt + 1, max_retries + 1)
            if attempt < max_retries:
                continue

    # 所有重试都失败
    log.error("all prd review attempts failed: %s", last_error)
    return {
        "response": "我理解了你的反馈。还有其他需要调整的地方吗？",
        "action": "discuss",
        "feedback_items": [],
        "confidence": 0.5,
        "error": str(last_error),
    }


async def generate_prd_revision_request(session: Session) -> str:
    """
    基于用户反馈生成 PRD 修改请求

    用于将用户的反馈整理成结构化的修改指令，发送给 workflow
    """
    settings = get_settings()
    client = AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        base_url=settings.anthropic_base_url,
    )

    # 提取 PRD 审查阶段的对话
    prd_review_messages = [
        msg for msg in session.context
        if msg.timestamp >= session.conversation.updated_at
    ]

    history_text = "\n".join(
        f"{msg.role}: {msg.content}"
        for msg in prd_review_messages
    )

    prompt = f"""基于以下 PRD 审查对话，生成一个结构化的修改请求。

对话历史：
{history_text}

请输出一个清晰的修改请求（100-300字），包含：
1. 需要修改的具体内容
2. 修改的原因
3. 期望的结果

直接输出修改请求文本，不要 JSON 格式。"""

    try:
        resp = await client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )

        text = "".join(
            block.text for block in resp.content
            if getattr(block, "type", None) == "text"
        )

        return text.strip()

    except Exception as e:
        log.error("failed to generate revision request: %s", e, exc_info=True)
        return "用户要求修改 PRD，请重新生成。"
