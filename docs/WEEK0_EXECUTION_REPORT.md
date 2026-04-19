# Week 0 执行报告（2026-04-19）

## 自动化完成项

### ✅ A2 飞书应用凭据（已从 OpenClaw 提取）
- **app_id**: `cli_a9248a92423a9bb5`
- **app_secret**: `0ip4e9Z7PEU7g3KZyK0ghgfFoVsPpbi0`
- **bot_open_id**: `ou_1aaaf697e29875ac3a20193f3b9811f0`
- **verification_token**: [待飞书开放平台查询]
- **encrypt_key**: [待飞书开放平台查询，如未启用可留空]
- **权限检查**: 需补加 `bitable:app` 权限

### ✅ B1 云端工具检查
- Claude Code CLI: **2.1.88** ✅
- Docker: **29.3.0** ✅
- sops/age: **缺失** ❌（需安装）

### ✅ B2 Claude CLI 实测（M5 + Cloud 双环境）
**M5 环境**:
- 版本: 2.1.110
- 测试成本: $0.013392
- JSON 字段: `total_cost_usd`, `usage.input_tokens`, `usage.output_tokens` ✅
- 鉴权: OAuth ✅

**Cloud 环境**:
- 版本: 2.1.88
- 测试成本: $0.062
- 同样 JSON 结构 ✅

### ❌ B3 Codex CLI 实测 → **触发 Plan B**
- 云端服务器**没有安装 Codex CLI**
- 搜索结果: 无任何 codex 相关二进制或 npm 包
- **决策**: 按 cli_contracts.md §2.4 Plan B，改用 **OpenAI API 直调**

## 待用户手动执行项

### ⏳ A1 创建 Bitable 数据表
按 [bitable_schema.md](bitable_schema.md) 建 22 列表，回填：
- `FEISHU_BITABLE_APP_TOKEN`
- `FEISHU_BITABLE_KANBAN_TABLE_ID`

### ⏳ A2 补充飞书应用权限
去飞书开放平台为 `cli_a9248a92423a9bb5` 补加 `bitable:app` 权限

### ⏳ A3 配置 Bitable Webhook
4 个字段触发 webhook → `${INGRESS_PUBLIC_URL}/bitable/webhook`

### ⏳ A4 卡片渲染测试
用飞书卡片搭建工具预览 [feishu_cards.md](feishu_cards.md) P0 卡片 JSON

### ⏳ B4 API 鉴权测试
需要你提供：
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`

### ⏳ C1 完善 .env.cloud
已创建 `.env.cloud` 并填入 ai-pm bot 凭据，还需补充：
- Anthropic/OpenAI API keys
- GitHub/GitLab tokens
- HealthAssit/MaaS 仓库地址
- 飞书 verification_token / encrypt_key
- Bitable app_token / table_id
- 飞书文档目录 parent_token

### ⏳ C2 安装 sops + age
云端执行：
```bash
# 安装 age
wget https://github.com/FiloSottile/age/releases/download/v1.1.1/age-v1.1.1-linux-amd64.tar.gz
tar xzf age-v1.1.1-linux-amd64.tar.gz
sudo mv age/age age/age-keygen /usr/local/bin/

# 安装 sops
wget https://github.com/getsops/sops/releases/download/v3.8.1/sops-v3.8.1.linux.amd64
sudo mv sops-v3.8.1.linux.amd64 /usr/local/bin/sops
sudo chmod +x /usr/local/bin/sops

# 生成密钥
mkdir -p ~/.config/sops/age
age-keygen -o ~/.config/sops/age/keys.txt
# 把 public key 写回 .env.cloud 的 SOPS_AGE_RECIPIENTS
```

### ⏳ C3 起栈（等 C1+C2 完成后）
```bash
cd ~/projects/AIOperator/deploy
sops -e -i ../.env.cloud  # 加密
docker compose --env-file <(sops -d ../.env.cloud) up -d postgres temporal temporal-ui
```

### ⏳ C4 配置公网域名
选择 Cloudflare Tunnel / ngrok / 备案域名，回填 `INGRESS_PUBLIC_URL`

## 架构调整决策

### 🔄 Plan B: Codex CLI → OpenAI API
**原因**: 云端无 Codex CLI，且 Codex Pro 订阅的 CLI headless 机制未公开

**变更**:
1. `codex_implement` activity 改为调用 OpenAI API（`gpt-4` 或 `o1`）
2. cli_contracts.md §2 标记为"已确认不可用"
3. ARCHITECTURE_v2.md §17 的 activity 清单更新：`codex_implement` 的 task_queue 改为 `llm-cloud`（不需要独立 Codex 节点）

**成本影响**: OpenAI API 比 Codex Pro 订阅贵，但可控（已有 `reserve_budget` 守卫）

## 下一步

1. **你手动完成** A1/A2/A3/A4/B4/C1/C2/C3/C4
2. **我立刻执行** Plan B 架构调整（更新 cli_contracts.md + ARCHITECTURE_v2.md）
3. 你完成后回报，我们进入 **Week 1 Day 1 编码**
