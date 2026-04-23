"""对话状态管理器"""
from __future__ import annotations

import logging
from typing import Optional

from anthropic import Anthropic

from aiop.settings import get_settings
from apps.ingress.chat_handler import handle_chat
from apps.ingress.confirmation_handler import (
    is_cancellation,
    is_confirmation,
    is_modification_request,
    is_rejection,
)
from apps.ingress.dialogue_state import (
    Action,
    DialogueState,
    RequirementDraft,
    StateTransition,
)
from apps.ingress.intent_analyzer import EnhancedIntent, IntentType, analyze_intent
from apps.ingress.requirement_clarifier import clarify_requirement, generate_requirement_summary
from apps.ingress.session_manager import Session
from apps.ingress.status_query import handle_status_query

log = logging.getLogger(__name__)


class DialogueStateManager:
    """对话状态管理器"""

    def __init__(self):
        pass

    async def handle_message(
        self,
        session: Session,
        message: str,
    ) -> StateTransition:
        """处理消息并返回状态转换"""

        current_state = session.dialogue_state

        log.info(
            "handling message in state %s: %s",
            current_state,
            message[:50],
        )

        # 1. 分析消息意图
        intent = await analyze_intent(message, session.get_recent_context(n=5))

        # 2. 根据当前状态和意图决定转换
        if current_state == DialogueState.IDLE:
            return await self._handle_idle(intent, message, session)

        elif current_state == DialogueState.DISCUSSING:
            return await self._handle_discussing(intent, message, session)

        elif current_state == DialogueState.CLARIFYING:
            return await self._handle_clarifying(intent, message, session)

        elif current_state == DialogueState.CONFIRMING:
            return await self._handle_confirming(intent, message, session)

        elif current_state == DialogueState.EXECUTING:
            return await self._handle_executing(intent, message, session)

        elif current_state == DialogueState.QUERYING:
            return await self._handle_querying(intent, message, session)

        else:
            log.warning("unknown state: %s", current_state)
            return StateTransition(
                next_state=DialogueState.IDLE,
                action=Action.CHAT,
                response="抱歉，系统状态异常，已重置。请重新开始。",
            )

    async def _handle_idle(
        self,
        intent: EnhancedIntent,
        message: str,
        session: Session,
    ) -> StateTransition:
        """处理 IDLE 状态"""

        if intent.type == IntentType.DISCUSSION:
            # 进入讨论状态
            response = await self._generate_discussion_response(message, session)
            return StateTransition(
                next_state=DialogueState.DISCUSSING,
                action=Action.DISCUSS,
                response=response,
            )

        elif intent.type == IntentType.REQUIREMENT:
            # 直接进入澄清状态
            response = await self._start_clarification(message, session)
            return StateTransition(
                next_state=DialogueState.CLARIFYING,
                action=Action.CLARIFY,
                response=response,
            )

        elif intent.type == IntentType.QUERY:
            # 进入查询状态
            response = await handle_status_query(message, session.chat_id)
            return StateTransition(
                next_state=DialogueState.IDLE,  # 查询后回到 IDLE
                action=Action.QUERY,
                response=response,
            )

        else:
            # 保持 IDLE，闲聊
            response = await handle_chat(message, session)
            return StateTransition(
                next_state=DialogueState.IDLE,
                action=Action.CHAT,
                response=response,
            )

    async def _handle_discussing(
        self,
        intent: EnhancedIntent,
        message: str,
        session: Session,
    ) -> StateTransition:
        """处理 DISCUSSING 状态"""

        # 检查是否出现需求意图
        if intent.type == IntentType.REQUIREMENT and intent.confidence > 0.8:
            # 用户在讨论中明确表达了需求
            response = await self._start_clarification(message, session)
            return StateTransition(
                next_state=DialogueState.CLARIFYING,
                action=Action.CLARIFY,
                response=response,
            )

        # 检查是否要结束讨论
        if self._is_discussion_complete(message):
            return StateTransition(
                next_state=DialogueState.IDLE,
                action=Action.COMPLETE,
                response="好的，如果有需求随时告诉我！",
            )

        # 继续讨论
        response = await self._continue_discussion(message, session)
        return StateTransition(
            next_state=DialogueState.DISCUSSING,
            action=Action.DISCUSS,
            response=response,
        )

    async def _handle_clarifying(
        self,
        intent: EnhancedIntent,
        message: str,
        session: Session,
    ) -> StateTransition:
        """处理 CLARIFYING 状态"""

        # 检查是否取消
        if is_cancellation(message):
            session.reset_clarification()
            return StateTransition(
                next_state=DialogueState.IDLE,
                action=Action.CANCEL,
                response="好的，已取消需求澄清。",
            )

        # 用户回答澄清问题
        if session.clarification_questions:
            last_question = session.clarification_questions[-1]
            session.add_clarification(last_question, message)

        # 检查是否澄清完成
        if await self._is_clarification_complete(session):
            # 生成需求摘要
            draft = await self._generate_requirement_draft(session)
            session.requirement_draft = draft

            # 进入确认状态
            return StateTransition(
                next_state=DialogueState.CONFIRMING,
                action=Action.CONFIRM,
                response=draft.to_summary(),
            )

        # 继续澄清
        next_question = await self._get_next_clarification_question(session, message)
        session.clarification_questions.append(next_question)
        return StateTransition(
            next_state=DialogueState.CLARIFYING,
            action=Action.CLARIFY,
            response=next_question,
        )

    async def _handle_confirming(
        self,
        intent: EnhancedIntent,
        message: str,
        session: Session,
    ) -> StateTransition:
        """处理 CONFIRMING 状态"""

        # 检查用户确认
        if is_confirmation(message) or intent.type == IntentType.CONFIRMATION:
            # 用户确认，准备启动 workflow
            return StateTransition(
                next_state=DialogueState.EXECUTING,
                action=Action.EXECUTE,
                response="✅ 需求已确认，正在启动处理流程...",
                metadata={"start_workflow": True},
            )

        elif is_rejection(message) or is_modification_request(message):
            # 用户拒绝或要求修改，返回澄清状态
            session.reset_clarification()
            return StateTransition(
                next_state=DialogueState.CLARIFYING,
                action=Action.CLARIFY,
                response="好的，我们重新澄清一下。请问哪里需要修改？",
            )

        elif is_cancellation(message):
            # 用户取消
            session.reset_clarification()
            return StateTransition(
                next_state=DialogueState.IDLE,
                action=Action.CANCEL,
                response="好的，已取消需求提交。",
            )

        else:
            # 用户提供了额外信息，返回澄清状态
            if session.clarification_questions:
                last_question = session.clarification_questions[-1]
                session.add_clarification(last_question, message)
            return StateTransition(
                next_state=DialogueState.CLARIFYING,
                action=Action.CLARIFY,
                response="好的，我记下了。还有其他补充吗？",
            )

    async def _handle_executing(
        self,
        intent: EnhancedIntent,
        message: str,
        session: Session,
    ) -> StateTransition:
        """处理 EXECUTING 状态"""

        # 在执行状态，只支持查询和取消
        if intent.type == IntentType.QUERY:
            response = await handle_status_query(message, session.chat_id)
            return StateTransition(
                next_state=DialogueState.EXECUTING,
                action=Action.QUERY,
                response=response,
            )

        elif is_cancellation(message):
            # 取消 workflow
            return StateTransition(
                next_state=DialogueState.IDLE,
                action=Action.CANCEL,
                response="正在取消需求处理...",
                metadata={"cancel_workflow": True},
            )

        else:
            return StateTransition(
                next_state=DialogueState.EXECUTING,
                action=Action.WAIT,
                response="需求正在处理中，请稍候。你可以发送「查询进度」查看状态。",
            )

    async def _handle_querying(
        self,
        intent: EnhancedIntent,
        message: str,
        session: Session,
    ) -> StateTransition:
        """处理 QUERYING 状态"""

        response = await handle_status_query(message, session.chat_id)
        return StateTransition(
            next_state=DialogueState.IDLE,  # 查询后回到 IDLE
            action=Action.QUERY,
            response=response,
        )

    async def _generate_discussion_response(
        self,
        message: str,
        session: Session,
    ) -> str:
        """生成讨论响应"""
        # 使用 chat_handler 生成响应
        return await handle_chat(message, session)

    async def _continue_discussion(
        self,
        message: str,
        session: Session,
    ) -> str:
        """继续讨论"""
        return await handle_chat(message, session)

    async def _start_clarification(
        self,
        message: str,
        session: Session,
    ) -> str:
        """开始需求澄清"""
        # 重置澄清数据
        session.reset_clarification()

        # 使用 clarify_requirement 开始澄清
        result = await clarify_requirement(message, session)

        return result["response"]

    async def _is_clarification_complete(self, session: Session) -> bool:
        """检查澄清是否完成"""
        # 简单策略：至少3轮问答
        return len(session.clarification_answers) >= 3

    async def _get_next_clarification_question(self, session: Session, message: str) -> str:
        """获取下一个澄清问题"""
        result = await clarify_requirement(message, session)
        return result["response"]

    async def _generate_requirement_draft(
        self,
        session: Session,
    ) -> RequirementDraft:
        """生成需求草稿"""
        # 使用 LLM 从澄清问答中提取需求信息
        settings = get_settings()
        client = Anthropic(
            api_key=settings.anthropic_api_key,
            base_url=settings.anthropic_base_url,
        )

        qa_text = "\n".join(
            f"Q: {q}\nA: {a}"
            for q, a in zip(
                session.clarification_questions,
                session.clarification_answers,
            )
        )

        prompt = f"""根据以下需求澄清问答，生成需求摘要：

{qa_text}

请提取：
1. 需求标题（简短，10字以内）
2. 需求描述（1-2句话）
3. 关键功能列表（3-5个要点）
4. 预估成本（美元，基于复杂度）
5. 预估时间（如"30-40分钟"）

返回 JSON 格式：
{{
  "title": "需求标题",
  "description": "需求描述",
  "features": ["功能1", "功能2", "功能3"],
  "estimated_cost": 2.5,
  "estimated_time": "30-40分钟"
}}

只返回 JSON，不要其他内容。"""

        try:
            response = client.messages.create(
                model="claude-3-5-haiku-20241022",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
            )

            text = response.content[0].text.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()

            import json
            result = json.loads(text)

            draft = RequirementDraft(
                title=result["title"],
                description=result["description"],
                features=result["features"],
                estimated_cost=result["estimated_cost"],
                estimated_time=result["estimated_time"],
            )

            # 保存澄清问答
            for q, a in zip(
                session.clarification_questions,
                session.clarification_answers,
            ):
                draft.add_clarification(q, a)

            return draft

        except Exception as e:
            log.error("failed to generate requirement draft: %s", e, exc_info=True)
            # 返回默认草稿
            return RequirementDraft(
                title="需求草稿",
                description="基于用户输入的需求",
                features=["待补充"],
                estimated_cost=1.0,
                estimated_time="待评估",
            )

    def _is_discussion_complete(self, message: str) -> bool:
        """判断讨论是否结束"""
        message_lower = message.lower().strip()

        completion_keywords = [
            "明白了", "了解了", "清楚了", "好的", "谢谢",
            "知道了", "懂了", "ok", "thanks"
        ]

        # 必须是短消息
        if len(message) > 15:
            return False

        return any(kw in message_lower for kw in completion_keywords)
