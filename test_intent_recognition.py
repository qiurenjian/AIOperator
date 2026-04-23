#!/usr/bin/env python3
"""测试意图识别准确性"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from apps.ingress.intent_analyzer import analyze_intent, IntentType


async def test_intent(message: str, expected: IntentType):
    """测试单个意图识别"""
    print(f"\n测试: {message}")
    print(f"期望: {expected.value}")

    result = await analyze_intent(message, [])

    print(f"结果: {result.type.value} (置信度: {result.confidence:.2f})")
    print(f"推理: {result.reasoning}")

    if result.type == expected:
        print("✅ 正确")
        return True
    else:
        print(f"❌ 错误 - 期望 {expected.value}，得到 {result.type.value}")
        return False


async def main():
    """运行所有测试"""
    test_cases = [
        # 查询类
        ("需求列表", IntentType.QUERY),
        ("项目详情", IntentType.QUERY),
        ("当前进度", IntentType.QUERY),
        ("有哪些任务", IntentType.QUERY),
        ("显示所有需求", IntentType.QUERY),
        ("查询项目状态", IntentType.QUERY),

        # 讨论类
        ("帮我分析一下项目架构", IntentType.DISCUSSION),
        ("梳理当前项目的整体结构", IntentType.DISCUSSION),
        ("介绍一下这个项目", IntentType.DISCUSSION),
        ("评估一下性能", IntentType.DISCUSSION),

        # 需求类
        ("实现用户登录功能", IntentType.REQUIREMENT),
        ("开发一个注册页面", IntentType.REQUIREMENT),
        ("添加支付功能", IntentType.REQUIREMENT),
        ("创建数据库表", IntentType.REQUIREMENT),

        # 确认类
        ("确认", IntentType.CONFIRMATION),
        ("提交", IntentType.CONFIRMATION),
        ("取消", IntentType.CONFIRMATION),
    ]

    results = []
    for message, expected in test_cases:
        success = await test_intent(message, expected)
        results.append(success)

    print("\n" + "="*50)
    print(f"测试结果: {sum(results)}/{len(results)} 通过")
    print("="*50)

    if sum(results) < len(results):
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
