from __future__ import annotations

import asyncio
import json
from pathlib import Path

from temporalio import activity

from aiop.settings import get_settings
from aiop.types import CapturedRequirement, PrdResult

PRD_PROMPT_TEMPLATE = """你是 AIOperator 的 P1 产品经理。基于已捕获的需求，产出一份完整 PRD.md。

需求摘要：{summary}
用户故事：{user_story}
验收提示：{hints}
风险等级建议：{risk}

要求：
1. 在当前工作目录写入 `PRD.md`，章节包括：背景、目标、用户角色、用户故事、详细功能、验收标准、非功能需求、风险与边界。
2. 同时写入 `acceptance_criteria.json`：数组形式，每条 `{{"id":"AC-1","given":"...","when":"...","then":"..."}}`。
3. 验收条件至少 5 条，覆盖正常、异常、边界场景。
4. 只用 Write 工具创建这两个文件，不要修改其他文件。

完成后输出一行总结。"""


@activity.defn(name="claude_generate_prd")
async def claude_generate_prd(captured: CapturedRequirement) -> PrdResult:
    s = get_settings()
    workdir = s.workdir_for(captured.req_id, "p1")

    prompt = PRD_PROMPT_TEMPLATE.format(
        summary=captured.summary,
        user_story=captured.user_story,
        hints="; ".join(captured.acceptance_hints),
        risk=captured.suggested_risk,
    )

    activity.heartbeat({"req_id": captured.req_id, "stage": "spawning_claude_cli", "workdir": str(workdir)})

    proc = await asyncio.create_subprocess_exec(
        "claude",
        "-p",
        prompt,
        "--model",
        "claude-sonnet-4-6",
        "--output-format",
        "json",
        "--max-turns",
        "20",
        "--allowed-tools",
        "Read,Write,Edit,Glob,Grep",
        cwd=str(workdir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def _heartbeat() -> None:
        while proc.returncode is None:
            activity.heartbeat({"req_id": captured.req_id, "stage": "claude_running"})
            await asyncio.sleep(30)

    hb_task = asyncio.create_task(_heartbeat())
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=1200)
    finally:
        hb_task.cancel()

    if proc.returncode != 0:
        raise RuntimeError(f"claude CLI failed (rc={proc.returncode}): {stderr.decode()[:500]}")

    result = json.loads(stdout.decode())
    prd_path = workdir / "PRD.md"
    ac_path = workdir / "acceptance_criteria.json"
    if not prd_path.exists():
        raise RuntimeError(f"PRD.md was not produced at {prd_path}")

    ac_count = 0
    if ac_path.exists():
        try:
            ac_count = len(json.loads(ac_path.read_text()))
        except json.JSONDecodeError:
            ac_count = 0

    return PrdResult(
        req_id=captured.req_id,
        prd_path=str(prd_path),
        prd_markdown=Path(prd_path).read_text(),
        ac_count=ac_count,
        cost_usd=float(result.get("total_cost_usd", 0.0)),
        input_tokens=int(result.get("usage", {}).get("input_tokens", 0)),
        output_tokens=int(result.get("usage", {}).get("output_tokens", 0)),
    )
