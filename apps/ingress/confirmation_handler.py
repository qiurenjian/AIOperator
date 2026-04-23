"""确认处理机制"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def is_confirmation(message: str) -> bool:
    """判断是否是确认消息"""
    message_lower = message.lower().strip()

    # 明确的确认词
    confirmation_keywords = [
        "确认", "提交", "开始", "执行", "好的", "可以",
        "没问题", "就这样", "ok", "yes", "y", "同意"
    ]

    # 必须是短消息（避免误判）
    if len(message) > 20:
        return False

    return any(kw in message_lower for kw in confirmation_keywords)


def is_rejection(message: str) -> bool:
    """判断是否是拒绝消息"""
    message_lower = message.lower().strip()

    rejection_keywords = [
        "取消", "不要", "重新", "修改", "不对", "不是",
        "no", "n", "cancel", "拒绝"
    ]

    return any(kw in message_lower for kw in rejection_keywords)


def is_modification_request(message: str) -> bool:
    """判断是否是修改请求"""
    message_lower = message.lower().strip()

    modification_keywords = [
        "修改", "改一下", "调整", "换成", "改成", "重新"
    ]

    return any(kw in message_lower for kw in modification_keywords)


def is_cancellation(message: str) -> bool:
    """判断是否是取消请求"""
    message_lower = message.lower().strip()

    cancellation_keywords = [
        "取消", "停止", "中止", "不要了", "算了", "cancel", "stop"
    ]

    return any(kw in message_lower for kw in cancellation_keywords)
