from __future__ import annotations

from typing import Any


def captured_card(*, req_id: str, summary: str, user_story: str, hints: list[str], risk: str) -> dict[str, Any]:
    hint_text = "\n".join(f"- {h}" for h in hints)
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"📥 已捕获需求 · {req_id}"},
            "template": "blue",
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**摘要**：{summary}"}},
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**用户故事**：{user_story}"}},
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**验收提示**：\n{hint_text}"}},
            {"tag": "div", "text": {"tag": "lark_md", "content": f"**建议风险等级**：`{risk}`"}},
            {"tag": "hr"},
            {
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "进入 P1（生成 PRD）"},
                        "type": "primary",
                        "value": {"action": "p0_confirm", "req_id": req_id},
                    },
                    {
                        "tag": "button",
                        "text": {"tag": "plain_text", "content": "改写需求"},
                        "type": "default",
                        "value": {"action": "p0_revise", "req_id": req_id},
                    },
                ],
            },
        ],
    }


def prd_card(*, req_id: str, summary: str, ac_count: int, prd_url: str | None = None) -> dict[str, Any]:
    elements: list[dict[str, Any]] = [
        {"tag": "div", "text": {"tag": "lark_md", "content": f"**摘要**：{summary}"}},
        {"tag": "div", "text": {"tag": "lark_md", "content": f"**验收条件**：{ac_count} 条"}},
    ]
    if prd_url:
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"📄 [查看 PRD]({prd_url})"}})
    elements.extend([
        {"tag": "hr"},
        {
            "tag": "action",
            "actions": [
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "✅ 批准并入库（git commit）"},
                    "type": "primary",
                    "value": {"action": "p1_approve", "req_id": req_id},
                },
                {
                    "tag": "button",
                    "text": {"tag": "plain_text", "content": "❌ 拒绝"},
                    "type": "danger",
                    "value": {"action": "p1_reject", "req_id": req_id},
                },
            ],
        },
    ])
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"📝 PRD 已生成 · {req_id}"},
            "template": "green",
        },
        "elements": elements,
    }


def commit_card(*, req_id: str, commit_sha: str, commit_url: str | None) -> dict[str, Any]:
    sha_text = commit_sha[:8]
    link = f"[{sha_text}]({commit_url})" if commit_url else f"`{sha_text}`"
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"🚀 PRD 已入库 · {req_id}"},
            "template": "turquoise",
        },
        "elements": [
            {"tag": "div", "text": {"tag": "lark_md", "content": f"提交：{link}\n下一步：等待 P2 设计阶段（Week 1 Day 2 启用）。"}},
        ],
    }
