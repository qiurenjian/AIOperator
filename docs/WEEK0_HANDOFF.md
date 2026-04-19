# Week 0 交接：用户需亲自执行的物理动作

> 我（Claude）已完成 Week 0 的纸面交付（架构、4 份 spec、骨架）。
> 本文档列出**只能你本人来做**的 12 个动作，按顺序执行。每项有验收标准。
> 完成后回到对话告诉我哪些卡住了，我们再决定 Week 1 是否能按时启动。

---

## 时间预算

| 段 | 预估时长 | 关键依赖 |
|----|---------|---------|
| Day 1 上半段（飞书/Bitable）| 1.5h | 你的飞书管理员权限 |
| Day 2 上半段（CLI 实测）| 1.5h | 云端 SSH 已通 |
| Day 3 上半段（云端起栈）| 2h | docker / sops / age 已装 |
| 总计 | **~5h** 跨 3 天 | |

---

## Day 1 — 飞书侧准备

### A1. 创建 Bitable 数据表
**严格按 [bitable_schema.md](bitable_schema.md) §主表 的 22 列建表。**

操作：
1. 飞书 → 多维表格 → 新建空白表格 `AIOperator · 项目看板`
2. 数据表名 `projects_kanban`
3. 按 6 个分组（A 标识 / B 状态 / C 决策 / D 度量 / E 链接 / F 时间）逐列添加
4. 每列字段类型严格对齐文档（单选选项要全部录入）
5. 创建 5 个视图（🔥 进行中 / ⏸️ 阻塞 / ✅ 已完成 / 💰 预算告急 / 📊 看板视图）

**验收**：
- [ ] 22 列全部建好
- [ ] `lifecycle_state` 单选有 10 个选项
- [ ] `current_phase` 单选有 6 个选项
- [ ] `risk_level` 单选有 4 个选项
- [ ] 5 个视图都能切换
- [ ] 把 `app_token` 和 `table_id` 复制下来（建表 URL 里有）

### A2. 复用 OpenClaw 的飞书应用（或新建）
**推荐：直接复用 OpenClaw ai-pm bot 的应用凭据。**

操作：
1. 找到 OpenClaw 的 `app_id / app_secret / verification_token / encrypt_key`
2. 检查权限是否包含：
   - `bitable:app` 多维表读写（如果没有，去飞书开放平台补加）
   - `im:message` / `im:message:send_as_bot` 卡片消息（已有）
   - `docx:document` 云文档读写（已有）
3. 如果 OpenClaw 应用已废弃或权限不全，再新建应用 `AIOperator`

**验收**：
- [ ] 拿到 `app_id` / `app_secret` / `verification_token` / `encrypt_key`
- [ ] 确认 `bitable:app` 权限已开启

### A3. 配置 Bitable Webhook
1. 在 Bitable 表格的「自动化」中创建流程
2. 触发：当 `priority` / `risk_level` / `cost_cap_usd` / `is_paused` 字段变化
3. 动作：发送 HTTP 请求到 `${INGRESS_PUBLIC_URL}/bitable/webhook`
4. 临时占位 URL 用 ngrok 或先填一个不存在的，等 Day 3 部署完再改

**验收**：
- [ ] 4 个字段都配置了 webhook 触发
- [ ] webhook 配置已保存（可以先指向占位 URL）

### A4. ai-pm Bot 卡片渲染冒烟测试
**目的**：在写代码前先确认 [feishu_cards.md](feishu_cards.md) §1 的 P0 卡片 JSON 在飞书里能渲染。

操作：
1. 在飞书开发者工具的「消息卡片搭建工具」中粘贴 P0 卡片的 `card` 部分 JSON
2. 预览，确认布局符合预期
3. **推荐：用 OpenClaw 现有 ai-pm bot 实际发一张到你自己**（复用现有 bot，不用重新申请）

**验收**：
- [ ] P0 卡片渲染正常（标题、3 个 select、3 个按钮都在）
- [ ] 截图保留 → 提交到 `tests/fixtures/feishu_cards/p0_preview.png`
- [ ] 确认 OpenClaw ai-pm bot 的 `open_id`，写回 `.env.cloud` 的 `FEISHU_BOT_OPEN_ID`

---

## Day 2 — CLI 实测

### B1. 云端环境检查
SSH 到腾讯云 VM 后：

```bash
# 工具是否齐全
which claude && claude --version
which codex && codex --version          # 如未装，先 npm install -g @openai/codex
which docker && docker --version
which docker compose && docker compose version
which sops && which age                 # 加密工具
```

**验收**：
- [ ] `claude` CLI 在
- [ ] `codex` CLI 在（这是 Day 2 最大不确定项）
- [ ] docker / docker-compose 在
- [ ] sops / age 在（缺则 `brew install sops age` 或 apt 等价）

### B2. Claude Code CLI 实测
按 [cli_contracts.md §1.4](cli_contracts.md) 命令跑：

```bash
mkdir -p /tmp/aiop-test && cd /tmp/aiop-test
claude -p "请输出一段简短的 PRD（关于'登录页'），用 markdown 格式" \
  --model claude-sonnet-4-6 \
  --output-format json \
  --max-turns 5 \
  > result.json
cat result.json | jq .
```

**回填到 cli_contracts.md §1.3**：
- [ ] JSON 输出实际有哪些 keys？
- [ ] 是否包含 `cost_usd` / `input_tokens` / `output_tokens`？
- [ ] `--max-turns` 默认值是多少？（不传时）
- [ ] 鉴权方式：oauth 还是 API key？
- [ ] 把 `result.json` 复制到 `tests/fixtures/cli_outputs/claude_p1_smoke.json`

### B3. Codex CLI 实测（**最高风险项**）

```bash
mkdir -p /tmp/codex-test && cd /tmp/codex-test
echo "" > hello.py
codex exec "把 hello.py 改成打印 'Hello from Codex'" \
  --cwd $(pwd) \
  > result.txt 2>&1
cat hello.py
cat result.txt
```

**回填到 cli_contracts.md §2.2**：
- [ ] CLI 二进制名 / headless 子命令实际是什么？
- [ ] Codex Pro 订阅怎么从 CLI 用？
- [ ] 是否支持 `--output-format json`？
- [ ] 多进程并发是否安全？

**如果跑不通**：直接告诉我，我们立刻切 Plan B（OpenAI API 直调）改架构图 §17，**不要硬磕 Codex CLI**。

**验收**：
- [ ] hello.py 内容确实变了，或确认走 Plan B

### B4. Anthropic / OpenAI API 鉴权
```bash
export ANTHROPIC_API_KEY=sk-ant-...
curl -s https://api.anthropic.com/v1/messages \
  -H "x-api-key: $ANTHROPIC_API_KEY" \
  -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"claude-haiku-4-5","max_tokens":50,"messages":[{"role":"user","content":"ping"}]}'

export OPENAI_API_KEY=sk-...
curl -s https://api.openai.com/v1/models | jq '.data[] | select(.id|test("gpt-5"))'
```

**验收**：
- [ ] Haiku 返回正常 200
- [ ] OpenAI 列出的模型里有 gpt-5（或确认实际可用的最新模型名，回填 `OPENAI_REVIEW_MODEL`）

---

## Day 3 — 起栈

### C1. 准备 .env.cloud
```bash
cd ~/projects/AIOperator
cp .env.example .env.cloud
# 编辑 .env.cloud，把所有 CHANGEME 替换成真值
```

**验收**：
- [ ] 所有 `CHANGEME` 都已替换或留空（明确不需要的）
- [ ] WORKER_TASK_QUEUES 取了 cloud 那一组

### C2. sops + age 加密
```bash
# 生成一对 age 密钥（只生一次，所有节点共用 public，私钥分发到节点）
age-keygen -o ~/.config/sops/age/keys.txt
# 输出形如 "age1xxx..."，把这串 public key 写回 .env.example 的 SOPS_AGE_RECIPIENTS

# 加密 .env.cloud
sops --age $(grep "public key" ~/.config/sops/age/keys.txt | cut -d: -f2 | tr -d ' ') \
     -e -i .env.cloud
```

**验收**：
- [ ] `cat .env.cloud` 显示加密内容（看到 ENC[AES256_GCM,...]）
- [ ] `sops -d .env.cloud` 能解出明文
- [ ] `~/.config/sops/age/keys.txt` 的私钥已**额外备份**（比如 1Password）

### C3. 起栈
```bash
cd ~/projects/AIOperator/deploy
# Dockerfile 还没写（Week 1 Day 1 我会写），所以先只起 postgres + temporal
docker compose --env-file <(sops -d ../.env.cloud) up -d postgres temporal temporal-ui
```

**验收**：
- [ ] `docker ps` 看到 3 个容器 healthy
- [ ] `curl localhost:8088` 能打开 Temporal UI
- [ ] `tctl --address localhost:7233 namespace describe aiop` 返回 namespace info

### C4. 拉公网域名 + 反向代理
ingress 后续要给飞书 webhook 用，必须有 HTTPS：

选项：
- **快**：Cloudflare Tunnel（免费、不用 IP）`cloudflared tunnel ...`
- **稳**：备案后用 Nginx + Let's Encrypt
- **临时**：ngrok（仅开发期）

**验收**：
- [ ] 拿到一个公网 HTTPS URL，写回 `.env.cloud` 的 `INGRESS_PUBLIC_URL`
- [ ] 把这个 URL 填进 Day 1 的 Bitable webhook 配置

---

## 完成后回报清单

请把以下信息粘贴回对话，我据此判断 Week 1 能否启动：

```
A1 Bitable: ✅/❌    app_token=basc...  table_id=tbl...
A2 飞书应用: ✅/❌    app_id=cli...
A3 Webhook: ✅/❌
A4 卡片预览: ✅/❌
B1 工具齐全: ✅/❌    缺什么：
B2 Claude CLI: ✅/❌  cost_usd 字段在不在：
B3 Codex CLI: ✅/❌  → 是否需要切 Plan B：
B4 API 鉴权: ✅/❌    OpenAI 实际可用模型：
C1 .env: ✅/❌
C2 sops: ✅/❌
C3 起栈: ✅/❌       Temporal UI URL：
C4 公网: ✅/❌       INGRESS_PUBLIC_URL：

阻塞 / 疑问：
```

---

## 参考链接

- [docs/ARCHITECTURE_v2.md](ARCHITECTURE_v2.md) — 总架构
- [docs/feishu_cards.md](feishu_cards.md) — 卡片 JSON
- [docs/bitable_schema.md](bitable_schema.md) — Bitable 表结构
- [docs/cli_contracts.md](cli_contracts.md) — CLI/API 调用模板
- [.env.example](../.env.example) — 全部环境变量
- [deploy/docker-compose.yml](../deploy/docker-compose.yml) — 云端栈
