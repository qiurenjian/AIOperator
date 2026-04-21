"""对话流程集成测试

测试多阶段对话系统的完整流程：
1. 需求澄清阶段
2. 需求确认阶段
3. PRD 审查阶段
4. 状态查询
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from apps.ingress.conversation_state import ConversationPhase
from apps.ingress.session_manager import Session, session_manager
from apps.feishu_connector.message_handler import (
    handle_message,
    _is_status_query,
)


@pytest.fixture
def mock_session():
    """创建模拟会话"""
    # 清理旧会话
    session_manager.remove("test_chat")
    # 创建新会话
    session = session_manager.get_or_create("test_chat", "test_user")
    return session


@pytest.fixture
def mock_feishu_api():
    """模拟飞书 API"""
    with patch("apps.feishu_connector.message_handler.send_feishu_message") as mock:
        mock.return_value = asyncio.Future()
        mock.return_value.set_result(None)
        yield mock


@pytest.fixture
def mock_temporal_client():
    """模拟 Temporal 客户端"""
    with patch("apps.feishu_connector.message_handler.get_temporal_client") as mock:
        client = AsyncMock()
        mock.return_value = client
        yield client


class TestStatusQuery:
    """测试状态查询功能"""

    def test_is_status_query_positive(self):
        """测试状态查询关键词识别"""
        assert _is_status_query("查看状态")
        assert _is_status_query("当前进度")
        assert _is_status_query("任务进展怎么样了")
        assert _is_status_query("到哪了")
        assert _is_status_query("workflow 状态")

    def test_is_status_query_negative(self):
        """测试非状态查询"""
        assert not _is_status_query("你好")
        assert not _is_status_query("我想做一个功能")
        assert not _is_status_query("批准 PRD")


class TestRequirementClarification:
    """测试需求澄清流程"""

    @pytest.mark.asyncio
    async def test_enter_clarification_phase(
        self, mock_session, mock_feishu_api
    ):
        """测试进入需求澄清阶段"""
        with patch("apps.feishu_connector.message_handler.classify_intent") as mock_intent:
            # 模拟意图分类返回 REQUIREMENT
            from apps.ingress.intent_classifier import IntentType
            mock_intent.return_value = MagicMock(type=IntentType.REQUIREMENT, confidence=0.9)

            with patch("apps.feishu_connector.message_handler.clarify_requirement") as mock_clarify:
                mock_clarify.return_value = {
                    "response": "请问这个功能的目标用户是谁？",
                    "is_ready": False,
                }

                await handle_message(
                    "test_chat",
                    "test_user",
                    "msg_001",
                    "我想做一个用户登录功能",
                )

                # 验证会话状态
                assert mock_session.conversation.phase == ConversationPhase.REQUIREMENT_CLARIFYING
                assert mock_feishu_api.called

    @pytest.mark.asyncio
    async def test_requirement_ready_after_clarification(
        self, mock_session, mock_feishu_api
    ):
        """测试需求澄清完成后进入确认阶段"""
        mock_session.conversation.update_phase(ConversationPhase.REQUIREMENT_CLARIFYING)

        with patch("apps.feishu_connector.message_handler.clarify_requirement") as mock_clarify:
            mock_clarify.return_value = {
                "response": "明白了，需求已经很清晰。",
                "is_ready": True,
            }

            with patch("apps.feishu_connector.message_handler.generate_requirement_summary") as mock_summary:
                mock_summary.return_value = "用户登录功能需求摘要"

                await handle_message(
                    "test_chat",
                    "test_user",
                    "msg_002",
                    "目标用户是企业员工，需要支持邮箱和手机号登录",
                )

                # 验证会话状态
                assert mock_session.conversation.phase == ConversationPhase.REQUIREMENT_CONFIRMED
                assert mock_session.conversation.requirement_draft == "用户登录功能需求摘要"


class TestRequirementConfirmation:
    """测试需求确认流程"""

    @pytest.mark.asyncio
    async def test_confirm_and_start_workflow(
        self, mock_session, mock_feishu_api, mock_temporal_client
    ):
        """测试确认需求并启动 workflow"""
        mock_session.conversation.update_phase(ConversationPhase.REQUIREMENT_CONFIRMED)
        mock_session.conversation.requirement_draft = "用户登录功能需求"

        with patch("apps.feishu_connector.message_handler.get_settings") as mock_settings:
            mock_settings.return_value = MagicMock(
                healthassit_repo="https://github.com/test/repo",
                healthassit_default_branch="main",
            )

            await handle_message(
                "test_chat",
                "test_user",
                "msg_003",
                "确认",
            )

            # 验证 workflow 启动
            assert mock_temporal_client.start_workflow.called
            assert mock_session.conversation.phase == ConversationPhase.PRD_REVIEW
            assert mock_session.conversation.workflow_id is not None

    @pytest.mark.asyncio
    async def test_reject_and_return_to_clarification(
        self, mock_session, mock_feishu_api
    ):
        """测试拒绝确认，返回澄清阶段"""
        mock_session.conversation.update_phase(ConversationPhase.REQUIREMENT_CONFIRMED)

        await handle_message(
            "test_chat",
            "test_user",
            "msg_004",
            "我想再改改需求",
        )

        # 验证返回澄清阶段
        assert mock_session.conversation.phase == ConversationPhase.REQUIREMENT_CLARIFYING


class TestPRDReview:
    """测试 PRD 审查流程"""

    @pytest.mark.asyncio
    async def test_approve_prd(
        self, mock_session, mock_feishu_api, mock_temporal_client
    ):
        """测试批准 PRD"""
        mock_session.conversation.update_phase(ConversationPhase.PRD_REVIEW)
        mock_session.conversation.workflow_id = "test_workflow_001"
        mock_session.conversation.prd_content = "PRD 内容摘要"

        with patch("apps.feishu_connector.message_handler.review_prd") as mock_review:
            mock_review.return_value = {
                "response": "好的，已批准 PRD",
                "action": "approve",
            }

            # 模拟 workflow handle
            mock_handle = AsyncMock()
            mock_temporal_client.get_workflow_handle.return_value = mock_handle

            await handle_message(
                "test_chat",
                "test_user",
                "msg_005",
                "批准这个 PRD",
            )

            # 验证发送了批准信号
            mock_handle.signal.assert_called_once_with("p1_approve")
            assert mock_session.conversation.phase == ConversationPhase.DESIGN_DISCUSSION

    @pytest.mark.asyncio
    async def test_request_prd_revision(
        self, mock_session, mock_feishu_api, mock_temporal_client
    ):
        """测试请求 PRD 修改"""
        mock_session.conversation.update_phase(ConversationPhase.PRD_REVIEW)
        mock_session.conversation.workflow_id = "test_workflow_002"

        with patch("apps.feishu_connector.message_handler.review_prd") as mock_review:
            mock_review.return_value = {
                "response": "好的，已记录修改建议",
                "action": "revise",
                "feedback_items": ["需要添加错误处理"],
            }

            with patch("apps.feishu_connector.message_handler.generate_prd_revision_request") as mock_revision:
                mock_revision.return_value = "修改请求内容"

                # 模拟 workflow handle
                mock_handle = AsyncMock()
                mock_temporal_client.get_workflow_handle.return_value = mock_handle

                await handle_message(
                    "test_chat",
                    "test_user",
                    "msg_006",
                    "这个 PRD 需要添加错误处理的说明",
                )

                # 验证发送了拒绝信号
                mock_handle.signal.assert_called_once_with("p1_reject")
                assert mock_session.conversation.phase == ConversationPhase.IDLE


class TestErrorHandling:
    """测试错误处理"""

    @pytest.mark.asyncio
    async def test_handle_empty_message(self, mock_feishu_api):
        """测试处理空消息"""
        await handle_message("test_chat", "test_user", "msg_007", "")

        # 空消息应该被忽略，不发送回复
        assert not mock_feishu_api.called

    @pytest.mark.asyncio
    async def test_handle_exception_in_clarification(
        self, mock_session, mock_feishu_api
    ):
        """测试澄清阶段异常处理"""
        mock_session.conversation.update_phase(ConversationPhase.REQUIREMENT_CLARIFYING)

        with patch("apps.feishu_connector.message_handler.clarify_requirement") as mock_clarify:
            # 模拟抛出异常
            mock_clarify.side_effect = Exception("API 调用失败")

            await handle_message(
                "test_chat",
                "test_user",
                "msg_008",
                "测试消息",
            )

            # 验证发送了错误消息
            assert mock_feishu_api.called
            call_args = mock_feishu_api.call_args[0]
            assert "处理失败" in call_args[1]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
