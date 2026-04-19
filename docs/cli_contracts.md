# LLM 调用合同（Week 0 Day 2）

> 本文定义每个 LLM activity 走 **CLI**（Claude Code / Codex）还是 **API**（Anthropic / OpenAI），及调用模板。
>
> 字段标 `[待实测]` 的需要在 Day 2 用真实命令验证后回填。

---

## 决策矩阵：Activity → 调用方式

| Activity | 调用方式 | 模型 | 理由 |
|----------|---------|------|------|
| `claude_capture_requirement` | **API** (Haiku) | claude-haiku-4-5 | 短结构化任务，API 快且便宜 |
| `claude_generate_prd` | **CLI** (Claude Code) | sonnet-4-6 | 需读项目历史 PRD 作 few-shot，CLI 上下文管理更好 |
| `claude_generate_design` | **CLI** (Claude Code) | sonnet-4-6 | 需扫描代码仓库，CLI 自带 Read/Grep/Glob |
| `claude_generate_tests` | **CLI** (Claude Code) | sonnet-4-6 | 需读 design + 现有测试风格，CLI 适合 |
| `codex_implement` | **CLI** (Codex) | Codex Pro | Codex 专长实现 + 已有 Pro 订阅 |
| `claude_review` | **CLI** (Claude Code) | sonnet-4-6 | 需读完整 diff + design |
| `claude_lite_review` | **API** (Haiku) | claude-haiku-4-5 | 只看 diff 摘要 + AC 映射，API 够用且便宜 |
| `openai_review` | **API** (OpenAI) | gpt-5 或 o4 | 跨家独立终审 |

**规则**：
- **API 适合**：短任务、结构化输出、不需要文件系统访问
- **CLI 适合**：长任务、需要读写代码仓库、多轮 Tool 调用

---

## 1. Claude Code CLI 调用模板

### 1.1 基础调用（headless / `-p` mode）

```bash
claude -p "PROMPT" \
  --model claude-sonnet-4-6 \
  --output-format json \
  --max-turns 30 \
  --cwd /tmp/aiop-work/REQ-20260419-001 \
  --allowed-tools "Read,Edit,Write,Glob,Grep,Bash"
```

**关键参数**：
- `-p PROMPT`：headless 模式，不进交互
- `--output-format json`：返回结构化结果，方便 activity 解析
- `--max-turns N`：限制 agent 自迭代次数（防失控）
- `--cwd DIR`：每个 req 一个独立工作目录
- `--allowed-tools`：白名单工具，禁止 WebFetch 等

### 1.2 Activity 包装伪代码

```python
@activity.defn
async def claude_generate_prd(input: PrdInput) -> PrdOutput:
    workdir = f"/tmp/aiop/{input.req_id}/p1"
    os.makedirs(workdir, exist_ok=True)

    # 把 requirement.json + 项目 CLAUDE.md 复制到 workdir
    shutil.copy(input.requirement_path, workdir)
    git_clone_or_pull(input.project_repo, workdir)

    prompt = render_template("p1_prd.j2", input=input)

    proc = await asyncio.create_subprocess_exec(
        "claude", "-p", prompt,
        "--model", "claude-sonnet-4-6",
        "--output-format", "json",
        "--max-turns", "30",
        "--cwd", workdir,
        "--allowed-tools", "Read,Edit,Write,Glob,Grep,Bash",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=1200)

    result = json.loads(stdout)
    return PrdOutput(
        prd_path=f"{workdir}/PRD.md",
        ac_path=f"{workdir}/acceptance_criteria.json",
        cost_usd=result["cost_usd"],
        input_tokens=result["input_tokens"],
        output_tokens=result["output_tokens"],
    )
```

### 1.3 待 Day 2 实测项

- [ ] `claude -p` 在云端服务器上能跑（已知装了 Claude Code）
- [ ] `--output-format json` 实际返回字段：`[待实测：列出 keys]`
- [ ] cost_usd / input_tokens / output_tokens 字段是否在 JSON 里：`[待实测]`
- [ ] `--max-turns` 默认值：`[待实测]`
- [ ] 鉴权方式（OAuth login vs API key 环境变量）：`[待实测]`
- [ ] 长任务（30 min+）的 stdout buffering 行为：`[待实测]`
- [ ] 多个 `claude -p` 进程并发是否抢同一 session：`[待实测]`

### 1.4 Day 2 验证命令

```bash
# 在云端跑：生成一段假 PRD
mkdir -p /tmp/aiop-test && cd /tmp/aiop-test
claude -p "请输出一段简短的 PRD（关于'登录页'），用 markdown 格式" \
  --model claude-sonnet-4-6 \
  --output-format json \
  --max-turns 5 \
  > result.json
cat result.json | jq .
```

---

## 2. Codex CLI 调用模板

### 2.1 基础调用（headless）

```bash
codex exec "PROMPT" \
  --cwd /tmp/aiop-work/REQ-20260419-001 \
  --output-format json
```

> ⚠️ Codex CLI 的具体 headless 子命令、参数、认证方式 **必须 Day 2 实测确认**。本节是基于 OpenAI Codex CLI 公开文档的猜测，不是事实。

### 2.2 待 Day 2 实测项

- [ ] Codex CLI 二进制名（`codex` / `codex-cli` / 别的）：`[待实测]`
- [ ] headless 子命令：`[待实测]`
- [ ] 认证方式（Codex Pro 订阅怎么从 CLI 用？OAuth？API key？）：`[待实测：关键]`
- [ ] 是否支持 `--output-format json`：`[待实测]`
- [ ] 是否支持指定 cwd：`[待实测]`
- [ ] 长任务超时 / 续跑 / 增量保存机制：`[待实测]`
- [ ] 多进程并发是否安全：`[待实测]`
- [ ] 与 Claude Code CLI 共存时是否冲突（端口/socket/auth state）：`[待实测]`

### 2.3 Day 2 验证命令

```bash
# 在云端跑：让 Codex 把空文件填成 hello world
mkdir -p /tmp/codex-test && cd /tmp/codex-test
echo "" > hello.py
codex exec "把 hello.py 改成打印 'Hello from Codex'" \
  --cwd $(pwd) \
  > result.txt 2>&1
cat hello.py
cat result.txt
```

### 2.4 备选方案（如果 Codex CLI headless 不可用）

如果 Day 2 发现 Codex CLI 无 headless / 认证不可脚本化：

**Plan B**：用 OpenAI API（`gpt-4-codex` 等价模型）直接调，放弃 Codex Pro 订阅的成本优势但获得稳定性。

**Plan C**：Codex 改用 VSCode 中转——M5 上写一个 VSCode 扩展接收 workflow 触发并把生成结果通过 API 回传。复杂度高，最后选项。

---

## 3. Anthropic API 调用模板

```python
# activities/claude/api.py
from anthropic import AsyncAnthropic

client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

async def claude_api_call(
    model: str,
    system: str,
    messages: list,
    max_tokens: int = 4096,
) -> dict:
    response = await client.messages.create(
        model=model,
        system=system,
        messages=messages,
        max_tokens=max_tokens,
    )
    return {
        "content": response.content[0].text,
        "input_tokens": response.usage.input_tokens,
        "output_tokens": response.usage.output_tokens,
        "cost_usd": _calc_cost(model, response.usage),
    }
```

**模型与单价**（2026-04 现价，需 Day 2 复核）：

| 模型 | input/1M | output/1M | 用途 |
|------|---------|----------|------|
| `claude-haiku-4-5` | $0.80 | $4.00 | 结构化、lite review |
| `claude-sonnet-4-6` | $3.00 | $15.00 | 主力（CLI 内部使用）|
| `claude-opus-4-7` | $15.00 | $75.00 | 暂不用（成本太高）|

---

## 4. OpenAI API 调用模板

```python
# activities/openai/api.py
from openai import AsyncOpenAI

client = AsyncOpenAI(api_key=os.environ["OPENAI_API_KEY"])

async def openai_review(diff: str, design: str) -> dict:
    response = await client.chat.completions.create(
        model="gpt-5",  # [待 Day 2 确认 2026-04 可用模型]
        messages=[
            {"role": "system", "content": REVIEW_SYSTEM_PROMPT},
            {"role": "user", "content": f"DESIGN:\n{design}\n\nDIFF:\n{diff}"},
        ],
        response_format={"type": "json_object"},
    )
    ...
```

---

## 5. 成本估算函数（用于 `reserve_budget`）

```python
# activities/budget.py
ESTIMATES = {
    # activity_type: (avg_input_tokens, avg_output_tokens, model)
    "claude_capture_requirement": (2000, 500, "claude-haiku-4-5"),
    "claude_generate_prd": (15000, 3000, "claude-sonnet-4-6"),
    "claude_generate_design": (30000, 5000, "claude-sonnet-4-6"),
    "claude_generate_tests": (20000, 4000, "claude-sonnet-4-6"),
    "codex_implement": (50000, 10000, "codex-pro"),  # 估算
    "claude_review": (40000, 2000, "claude-sonnet-4-6"),
    "claude_lite_review": (8000, 500, "claude-haiku-4-5"),
    "openai_review": (40000, 2000, "gpt-5"),
}

def estimate_cost(activity_type: str, multiplier: float = 1.5) -> float:
    """保守估算：avg × 1.5（Week 5+ 改为历史 P95 回归）"""
    in_tok, out_tok, model = ESTIMATES[activity_type]
    return _calc_cost(model, in_tok, out_tok) * multiplier
```

`multiplier=1.5` 是 Week 1 起步值，避免 reserve 不足导致频繁触上限。Week 5+ 用 `cost_records` 表的实际数据回归。

---

## 6. 工作目录隔离

每个 req 一个独立 workdir，避免并发污染：

```
/tmp/aiop/
├── REQ-20260419-001/
│   ├── p1/                   # P1 工作区
│   ├── p2/                   # P2 工作区
│   ├── p3/
│   │   ├── healthassit/      # git clone 的项目副本
│   │   ├── PRD.md            # 复制自 git
│   │   ├── DESIGN.md
│   │   └── test_contract.json
│   └── logs/
└── REQ-20260419-002/
    └── ...
```

清理策略：req 进入 `closed` / `cancelled` 后 7 天清理。

---

## Day 2 实测交付物

跑完 §1.4 + §2.3 的命令后，回填本文档所有 `[待实测]` 字段，并把验证用的 `result.json` 提交到 `tests/fixtures/cli_outputs/`。
