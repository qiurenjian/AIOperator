# 飞书卡片 Schema 规范（Week 0 Day 1）

> 本文定义 AIOperator 与用户之间通过飞书卡片交互的 3 类卡片 JSON schema。所有 button `value` 字段必须包含 `req_id + phase + action`，使 ingress 能反查 workflow 实例并发 signal。
>
> 飞书卡片官方文档：<https://open.feishu.cn/document/uAjLw4CM/ukzMukzMukzM/feishu-cards/quick-start/getting-started>
>
> 所有卡片使用 **2.0 schema**（`config.update_multi: true`）以支持局部更新。

---

## 通用约定

### Button value 通用字段

每个按钮的 `value` 字段固定包含：

```json
{
  "req_id": "REQ-20260419-001",
  "phase": "p1_prd",
  "action": "approve",
  "card_msg_id": "om_xxxxxxxx"
}
```

- `req_id` = workflow_id（用于 Temporal signal 路由）
- `phase` = 当前阶段标识
- `action` = 用户动作（`approve` / `reject` / `request_changes` / `change_risk_level` / ...）
- `card_msg_id` = 卡片消息 ID（用于卡片局部更新回写"已批准 by xxx at hh:mm"）

附加业务字段按卡片类型扩展。

### Card callback 处理流程

```
用户点击按钮
  ↓
飞书 → ingress POST /feishu/card_callback (含 value 全文)
  ↓
ingress 写 operator_actions 表（含 raw payload + actor user_id）
  ↓
ingress 调 Temporal client.signal_workflow(req_id, signal_name, payload)
  ↓
ingress 返回新卡片 JSON（标记"处理中"）
  ↓
workflow 接收 signal → 推进状态 → 调 feishu_send_card 更新卡片为最终状态
```

---

## 卡片 1：P0 需求确认卡

**触发**：用户在飞书 @ai-pm 发送需求文本后，Claude 结构化完成。

**用户必须做出的 3 个决策**：项目归属、风险级别、确认/编辑/丢弃。

```json
{
  "schema": "2.0",
  "config": { "update_multi": true, "wide_screen_mode": true },
  "header": {
    "template": "blue",
    "title": { "tag": "plain_text", "content": "📥 新需求待确认 · REQ-20260419-001" }
  },
  "body": {
    "elements": [
      {
        "tag": "div",
        "fields": [
          { "is_short": true, "text": { "tag": "lark_md", "content": "**项目**\n下方选择" } },
          { "is_short": true, "text": { "tag": "lark_md", "content": "**优先级**\n下方选择" } }
        ]
      },
      {
        "tag": "markdown",
        "content": "**📝 需求摘要**\n开发一个登录页，支持邮箱+密码、错误提示、生物识别。"
      },
      {
        "tag": "markdown",
        "content": "**✅ 初步验收标准（共 3 条）**\n- AC-001: 错误密码显示提示\n- AC-002: 支持生物识别\n- AC-003: 首次登录引导画像"
      },
      {
        "tag": "markdown",
        "content": "**⚠️ 建议风险级别：medium**\n触发原因：涉及 src/auth/ 目录"
      },
      { "tag": "hr" },
      {
        "tag": "action",
        "actions": [
          {
            "tag": "select_static",
            "placeholder": { "tag": "plain_text", "content": "选择项目" },
            "value": { "req_id": "REQ-20260419-001", "phase": "p0_capture", "action": "set_project" },
            "options": [
              { "text": { "tag": "plain_text", "content": "HealthAssit" }, "value": "healthassit" },
              { "text": { "tag": "plain_text", "content": "MaaS" }, "value": "maas" }
            ]
          },
          {
            "tag": "select_static",
            "placeholder": { "tag": "plain_text", "content": "选择优先级" },
            "value": { "req_id": "REQ-20260419-001", "phase": "p0_capture", "action": "set_priority" },
            "options": [
              { "text": { "tag": "plain_text", "content": "P0 紧急" }, "value": "P0" },
              { "text": { "tag": "plain_text", "content": "P1 普通" }, "value": "P1" },
              { "text": { "tag": "plain_text", "content": "P2 次要" }, "value": "P2" }
            ]
          },
          {
            "tag": "select_static",
            "placeholder": { "tag": "plain_text", "content": "选择风险级别" },
            "initial_option": "medium",
            "value": { "req_id": "REQ-20260419-001", "phase": "p0_capture", "action": "set_risk_level" },
            "options": [
              { "text": { "tag": "plain_text", "content": "low 小改" }, "value": "low" },
              { "text": { "tag": "plain_text", "content": "medium 普通" }, "value": "medium" },
              { "text": { "tag": "plain_text", "content": "high 核心" }, "value": "high" },
              { "text": { "tag": "plain_text", "content": "release-critical 上线/支付" }, "value": "release-critical" }
            ]
          }
        ]
      },
      {
        "tag": "action",
        "actions": [
          {
            "tag": "button",
            "text": { "tag": "plain_text", "content": "✅ 确认开工" },
            "type": "primary",
            "value": { "req_id": "REQ-20260419-001", "phase": "p0_capture", "action": "confirm" }
          },
          {
            "tag": "button",
            "text": { "tag": "plain_text", "content": "✏️ 我要修改需求" },
            "type": "default",
            "value": { "req_id": "REQ-20260419-001", "phase": "p0_capture", "action": "request_edit" }
          },
          {
            "tag": "button",
            "text": { "tag": "plain_text", "content": "❌ 丢弃" },
            "type": "danger",
            "value": { "req_id": "REQ-20260419-001", "phase": "p0_capture", "action": "discard" }
          }
        ]
      }
    ]
  }
}
```

**Signal 映射**：
- `set_project` / `set_priority` / `set_risk_level` → workflow query 字段更新（不触发推进）
- `confirm` → signal `confirm_capture`（推进到 P1）
- `request_edit` → signal `request_changes_p0`（workflow 等待用户在群里再发一段补充）
- `discard` → signal `cancel`（workflow 终止）

---

## 卡片 2：阶段审批卡（P1 PRD / P2 DESIGN / P3 CODE / P4 RELEASE 通用）

**触发**：每个阶段产出完成 + 评审通过后。

**模板字段**（按 phase 替换标题、文档链接、评审摘要）：

```json
{
  "schema": "2.0",
  "config": { "update_multi": true, "wide_screen_mode": true },
  "header": {
    "template": "green",
    "title": { "tag": "plain_text", "content": "📋 PRD 待审批 · REQ-20260419-001" }
  },
  "body": {
    "elements": [
      {
        "tag": "div",
        "fields": [
          { "is_short": true, "text": { "tag": "lark_md", "content": "**项目**\nHealthAssit" } },
          { "is_short": true, "text": { "tag": "lark_md", "content": "**优先级 / 风险**\nP1 / medium" } },
          { "is_short": true, "text": { "tag": "lark_md", "content": "**已用预算**\n$1.20 / $15" } },
          { "is_short": true, "text": { "tag": "lark_md", "content": "**耗时**\n12 min" } }
        ]
      },
      {
        "tag": "markdown",
        "content": "**📄 文档链接**\n- [完整 PRD（飞书文档）](https://example.feishu.cn/docs/xxx)\n- [Git 提交](https://github.com/user/healthassit/commit/abc123)"
      },
      {
        "tag": "markdown",
        "content": "**🔍 自动评审摘要**\n- AC 编号完整 ✓\n- 全部 AC 可映射到测试 ✓\n- 范围清晰 ✓\n- 依赖：无外部依赖"
      },
      {
        "tag": "markdown",
        "content": "**⚠️ 关注点**\n- 生物识别需要 iOS/Android 分别实现\n- AC-003 引导流程未定义画像字段"
      },
      { "tag": "hr" },
      {
        "tag": "action",
        "actions": [
          {
            "tag": "button",
            "text": { "tag": "plain_text", "content": "✅ 批准进入下一阶段" },
            "type": "primary",
            "value": { "req_id": "REQ-20260419-001", "phase": "p1_prd", "action": "approve" }
          },
          {
            "tag": "button",
            "text": { "tag": "plain_text", "content": "🔁 要求返工" },
            "type": "default",
            "value": { "req_id": "REQ-20260419-001", "phase": "p1_prd", "action": "request_changes" }
          },
          {
            "tag": "button",
            "text": { "tag": "plain_text", "content": "❌ 驳回" },
            "type": "danger",
            "value": { "req_id": "REQ-20260419-001", "phase": "p1_prd", "action": "reject" }
          }
        ]
      },
      {
        "tag": "note",
        "elements": [
          { "tag": "plain_text", "content": "💡 在飞书表格直接修改字段也会触发对应的 operator_action" }
        ]
      }
    ]
  }
}
```

**Signal 映射**（按 phase 不同 signal 名变化）：
- P1: `approve_prd` / `request_changes_prd` / `reject_prd`
- P2: `approve_design` / `request_changes_design` / `reject_design`
- P3: `approve_merge` / `request_changes_code` / `reject_code`
- P4 (staging): `approve_staging_release`
- P4 (prod): `approve_prod_release`（release-critical 时附 checklist 卡片，见卡片 3 变体）

**release-critical P4 prod 二次确认**：批准后弹出二次确认浮层（`confirm_text` 字段）+ checklist 必须全勾。

---

## 卡片 3：人工介入卡（阻塞通知 / 预算请求 / 凭据失败）

**触发**：workflow 进入 `awaiting_human` 状态。

```json
{
  "schema": "2.0",
  "config": { "update_multi": true, "wide_screen_mode": true },
  "header": {
    "template": "orange",
    "title": { "tag": "plain_text", "content": "⚠️ 需要人工介入 · REQ-20260419-001" }
  },
  "body": {
    "elements": [
      {
        "tag": "div",
        "fields": [
          { "is_short": true, "text": { "tag": "lark_md", "content": "**当前阶段**\nP3 实现" } },
          { "is_short": true, "text": { "tag": "lark_md", "content": "**阻塞类型**\n预算超限" } }
        ]
      },
      {
        "tag": "markdown",
        "content": "**📛 阻塞原因**\n累计成本已达 $14.50，下次 codex_implement 预估需 $2.30，将超出 cost_cap=$15。"
      },
      {
        "tag": "markdown",
        "content": "**🤖 AI 已尝试**\n- 2 轮 Codex 实现，剩余 1 个测试不通过\n- 1 次 Claude 评审建议改用更小函数粒度"
      },
      {
        "tag": "markdown",
        "content": "**💡 推荐下一步**\n1. 加 $5 预算继续，或\n2. 终止本次需求并复盘"
      },
      { "tag": "hr" },
      {
        "tag": "action",
        "actions": [
          {
            "tag": "button",
            "text": { "tag": "plain_text", "content": "💰 加 $5 继续" },
            "type": "primary",
            "value": { "req_id": "REQ-20260419-001", "phase": "p3_impl", "action": "extend_cost_cap", "amount": 5 }
          },
          {
            "tag": "button",
            "text": { "tag": "plain_text", "content": "💰 加 $10 继续" },
            "type": "default",
            "value": { "req_id": "REQ-20260419-001", "phase": "p3_impl", "action": "extend_cost_cap", "amount": 10 }
          },
          {
            "tag": "button",
            "text": { "tag": "plain_text", "content": "🛑 终止需求" },
            "type": "danger",
            "value": { "req_id": "REQ-20260419-001", "phase": "p3_impl", "action": "cancel" }
          }
        ]
      }
    ]
  }
}
```

**变体**（按 `block_type` 字段切换提示文案 + 按钮组）：
- `block_type: budget_exceeded` → 加预算 / 终止
- `block_type: ios_credentials_invalid` → 提示用户更新证书 + "已更新，重试"按钮
- `block_type: lock_conflict` → 显示冲突需求 + "等待 / 抢锁"按钮
- `block_type: tdd_gate_failed` → 显示哪条 AC 没测试 + "我来补 / 让 AI 重写"

---

## ingress 实现要点

1. **签名校验**：飞书每个回调都带 `X-Lark-Signature`，必须验证
2. **幂等**：同一 `card_msg_id + action` 多次到达只执行一次（Postgres `operator_actions` unique 约束）
3. **超时回退**：调 Temporal signal 失败时返回卡片"系统繁忙，请稍后重试"，不阻塞用户
4. **卡片更新**：signal 成功后调 `feishu_card_update` activity 把卡片头部加 `✅ 已批准 by Yvetteqf at 14:32`

---

## 待用户在 Day 1 验证

- [ ] 在 ai-pm 机器人上发送一张卡片 1，确认能正常渲染
- [ ] 点击任一按钮，确认 ingress 能收到回调（先 echo 到日志）
- [ ] 验证 `X-Lark-Signature` 校验逻辑
- [ ] 验证卡片局部更新（替换头部颜色 + 加批注）能成功
