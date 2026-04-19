# Bitable Schema 规范（Week 0 Day 1）

> 本文定义 AIOperator 在飞书多维表格中的看板结构。Bitable 是**运营镜像**和**人工输入入口**，不是流程权威（流程权威 = Temporal workflow + Postgres 投影表）。
>
> 表名建议：`AIOperator · 项目看板`
> 数据表 ID 写入 [config/feishu.yaml](../config/feishu.yaml) 的 `bitable.app_token` 和 `bitable.tables.kanban_id`。

---

## 主表：`projects_kanban`（共 22 列）

### A. 标识列

| 字段名 | 类型 | 必填 | 用户可编辑 | 说明 |
|--------|------|------|-----------|------|
| `req_id` | 单行文本（主键）| ✅ | ❌ | 与 Temporal `workflow_id` 一致，格式 `REQ-YYYYMMDD-NNN` |
| `title` | 单行文本 | ✅ | ✅ | 需求标题（Claude 在 P0 生成，用户可改）|
| `project` | 单选 | ✅ | ❌ | 选项：`HealthAssit` / `MaaS` / `（其他后续添加）` |
| `created_by` | 人员 | ✅ | ❌ | 发起人（飞书 user_id）|

### B. 状态列

| 字段名 | 类型 | 必填 | 用户可编辑 | 说明 |
|--------|------|------|-----------|------|
| `lifecycle_state` | 单选 | ✅ | ❌ | 选项：`captured`, `requirement_confirmed`, `prd_approved`, `design_approved`, `code_approved`, `released`, `closed`, `paused`, `blocked`, `cancelled` |
| `current_phase` | 单选 | ✅ | ❌ | 选项：`P0`, `P1`, `P2`, `P3`, `P4`, `P5` |
| `current_phase_substate` | 单行文本 | ❌ | ❌ | 自由文本，如 `awaiting_human:budget_exceeded` |

### C. 决策列（**用户可改**，触发 operator_action webhook）

| 字段名 | 类型 | 必填 | 用户可编辑 | 改动行为 |
|--------|------|------|-----------|---------|
| `priority` | 单选 | ✅ | ✅ | 改 → `change_priority` operator_action → workflow 重新排队 |
| `risk_level` | 单选 | ✅ | ✅ | 选项：`low/medium/high/release-critical`；改 → `change_risk_level`；降级需在飞书卡片二次确认 |
| `cost_cap_usd` | 数字 | ✅ | ✅ | 改 → `extend_cost_cap` |
| `is_paused` | 复选框 | ❌ | ✅ | 勾选 → `pause`；取消 → `resume` |

### D. 度量列（只读）

| 字段名 | 类型 | 必填 | 用户可编辑 | 说明 |
|--------|------|------|-----------|------|
| `cost_used_usd` | 数字 | ❌ | ❌ | 实时累计（worker 异步刷新）|
| `cost_reserved_usd` | 数字 | ❌ | ❌ | 当前预留（reserve 已发但 reconcile 未完成）|
| `cycle_time_h` | 数字 | ❌ | ❌ | 从 captured 到 released 的小时数（released 后定值）|
| `rework_count` | 数字 | ❌ | ❌ | request_changes / reject 累计次数 |

### E. 交付物链接列（只读）

| 字段名 | 类型 | 必填 | 用户可编辑 | 说明 |
|--------|------|------|-----------|------|
| `prd_doc_url` | 链接 | ❌ | ❌ | 飞书文档 URL |
| `design_doc_url` | 链接 | ❌ | ❌ | 飞书文档 URL |
| `code_pr_url` | 链接 | ❌ | ❌ | GitHub/GitLab PR URL |
| `review_doc_url` | 链接 | ❌ | ❌ | 评审报告飞书文档 |
| `release_record_url` | 链接 | ❌ | ❌ | 发布记录文档 |

### F. 时间戳列（只读）

| 字段名 | 类型 | 必填 | 用户可编辑 | 说明 |
|--------|------|------|-----------|------|
| `created_at` | 日期时间 | ✅ | ❌ | |
| `updated_at` | 日期时间 | ✅ | ❌ | |

---

## 视图配置

建议在 Bitable 中预设以下视图：

| 视图名 | 筛选 | 排序 | 用途 |
|--------|------|------|------|
| **🔥 进行中** | `lifecycle_state ∉ {released, closed, cancelled}` | `priority` 升序，`updated_at` 降序 | 默认主看板 |
| **⏸️ 阻塞** | `lifecycle_state = blocked` 或 `current_phase_substate 含 awaiting_human` | `updated_at` 降序 | 需要人工的需求 |
| **✅ 已完成** | `lifecycle_state ∈ {released, closed}` | `created_at` 降序 | 历史归档 |
| **💰 预算告急** | `cost_used_usd / cost_cap_usd >= 0.8` | `cost_used_usd` 降序 | 成本监控 |
| **📊 看板视图** | 全部 | 按 `current_phase` 分组 | Kanban 风格 |

---

## Webhook 配置

### 触发条件

只对 **C. 决策列** 的字段变化触发 webhook（避免无意义事件）：

- `priority` 变化
- `risk_level` 变化
- `cost_cap_usd` 变化
- `is_paused` 变化

### Webhook payload → operator_action 映射

```python
# ingress 处理伪代码
def on_bitable_webhook(event):
    req_id = event["record"]["fields"]["req_id"]
    field_name = event["changed_field"]
    old_value = event["old_value"]
    new_value = event["new_value"]
    actor = event["operator_user_id"]

    action_map = {
        "priority": "change_priority",
        "risk_level": "change_risk_level",
        "cost_cap_usd": "extend_cost_cap",
        "is_paused": "pause" if new_value else "resume",
    }
    action_type = action_map[field_name]

    # 1. 写 operator_actions 表（含幂等键 = event["event_id"]）
    insert_operator_action(
        req_id=req_id,
        action_type=action_type,
        payload={"old": old_value, "new": new_value},
        requested_by=actor,
        idempotency_key=event["event_id"],
    )
    # 2. 调 Temporal signal
    temporal_client.signal_workflow(req_id, action_type, payload)
```

### 冲突解决

如果 workflow 自身正在写 Bitable（如刷新 `cost_used_usd`）的同时用户改了 `priority`：

- Bitable webhook 一定带 `operator_user_id`，区分人 vs 机器人写
- 机器人写不触发 webhook（飞书原生支持过滤 `app_id`）
- 人写永远胜出（最后写者优先）

---

## 副表（Phase 1 不建，按需补）

| 表名 | 用途 | 建表时机 |
|------|------|---------|
| `cost_breakdown` | 按 activity 拆分成本 | Week 4 |
| `worker_status` | 实时 worker 健康看板 | Week 5 |
| `release_history` | 发布历史 | Week 4 |
| `anti_patterns_index` | 学习库索引 | Week 5+ |

主表 `projects_kanban` 是 Week 1 唯一必须建的。

---

## 待用户在 Day 1 创建

- [ ] 在飞书多维表格新建表 `AIOperator · 项目看板`
- [ ] 按上表 22 列建好 `projects_kanban` 数据表
- [ ] 配置 5 个视图
- [ ] 在 Bitable 设置中创建 webhook，目标 URL = ingress 的 `/bitable/webhook`（先用 ngrok / Tailscale URL 占位）
- [ ] 把 `app_token`、`table_id` 写到 [config/feishu.yaml](../config/feishu.yaml)

---

## Postgres 投影表对齐

`projects_kanban` 与 [docs/ARCHITECTURE_v2.md](ARCHITECTURE_v2.md) §9.1 的 `aiop.requirements` 表字段一一对应：

| Bitable 列 | Postgres 列 | 同步方向 |
|-----------|------------|---------|
| `req_id` | `req_id` | bidi（主键）|
| `title` | `title` | bidi |
| `project` | `project` | DB → Bitable |
| `lifecycle_state` | `lifecycle_state` | DB → Bitable |
| `current_phase` | `current_phase` | DB → Bitable |
| `priority` | `priority` | bidi |
| `risk_level` | `risk_level` | bidi |
| `cost_cap_usd` | `cost_cap_usd` | bidi |
| `cost_used_usd` | `cost_used_usd` | DB → Bitable |
| `cost_reserved_usd` | (计算字段) | DB → Bitable |
| `*_url` | `artifacts_index` join | DB → Bitable |
| `created_at` / `updated_at` | 同名 | DB → Bitable |
