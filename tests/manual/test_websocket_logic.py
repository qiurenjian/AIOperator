#!/usr/bin/env python3
"""Simple test script to verify WebSocket implementation logic without running the server."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from apps.ingress.session_manager import SessionManager, Message
from apps.ingress.intent_classifier import classify_intent, IntentType


async def test_intent_classification():
    """Test intent classification with various messages."""
    print("=" * 60)
    print("Testing Intent Classification")
    print("=" * 60)

    test_cases = [
        ("JWT 和 Session 有什么区别？", IntentType.CHAT),
        ("帮我实现一个登录功能", IntentType.REQUIREMENT),
        ("我想做一个用户管理模块", IntentType.CHAT),  # Should be chat (discussing)
        ("就这样实现吧", IntentType.REQUIREMENT),  # After discussion
        ("通过", IntentType.APPROVAL),
        ("批准", IntentType.APPROVAL),
        ("进度如何？", IntentType.QUERY),
    ]

    session = SessionManager.get_or_create("test_chat", "test_user")

    for message, expected in test_cases:
        print(f"\n📝 Message: {message}")
        print(f"   Expected: {expected.value}")

        try:
            intent = await classify_intent(message, session.get_recent_context())
            print(f"   Got: {intent.type.value} (confidence: {intent.confidence:.2f})")
            print(f"   Reason: {intent.reason}")

            if intent.type == expected:
                print("   ✅ PASS")
            else:
                print("   ❌ FAIL")

            # Add to context for next iteration
            session.add_message("user", message)
            session.add_message("assistant", f"Response to: {message}")

        except Exception as e:
            print(f"   ❌ ERROR: {e}")


async def test_session_management():
    """Test session management."""
    print("\n" + "=" * 60)
    print("Testing Session Management")
    print("=" * 60)

    session = SessionManager.get_or_create("test_chat_2", "user_123")

    # Add messages
    for i in range(25):
        session.add_message("user", f"Message {i}")
        session.add_message("assistant", f"Response {i}")

    print(f"\n✅ Session created: {session.chat_id}")
    print(f"   Total messages: {len(session.context)}")
    print(f"   Should be capped at 20: {len(session.context) == 20}")

    recent = session.get_recent_context(5)
    print(f"   Recent 5 messages: {len(recent)}")
    print(f"   Last message: {recent[-1].content}")


async def main():
    """Run all tests."""
    print("\n🧪 WebSocket Implementation Tests\n")

    try:
        await test_session_management()
        await test_intent_classification()

        print("\n" + "=" * 60)
        print("✅ All tests completed!")
        print("=" * 60)

    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
