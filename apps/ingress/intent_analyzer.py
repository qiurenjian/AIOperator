"""增强的意图分析"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from enum import Enum

from anthropic import Anthropic

from aiop.settings import get_settings
from apps.ingress.session_manager import Message

log = logging.getLogger(__name__)


class IntentType(str, Enum):
    """意图类型"""
    CHAT = "chat"  # 闲聊
    DISCUSSION = "discussion"  # 讨论/分析
    REQUIREMENT = "requirement"  # 明确需求
    QUERY = "query"  # 查询状态
    CONFIRMATION = "confirmation"  # 确认/拒绝


@dataclass
class EnhancedIntent:
    """增强的意图识别结果"""
    type: IntentType
    confidence: float
    reasoning: str

    # 新增字段
    is_exploratory: bool = False  # 是否是探索性对话
    is_actionable: bool = False  # 是否是可执行的需求
    requires_clarification: bool = False  # 是否需要澄清


def format_context(messages: list[Message]) -> str:
    """格式化对话上下文"""
    if not messages:
        return "无历史对话"
    lines = []
    for msg in messages[-5:]:  # 最近5条
        lines.append(f"{msg.role}: {msg.content[:100]}")
    return "\n".join(lines)


async def analyze_intent(message: str, context: list[Message]) -> EnhancedIntent:
    """分析用户消息意图"""

    # 先进行快速规则匹配，避免LLM误判
    message_lower = message.lower().strip()

    # 0. 讨论类关键词（最高优先级，避免被查询误判）
    discussion_keywords = [
        "分析", "评估", "梳理", "介绍", "建议", "方案",
        "优化", "改进", "探讨", "讨论"
    ]
    if any(kw in message_lower for kw in discussion_keywords):
        log.info("fast match: DISCUSSION (keyword: %s)", message_lower)
        return EnhancedIntent(
            type=IntentType.DISCUSSION,
            confidence=0.95,
            reasoning=f"包含讨论关键词: {message_lower}",
            is_exploratory=True,
            is_actionable=False,
        )

    # 1. 查询类关键词
    query_keywords = [
        "列表", "查询", "显示", "查看", "进度", "状态",
        "详情", "有哪些", "什么任务", "项目信息"
    ]
    if any(kw in message_lower for kw in query_keywords):
        # 排除：如果同时包含"实现"、"开发"等强需求词，则不是查询
        strong_requirement_keywords = ["实现", "开发", "添加", "创建", "构建"]
        if not any(kw in message_lower for kw in strong_requirement_keywords):
            log.info("fast match: QUERY (keyword: %s)", message_lower)
            return EnhancedIntent(
                type=IntentType.QUERY,
                confidence=0.95,
                reasoning=f"包含查询关键词: {message_lower}",
                is_exploratory=False,
                is_actionable=False,
            )

    # 2. 确认类关键词
    confirmation_keywords = ["确认", "提交", "好的", "可以", "ok", "没问题", "就这样"]
    rejection_keywords = ["取消", "不要", "重新", "修改", "算了"]
    if message_lower in confirmation_keywords or message_lower in rejection_keywords:
        log.info("fast match: CONFIRMATION")
        return EnhancedIntent(
            type=IntentType.CONFIRMATION,
            confidence=0.95,
            reasoning=f"确认/拒绝关键词: {message_lower}",
        )

    # 3. 使用LLM进行复杂意图分析
    settings = get_settings()
    client = Anthropic(
        api_key=settings.anthropic_api_key,
        base_url=settings.anthropic_base_url,
    )

    context_str = format_context(context)

    prompt = f"""分析用户消息的意图，区分以下类型：

**优先级规则（必须严格遵守）**：
1. 如果消息包含"分析"、"评估"、"梳理"、"介绍"、"建议"、"方案" → 一定是 DISCUSSION
2. 如果消息包含"列表"、"查询"、"显示"、"有哪些"、"进度"、"状态"、"详情" → 一定是 QUERY
3. 如果消息是"确认"、"提交"、"好的"、"取消" → 一定是 CONFIRMATION
4. 只有明确说"实现"、"开发"、"添加功能"、"创建"时，才是 REQUIREMENT

**意图类型**：

1. **DISCUSSION（讨论）** - 最高优先级：
   - "帮我分析..."、"介绍一下..."、"评估..."
   - "梳理..."、"出方案"、"有什么建议"

2. **QUERY（查询）**：
   - "需求列表"、"任务列表"、"项目详情"
   - "当前进度"、"有哪些任务"
   - "显示..."、"查看..."、"查询..."

3. **REQUIREMENT（需求）**：
   - "实现..."、"开发..."、"添加功能..."
   - "创建..."、"构建..."

4. **CONFIRMATION（确认）**：
   - "确认"、"提交"、"好的"、"取消"

5. **CHAT（闲聊）**：
   - 问候、感谢

用户消息：{message}

最近对话：
{context_str}

返回 JSON：
{{
  "type": "DISCUSSION|QUERY|REQUIREMENT|CONFIRMATION|CHAT",
  "confidence": 0.0-1.0,
  "is_exploratory": true/false,
  "is_actionable": true/false,
  "requires_clarification": true/false,
  "reasoning": "判断理由"
}}

只返回 JSON，不要其他内容。"""

    try:
        response = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
        )

        text = response.content[0].text.strip()
        # 提取 JSON
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
            text = text.strip()

        result = json.loads(text)

        intent = EnhancedIntent(
            type=IntentType(result["type"].lower()),
            confidence=result["confidence"],
            reasoning=result.get("reasoning", ""),
            is_exploratory=result.get("is_exploratory", False),
            is_actionable=result.get("is_actionable", False),
            requires_clarification=result.get("requires_clarification", False),
        )

        log.info(
            "analyzed intent: %s (%.2f) exploratory=%s actionable=%s - %s",
            intent.type,
            intent.confidence,
            intent.is_exploratory,
            intent.is_actionable,
            intent.reasoning,
        )
        return intent

    except Exception as e:
        log.error("intent analysis failed: %s", e, exc_info=True)
        # 默认返回 DISCUSSION，避免误触发
        return EnhancedIntent(
            type=IntentType.DISCUSSION,
            confidence=0.5,
            reasoning=f"fallback due to error: {e}",
            is_exploratory=True,
            is_actionable=False,
        )
