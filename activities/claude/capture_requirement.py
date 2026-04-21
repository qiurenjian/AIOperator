from __future__ import annotations

import json

from anthropic import AsyncAnthropic
from temporalio import activity

from aiop.settings import get_settings
from aiop.types import CapturedRequirement, RequirementInput

SYSTEM_PROMPT = """你是 AIOperator 的 P0 需求捕获助手。
用户会用一句话描述需求，你的任务：
1. 抽取核心目标，写成一行 summary（≤30 字）
2. 改写为标准 user story（"作为 X，我想 Y，以便 Z"）
3. 列 3-5 条验收提示（acceptance hints），每条 ≤20 字
4. 标注风险信号（涉及支付/认证/线上数据迁移→ high；涉及 UI/文案→ low；其他→ medium）

只输出 JSON，不要解释，结构：
{
  "summary": "...",
  "user_story": "...",
  "acceptance_hints": ["..."],
  "risk_signals": ["..."],
  "suggested_risk": "low|medium|high|release-critical"
}"""


HAIKU_INPUT_PER_MTOK = 0.80
HAIKU_OUTPUT_PER_MTOK = 4.00


@activity.defn(name="claude_capture_requirement")
async def claude_capture_requirement(req: RequirementInput) -> CapturedRequirement:
    s = get_settings()
    client = AsyncAnthropic(api_key=s.anthropic_api_key, base_url=s.anthropic_base_url)
    activity.heartbeat({"req_id": req.req_id, "stage": "calling_anthropic"})

    resp = await client.messages.create(
        model="claude-haiku-4",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"标题：{req.title}\n描述：{req.raw_text}"}],
    )

    text = "".join(block.text for block in resp.content if getattr(block, "type", None) == "text")
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json\n"):
            text = text[5:]
    parsed = json.loads(text)

    in_tok = resp.usage.input_tokens
    out_tok = resp.usage.output_tokens
    cost = in_tok / 1_000_000 * HAIKU_INPUT_PER_MTOK + out_tok / 1_000_000 * HAIKU_OUTPUT_PER_MTOK

    return CapturedRequirement(
        req_id=req.req_id,
        summary=parsed["summary"],
        user_story=parsed["user_story"],
        acceptance_hints=parsed.get("acceptance_hints", []),
        risk_signals=parsed.get("risk_signals", []),
        suggested_risk=parsed.get("suggested_risk", "low"),
        cost_usd=round(cost, 6),
        input_tokens=in_tok,
        output_tokens=out_tok,
    )
