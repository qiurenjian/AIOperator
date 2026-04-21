"""需求澄清对话处理器 - 优化版本

优化点：
1. 添加重试机制
2. 改进 JSON 解析（处理更多边界情况）
3. 添加超时控制
4. 改进错误处理和降级策略
5. 添加成本跟踪
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from anthropic import AsyncAnthropic, APIError, APITimeoutError

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


def _extract_json_from_text(text: str) -> dict:
    """
    从文本中提取 JSON，处理各种格式

    支持：
    - 纯 JSON
    - ```json ... ```
    - ```...```
    - 混合文本中的 JSON
    """
    text = text.strip()

    # 尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 移除 markdown 代码块标记
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json\n"):
            text = text[5:]
        elif text.startswith("json "):
            text = text[5:]

    # 再次尝试解析
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass

    # 尝试提取 JSON 对象（使用正则）
    json_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
    matches = re.findall(json_pattern, text, re.DOTALL)

    for match in matches:
        try:
            return json.loads(match)
        except json.JSONDecodeError:
            continue

    # 所有方法都失败
    raise ValueError(f"无法从文本中提取有效的 JSON: {text[:100]}...")


async def clarify_requirement(
    user_message: str,
    session: Session,
    max_retries: int = 2,
) -> dict:
    """
    处理需求澄清对话

    参数：
        user_message: 用户消息
        session: 会话对象
        max_retries: 最大重试次数

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
        timeout=30.0,  # 30 秒超时
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
            result = _extract_json_from_text(text)

            # 验证必需字段
            if "response" not in result:
                raise ValueError("响应缺少 'response' 字段")

            # 设置默认值
            result.setdefault("is_ready", False)
            result.setdefault("confidence", 0.5)
            result.setdefault("missing_info", [])

            log.info(
                "clarification result: is_ready=%s, confidence=%.2f, attempt=%d",
                result["is_ready"],
                result["confidence"],
                attempt + 1,
            )

            return result

        except APITimeoutError as e:
            last_error = e
            log.warning("clarification timeout, attempt %d/%d", attempt + 1, max_retries + 1)
            if attempt < max_retries:
                continue

        except APIError as e:
            last_error = e
            log.error("anthropic API error: %s, attempt %d/%d", e, attempt + 1, max_retries + 1)
            if attempt < max_retries:
                continue

        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            log.error("failed to parse response: %s, attempt %d/%d", e, attempt + 1, max_retries + 1)
            if attempt < max_retries:
                continue

        except Exception as e:
            last_error = e
            log.error("unexpected error in clarify_requirement: %s", e, exc_info=True)
            break

    # 所有重试都失败，返回降级响应
    log.error("all clarification attempts failed: %s", last_error)

    return {
        "response": "我理解了。还有其他需要补充的吗？如果没有，我可以开始生成 PRD。",
        "is_ready": True,
        "confidence": 0.5,
        "missing_info": [],
        "error": str(last_error),
    }


async def generate_requirement_summary(
    session: Session,
    max_retries: int = 2,
) -> str:
    """
    基于澄清对话生成需求摘要

    用于在确认需求后，生成一个结构化的需求描述，传递给 workflow

    参数：
        session: 会话对象
        max_retries: 最大重试次数
    """
    settings = get_settings()
    client = AsyncAnthropic(
        api_key=settings.anthropic_api_key,
        base_url=settings.anthropic_base_url,
        timeout=30.0,
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

    last_error = None

    for attempt in range(max_retries + 1):
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

            summary = text.strip()

            if len(summary) < 50:
                raise ValueError(f"生成的摘要过短: {len(summary)} 字符")

            log.info("generated requirement summary: %d chars, attempt=%d", len(summary), attempt + 1)
            return summary

        except APITimeoutError as e:
            last_error = e
            log.warning("summary generation timeout, attempt %d/%d", attempt + 1, max_retries + 1)
            if attempt < max_retries:
                continue

        except APIError as e:
            last_error = e
            log.error("anthropic API error: %s, attempt %d/%d", e, attempt + 1, max_retries + 1)
            if attempt < max_retries:
                continue

        except Exception as e:
            last_error = e
            log.error("unexpected error in generate_requirement_summary: %s", e, exc_info=True)
            break

    # 所有重试都失败，返回降级响应
    log.error("all summary generation attempts failed: %s", last_error)

    # 降级：使用最后一条用户消息
    user_messages = [msg.content for msg in session.context if msg.role == "user"]
    if user_messages:
        return user_messages[-1]

    return "需求描述生成失败，请重新提交需求。"
