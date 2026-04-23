#!/usr/bin/env python3
"""测试对话状态机流程"""
import asyncio
import sys
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from apps.ingress.dialogue_state import DialogueState
from apps.ingress.dialogue_manager import DialogueStateManager
from apps.ingress.session_manager import Session


async def test_discussion_flow():
    """测试探索性对话流程"""
    print("=== 测试场景1: 探索性对话 ===")

    # 模拟会话
    session = Session(
        chat_id="test-001",
        user_id="test-user",
        project_id="test-project",
        dialogue_state=DialogueState.IDLE
    )

    manager = DialogueStateManager()

    # 用户消息：分析请求
    user_message = "梳理当前项目的整体结构，并给出优化分析建议"
    print(f"\n用户: {user_message}")

    transition = await manager.handle_message(session, user_message)

    print(f"状态转换: {session.dialogue_state} -> {transition.next_state}")
    print(f"动作: {transition.action}")
    print(f"响应: {transition.response[:200]}...")

    assert transition.next_state == DialogueState.DISCUSSING
    print("✅ 探索性对话正确识别")


async def test_requirement_confirmation_flow():
    """测试需求确认流程"""
    print("\n\n=== 测试场景2: 需求确认流程 ===")

    session = Session(
        chat_id="test-002",
        user_id="test-user",
        project_id="test-project",
        dialogue_state=DialogueState.IDLE
    )

    manager = DialogueStateManager()

    # 第一步：提交需求
    user_message = "帮我实现一个用户登录功能，支持手机号和密码登录"
    print(f"\n用户: {user_message}")

    transition = await manager.handle_message(session, user_message)

    print(f"状态转换: {session.dialogue_state} -> {transition.next_state}")
    print(f"动作: {transition.action}")
    print(f"响应: {transition.response[:200]}...")

    assert transition.next_state == DialogueState.CLARIFYING
    print("✅ 需求进入澄清状态")


async def test_query_flow():
    """测试查询流程"""
    print("\n\n=== 测试场景3: 查询流程 ===")

    session = Session(
        chat_id="test-003",
        user_id="test-user",
        project_id="test-project",
        dialogue_state=DialogueState.IDLE
    )

    manager = DialogueStateManager()

    user_message = "当前项目有哪些任务？"
    print(f"\n用户: {user_message}")

    transition = await manager.handle_message(session, user_message)

    print(f"状态转换: {session.dialogue_state} -> {transition.next_state}")
    print(f"动作: {transition.action}")

    # 查询是瞬时操作，完成后回到IDLE
    assert transition.next_state == DialogueState.IDLE
    assert transition.action.value == "query"
    print("✅ 查询请求正确识别并处理")


async def main():
    """运行所有测试"""
    try:
        await test_discussion_flow()
        await test_requirement_confirmation_flow()
        await test_query_flow()

        print("\n\n" + "="*50)
        print("✅ 所有测试通过！对话状态机工作正常")
        print("="*50)

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
