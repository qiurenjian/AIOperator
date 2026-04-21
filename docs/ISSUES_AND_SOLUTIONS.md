# 问题分析和解决方案

## 问题 1: 点击"改写需求"按钮报错

### 问题分析

从代码分析，"改写需求"按钮的处理流程：

1. 用户点击卡片上的"改写需求"按钮
2. 飞书发送 card callback 到 `handle_card_callback`
3. 解析 action 为 `p0_revise`
4. 发送 `p0_revise` 信号到 Temporal workflow
5. Workflow 接收信号并处理

**可能的原因**：

1. **Workflow 已完成**：如果 workflow 已经进入 P1 阶段或完成，无法再接收 P0 阶段的信号
2. **Temporal 连接问题**：worker 或 Temporal 服务未运行
3. **信号处理逻辑问题**：workflow 中的 `p0_revise` 信号处理可能有 bug

### 解决方案

#### 方案 1: 检查 Workflow 状态（推荐）

```bash
# 查看 Temporal UI
# 访问 http://localhost:8088
# 找到对应的 workflow，查看当前状态和历史
```

#### 方案 2: 查看错误日志

```bash
cd deploy
docker compose logs feishu-connector --tail=100 | grep -i error
docker compose logs worker-cloud --tail=100 | grep -i error
```

#### 方案 3: 改进错误处理

在 `apps/feishu_connector/main.py` 的 `handle_card_callback` 函数中添加更详细的错误处理：

```python
async def handle_card_callback(event):
    """处理消息卡片回调"""
    try:
        action = event.action
        value = json.loads(action.value) if isinstance(action.value, str) else action.value
        
        log.info("received card callback: %s", value)
        
        action_type = value.get("action")
        workflow_id = value.get("workflow_id")
        
        if not workflow_id:
            log.warning("card callback missing workflow_id")
            return
        
        # 发送信号到 workflow
        client = await get_temporal_client()
        handle = client.get_workflow_handle(workflow_id)
        
        # 先检查 workflow 状态
        try:
            status = await handle.query("status")
            current_phase = status.get("phase", "")
            lifecycle_state = status.get("lifecycle_state", "")
            
            log.info("workflow %s status: phase=%s, lifecycle=%s", 
                    workflow_id, current_phase, lifecycle_state)
            
            # 如果 workflow 已完成，返回错误
            if lifecycle_state in ["approved", "cancelled", "revision_requested"]:
                log.warning("workflow %s already completed: %s", workflow_id, lifecycle_state)
                # TODO: 发送错误消息到飞书
                return
                
        except Exception as e:
            log.error("failed to query workflow status: %s", e)
            # 继续尝试发送信号
        
        # 发送信号
        if action_type == "p0_revise":
            await handle.signal("p0_revise")
            log.info("sent signal p0_revise to workflow %s", workflow_id)
            
    except Exception as e:
        log.error("failed to handle card callback: %s", e, exc_info=True)
        # TODO: 发送错误消息到飞书
```

#### 方案 4: 添加用户友好的错误提示

修改 workflow 的信号处理，如果状态不对，返回友好提示：

```python
@workflow.signal
def p0_revise(self, by: str = "") -> None:
    """请求改写需求"""
    if self.current_phase != "P0":
        log.warning("cannot revise requirement in phase %s", self.current_phase)
        # 记录错误，但不抛异常（避免 workflow 失败）
        return
    
    self._p0_revise_requested = True
```

---

## 问题 2: 使用飞书表格统一管理项目和需求

### 现状分析

**已有内容**：
- ✅ 飞书表格 schema 设计文档：`docs/bitable_schema.md`
- ✅ 配置已添加：
  - `FEISHU_BITABLE_APP_TOKEN=Yyt9bLucna2jhRs6hHlcOssQnQf`
  - `FEISHU_BITABLE_KANBAN_TABLE_ID=tbl9YkcM1WWGasLh`
- ✅ Worker 已配置 `bitable-sync` 队列

**缺失内容**：
- ❌ Bitable 同步 activity 实现（`activities/bitable/` 目录为空）
- ❌ Bitable webhook 处理器
- ❌ Workflow 中的 bitable 同步逻辑

### 飞书表格功能设计

根据 `docs/bitable_schema.md`，飞书表格应该包含：

#### 主表字段（22列）

**A. 标识列**：
- `req_id`：需求 ID（主键）
- `title`：需求标题
- `project`：项目名称（HealthAssit / MaaS）
- `created_by`：发起人

**B. 状态列**：
- `lifecycle_state`：生命周期状态
- `current_phase`：当前阶段（P0-P5）
- `current_phase_substate`：子状态

**C. 决策列（用户可编辑）**：
- `priority`：优先级
- `risk_level`：风险等级
- `cost_cap_usd`：成本上限
- `is_paused`：是否暂停

**D. 度量列**：
- `cost_used_usd`：已用成本
- `cost_reserved_usd`：预留成本
- `cycle_time_h`：周期时间
- `rework_count`：返工次数

**E. 交付物链接**：
- `prd_doc_url`：PRD 文档链接
- `design_doc_url`：设计文档链接
- `code_pr_url`：代码 PR 链接
- `review_doc_url`：评审报告链接
- `release_record_url`：发布记录链接

**F. 时间戳**：
- `created_at`：创建时间
- `updated_at`：更新时间

#### 预设视图

1. **🔥 进行中**：显示所有进行中的需求
2. **⏸️ 阻塞**：显示需要人工介入的需求
3. **✅ 已完成**：历史归档
4. **💰 预算告急**：成本超过 80% 的需求
5. **📊 看板视图**：按阶段分组的 Kanban

### 实现方案

#### 阶段 1: 基础同步（Week 1 Day 2）

**目标**：Workflow 完成后自动同步到飞书表格

**实现步骤**：

1. **创建 Bitable Activity**

```python
# activities/bitable/sync.py
from temporalio import activity
from lark_oapi import Client
from lark_oapi.api.bitable.v1 import *

@activity.defn(name="bitable_sync_requirement")
async def bitable_sync_requirement(req_data: dict) -> None:
    """同步需求到飞书表格"""
    settings = get_settings()
    
    client = Client.builder() \
        .app_id(settings.feishu_app_id) \
        .app_secret(settings.feishu_app_secret) \
        .build()
    
    # 构建记录数据
    record = {
        "fields": {
            "req_id": req_data["req_id"],
            "title": req_data["title"],
            "project": req_data["project"],
            "created_by": req_data["created_by"],
            "lifecycle_state": req_data["lifecycle_state"],
            "current_phase": req_data["current_phase"],
            "cost_used_usd": req_data.get("cost_used_usd", 0.0),
            "prd_doc_url": req_data.get("prd_doc_url"),
            "created_at": req_data["created_at"],
            "updated_at": req_data["updated_at"],
        }
    }
    
    # 检查记录是否存在
    existing = await _find_record_by_req_id(
        client, 
        settings.feishu_bitable_app_token,
        settings.feishu_bitable_kanban_table_id,
        req_data["req_id"]
    )
    
    if existing:
        # 更新记录
        request = UpdateAppTableRecordRequest.builder() \
            .app_token(settings.feishu_bitable_app_token) \
            .table_id(settings.feishu_bitable_kanban_table_id) \
            .record_id(existing["record_id"]) \
            .request_body(
                AppTableRecord.builder()
                .fields(record["fields"])
                .build()
            ) \
            .build()
        
        response = client.bitable.v1.app_table_record.update(request)
    else:
        # 创建记录
        request = CreateAppTableRecordRequest.builder() \
            .app_token(settings.feishu_bitable_app_token) \
            .table_id(settings.feishu_bitable_kanban_table_id) \
            .request_body(
                AppTableRecord.builder()
                .fields(record["fields"])
                .build()
            ) \
            .build()
        
        response = client.bitable.v1.app_table_record.create(request)
    
    if not response.success():
        raise Exception(f"Failed to sync to bitable: {response.msg}")
```

2. **在 Workflow 中调用**

```python
# workflows/requirement.py
@workflow.run
async def run(self, req: RequirementInput) -> dict:
    # ... 现有逻辑 ...
    
    # P0 完成后同步
    await workflow.execute_activity(
        bitable_sync_requirement,
        {
            "req_id": req.req_id,
            "title": self.captured.summary,
            "project": "HealthAssit",
            "created_by": req.created_by,
            "lifecycle_state": "captured",
            "current_phase": "P0",
            "cost_used_usd": self.cost_used_usd,
            "created_at": workflow.now().isoformat(),
            "updated_at": workflow.now().isoformat(),
        },
        task_queue="bitable-sync",
        start_to_close_timeout=timedelta(seconds=30),
    )
    
    # P1 完成后同步
    await workflow.execute_activity(
        bitable_sync_requirement,
        {
            "req_id": req.req_id,
            "title": self.captured.summary,
            "project": "HealthAssit",
            "created_by": req.created_by,
            "lifecycle_state": "prd_approved",
            "current_phase": "P1",
            "cost_used_usd": self.cost_used_usd,
            "prd_doc_url": f"https://github.com/{req.repo_url}/blob/{req.branch}/docs/PRDs/{req.req_id}.md",
            "created_at": workflow.now().isoformat(),
            "updated_at": workflow.now().isoformat(),
        },
        task_queue="bitable-sync",
        start_to_close_timeout=timedelta(seconds=30),
    )
```

#### 阶段 2: Webhook 支持（Week 1 Day 3）

**目标**：用户在飞书表格中修改优先级、风险等级等字段时，自动同步到 Workflow

**实现步骤**：

1. **创建 Webhook 处理器**

```python
# apps/ingress/bitable_webhook.py
from fastapi import APIRouter, Request

router = APIRouter()

@router.post("/bitable/webhook")
async def handle_bitable_webhook(request: Request):
    """处理飞书表格 webhook"""
    event = await request.json()
    
    # 验证签名
    # ...
    
    # 解析事件
    req_id = event["record"]["fields"]["req_id"]
    field_name = event["changed_field"]
    old_value = event["old_value"]
    new_value = event["new_value"]
    actor = event["operator_user_id"]
    
    # 映射到 operator action
    action_map = {
        "priority": "change_priority",
        "risk_level": "change_risk_level",
        "cost_cap_usd": "extend_cost_cap",
        "is_paused": "pause" if new_value else "resume",
    }
    
    if field_name not in action_map:
        return {"ok": True}
    
    action_type = action_map[field_name]
    
    # 发送信号到 workflow
    client = await get_temporal_client()
    handle = client.get_workflow_handle(req_id)
    
    await handle.signal(action_type, {
        "old": old_value,
        "new": new_value,
        "actor": actor,
    })
    
    return {"ok": True}
```

2. **在 Workflow 中添加信号处理**

```python
@workflow.signal
def change_priority(self, data: dict) -> None:
    """修改优先级"""
    old_priority = data["old"]
    new_priority = data["new"]
    actor = data["actor"]
    
    log.info("priority changed from %s to %s by %s", 
            old_priority, new_priority, actor)
    
    # 记录到 workflow 状态
    self.priority = new_priority
    
    # TODO: 触发重新排队逻辑
```

### 快速验证方案

如果你想快速验证飞书表格功能，可以：

1. **手动创建飞书表格**
   - 按照 `docs/bitable_schema.md` 创建表格
   - 配置 22 个字段
   - 创建 5 个视图

2. **手动同步数据（临时方案）**
   - 创建一个简单的脚本，从 Temporal UI 或数据库读取数据
   - 批量写入飞书表格

3. **验证查询功能**
   - 在飞书表格中查看需求状态
   - 使用视图筛选和排序

### 下一步建议

1. **立即可做**：
   - 创建飞书表格（按 schema 文档）
   - 手动添加几条测试数据
   - 验证视图和筛选功能

2. **Week 1 Day 2**：
   - 实现 `activities/bitable/sync.py`
   - 在 workflow 中添加同步调用
   - 测试自动同步功能

3. **Week 1 Day 3**：
   - 实现 webhook 处理器
   - 配置飞书表格 webhook
   - 测试双向同步

---

## 总结

**问题 1（改写需求报错）**：
- 需要查看具体错误日志
- 可能是 workflow 状态问题
- 建议添加更详细的错误处理和用户提示

**问题 2（飞书表格管理）**：
- Schema 已设计完成
- 配置已添加
- 实现代码缺失（`activities/bitable/` 为空）
- 建议分阶段实现：先单向同步，再双向同步

需要我帮你实现飞书表格同步功能吗？
