# AIOperator Full v1.0 生产线架构与路由设计（完整交叉评审版）

> 本文是面向 **Claude 交叉评审** 的完整 handoff 稿，不依赖此前对话上下文。目标不是讨论一个最小原型，而是给出一版在弱资源起步、可持续扩容、具备生产控制面的完整 AI 软件生产线方案。
>
> **作者**：Codex
> **日期**：2026-04-19
> **适用阶段**：Phase 1 云端单节点起步，平滑扩展到 Phase 2 家庭 MBP 与 Phase 3 M5 MBA
> **文档目标**：锁定生产线的控制平面、执行平面、归档平面、审批平面与观测平面，后续允许通过加节点、改配置、补 adapter 扩展能力，而不推翻流程语义。

---

## 0. TL;DR

AIOperator 应被设计为一个 **生产级 AI 软件交付控制平面**，而不是“飞书机器人 + 多模型 + 一堆脚本”的组合。

完整方案保留以下外部能力：

- 飞书作为唯一人机入口
- 六阶段业务流水线：P0 需求捕获、P1 产品定义、P2 技术设计、P3 开发实现、P4 发布上线、P5 复盘沉淀
- 双模型协作：Codex 主实现，Claude 主测试/设计/评审
- 多 worker 节点扩容
- 三副本归档：Git + Feishu Docs + Bitable
- 人工审批卡点
- TDD 强制

但底层必须改为生产级结构：

- **唯一权威状态源**：Orchestrator DB，不再使用 `state.json + Bitable 双主写`
- **正式调度器**：Scheduler + Dispatcher + Lease Manager，不依赖 OpenClaw 原生 worker 路由
- **显式工单模型**：Requirement 生命周期状态与 Phase Execution 状态分离
- **TDD 门禁**：由测试契约、执行前置条件、Git/CI 校验共同保证，不依赖单一 CLI hook
- **风险分级模型链路**：保留双模型和第三方终审能力，但不是所有需求都默认走最长串行链路
- **真实容量模型**：Phase 1 云端采用 `heavy_slot=1`，拒绝虚假的并发承诺
- **可恢复执行**：通过 lease、heartbeat、retry、dead-letter queue 和 outbox 实现故障恢复

一句话总结：

> 这版方案不是缩成功能残缺的 MVP，而是把“完整生产线”真正需要的底座补齐，让六阶段、多 worker、双模型这些上层能力能稳定跑起来。

---

## 1. 目标与边界

### 1.1 业务范围

当前统一纳管两个项目：

- **HealthAssit**：React Native + Expo 移动 App
- **MaaS Service**：K8s + GitLab CI/CD 服务

### 1.2 系统目标

1. 用户全程只在飞书内发起、审批、查看、干预需求
2. 需求从捕获到复盘形成完整闭环
3. 所有关键流程可追踪、可重放、可恢复、可审计
4. 阶段 1 单节点能真实运行，不假设未来机器已经到位
5. 阶段 2/3 通过增量接入 worker 节点完成扩容，不推翻流程
6. 双模型协作用于提升质量，而不是制造默认吞吐瓶颈
7. 系统本身具备测试、观测、报警、容量控制与恢复机制

### 1.3 非目标

1. 不把 OpenClaw 当作整个任务调度与状态机内核
2. 不允许 Bitable 直接成为主状态源
3. 不要求所有任务都经过多轮模型互评
4. 不在 Phase 1 承诺大规模并发、iOS 构建、重型多任务扇出
5. 不让人工通过改底层字段直接破坏系统状态一致性

---

## 2. 原则

### 2.1 单一事实来源原则

流程状态只有一个权威来源：**Orchestrator 数据库**。

### 2.2 显式事件原则

审批、重试、暂停、恢复、返工、冲突处理、回滚全部表达为显式事件，而不是隐式覆盖字段。

### 2.3 无状态 worker 原则

worker 只持有：

- 当前 lease
- 当前 job payload
- 临时工作目录
- 局部日志

worker 不持有长期业务真相。

### 2.4 失败可恢复原则

任何外部系统调用、任务派发、同步动作都必须支持：

- 重试
- 幂等
- 超时
- 死信
- 人工接管

### 2.5 上层完整、底层保守原则

六阶段、双模型、多副本、审批卡点可以完整；底层容量、路由、同步、恢复必须保守而真实。

---

## 3. 顶层架构

### 3.1 分层图

```text
┌─────────────────────────────────────────────────────────────────┐
│ User Layer                                                      │
│  Feishu chat / cards / Bitable views / Feishu Docs             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ Ingress Layer                                                   │
│  ai-pm bot + OpenClaw gateway                                  │
│  - 接收飞书消息/卡片回调                                         │
│  - 转换为 Orchestrator commands/events                         │
│  - 回写卡片、通知、文档链接                                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ Control Plane                                                   │
│  Orchestrator                                                   │
│  - workflow engine                                              │
│  - scheduler                                                    │
│  - dispatcher                                                   │
│  - lease manager                                                │
│  - approval service                                             │
│  - artifact sync service                                        │
│  - audit/cost service                                           │
│  - lock manager                                                 │
└─────────────────────────────────────────────────────────────────┘
                              │
             ┌────────────────┼─────────────────┬────────────────┐
             ▼                ▼                 ▼                ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│ worker-lite      │ │ worker-llm       │ │ worker-build     │ │ worker-release   │
│ Feishu/Bitable   │ │ Claude/Codex     │ │ RN/K8s/tests     │ │ deploy/tag/rollbk│
└──────────────────┘ └──────────────────┘ └──────────────────┘ └──────────────────┘
             │                │                 │                │
             └────────────────┴─────────────────┴────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ Artifact Plane                                                  │
│  Git repos / Feishu Docs mirror / Bitable ops view             │
│  Build logs / test reports / release records / metrics         │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 组件职责

#### Ingress

- 接飞书消息
- 接卡片交互回调
- 做身份映射和权限校验
- 将外部动作转换为 Orchestrator API 调用
- 发送卡片、通知、链接

#### Orchestrator

- 维护 requirement 生命周期
- 维护 phase execution 工单
- 调度 worker
- 控制审批、熔断、重试、补偿、冲突与同步
- 记录审计与成本

#### Worker Runtime

- 领取 job lease
- 准备工作目录
- 拉取上下文和凭据
- 执行模型/构建/发布任务
- 续租 lease
- 上传结果和日志

#### Artifact Sync

- 把 Git 产物同步到 Feishu Docs
- 把状态索引同步到 Bitable
- 通过 outbox 重试，保证最终一致性

---

## 4. 关键架构决策

### 4.1 单一权威状态源

#### 放弃的设计

- `state.json` 权威副本
- Bitable 作为双向状态源
- webhook 回写直接改主状态

#### 采用的设计

- **生产推荐**：Postgres
- **Phase 1 可接受**：SQLite + WAL
- 对外所有状态推进只通过 Orchestrator API
- Bitable 只承接操作意图和状态镜像
- Docs 只承接文档镜像

#### 结论

Git 是交付物权威，DB 是流程权威，Bitable/Docs 不是流程权威。

### 4.2 正式调度器，而非补丁式 router

#### 放弃的设计

- 假设 OpenClaw 原生支持任务级 worker 标签路由
- 若不支持，只补 200 行 `router.py`

#### 采用的设计

将以下能力定义为 Orchestrator 正式内核：

- worker 注册
- heartbeat
- slot 计算
- job 路由
- lease 发放与回收
- circuit breaker
- retry 与 dead-letter
- affinity 与优先级

### 4.3 TDD 不依赖单点 hook

#### 放弃的设计

- 依赖 Codex CLI 的某个 pre-write hook 去硬拦截所有实现写入

#### 采用的设计

TDD 由五层共同保证：

1. P2 产出 `test_contract.json`
2. P3A 测试工单先成功
3. Orchestrator 不派发实现 job，直到测试存在且映射完整
4. Git/CI 校验“测试先于实现提交”
5. 合并前检查 AC -> tests -> diff 的映射矩阵

### 4.4 双模型分级策略

#### 放弃的设计

- 所有任务默认最长路径：Claude 测试 -> Codex 实现 -> Claude 评审 -> OpenAI 终审

#### 采用的设计

按 `risk_level` 决定链路长度：

- `low`：Claude 测试 + Codex 实现 + 自动验证
- `medium`：低风险链路 + Claude review
- `high`：中风险链路 + OpenAI 独立终审
- `release-critical`：高风险链路 + 人工 checklist + 发布前验证

---

## 5. 硬件拓扑与容量

### 5.1 节点规划

#### Phase 1：Tencent Cloud VM

- ai-pm ingress
- Orchestrator
- DB
- worker-lite
- worker-llm/build/release 降级承载

#### Phase 2：Home MBP 2014

- worker-llm
- worker-build
- worker-release
- K8s / RN / 实现类任务优先承载

#### Phase 3：M5 MBA

- worker-llm
- worker-build
- worker-release
- iOS / Xcode / Expo / urgent lane

### 5.2 容量模型

#### 云端 Phase 1

已知条件：

- RAM 约 3.6GB
- swap 已高
- OpenClaw/gateway 已占用显著内存

因此必须采用：

- `heavy_slot = 1`
- `light_slot = 6~8`

`heavy job` 包括：

- Claude Code
- Codex 实现
- RN build
- Docker build
- K8s 变更验证

禁止：

- `2 Claude + 1 Codex` 同时运行
- iOS build
- 多 heavy 并发

#### MBP Phase 2

- 默认 1~2 个 heavy 并发
- 以实测内存和热稳定性调参

#### M5 Phase 3

- `exec:ios-build = 1`
- `exec:xcode = 1`
- 可额外承担高优先级 LLM 任务

### 5.3 容量结论

Phase 1 不是假装多 worker，而是单节点运行完整语义；Phase 2/3 才逐渐释放吞吐。

---

## 6. Worker 能力模型

### 6.1 标签

| 标签 | 职责 |
|------|------|
| `exec:lite` | 飞书推送、Docs/Bitable 同步、轻量状态任务 |
| `exec:claude-code` | PRD、DESIGN、tests、review 生成 |
| `exec:codex` | 代码实现、bug fix、重构落地 |
| `exec:review:openai` | 第三方独立终审 |
| `exec:rn-build` | RN/Expo/Node 构建与测试 |
| `exec:k8s` | Docker/K8s/cluster 相关任务 |
| `exec:ios-build` | iOS/EAS/签名构建 |
| `exec:xcode` | simulator/真机调试 |
| `exec:release` | tag、部署、回滚、变更归档 |

### 6.2 Worker 注册字段

每个 worker 启动后向 Orchestrator 注册：

- `worker_id`
- `node_name`
- `host`
- `tailscale_ip`
- `labels`
- `slots`
- `status`
- `health_snapshot`
- `runtime_version`
- `tool_versions`
- `allowed_projects`
- `allowed_envs`
- `last_heartbeat`

### 6.3 Worker 状态

- `active`
- `draining`
- `paused`
- `planned`
- `unreachable`
- `circuit_open`

### 6.4 Worker 职责边界

worker 只负责执行，不负责：

- 推进全局 requirement 状态
- 决定是否能跳过审批
- 覆盖锁
- 决定重试策略

这些都归 Orchestrator 控制。

---

## 7. 调度、租约与熔断

### 7.1 Job 生成

每个 phase 会生成一个或多个 job，例如：

- `p1_prd_generate`
- `p2_design_generate`
- `p3_tests_generate`
- `p3_code_implement`
- `p3_review_claude`
- `p3_review_openai`
- `p4_release_staging`

### 7.2 Scheduler 选路因素

1. `required_labels`
2. `project affinity`
3. `risk_level`
4. `worker status`
5. `slot availability`
6. `health / circuit state`
7. `environment access`
8. `priority`
9. `resource locks`

### 7.3 Lease 生命周期

```text
queued
  -> leased
  -> running
  -> succeeded / failed / timed_out
```

细节：

1. Scheduler 选 worker
2. Dispatcher 发 lease
3. Worker ack
4. Worker 心跳续租
5. 超时未续租 -> lease 回收
6. Job 进入 retry 或 dead-letter

### 7.4 Retry 策略

#### 自动重试适用

- 网络短故障
- 外部 API 429/5xx
- worker 临时失联
- Docs/Bitable 同步失败

#### 不自动重试适用

- 设计冲突
- TDD 门禁未满足
- 权限不足
- 发布环境校验失败
- 模型评审明确指出高风险未解决

### 7.5 Dead-letter Queue

下列 job 进入死信队列：

- 超过最大重试次数
- 因环境或权限问题持续失败
- 存在人工必决阻塞

死信必须在飞书中可见。

### 7.6 熔断

worker 级熔断条件：

- `mem_high`
- `swap_high`
- `load_high`
- `disk_low`
- `heartbeat_lost`
- `tool_error_rate_high`

熔断后：

- 停止派发 heavy job
- 已执行 job 尽量收尾
- 若无法收尾，交由 lease timeout 触发恢复

---

## 8. 状态机

### 8.1 Requirement 生命周期状态

```text
captured
  -> requirement_confirmed
  -> prd_approved
  -> design_approved
  -> code_approved
  -> released
  -> closed
```

辅助状态：

- `paused`
- `blocked`
- `cancelled`

### 8.2 Phase Execution 状态

```text
queued
leased
running
awaiting_human
succeeded
failed
timed_out
cancelled
blocked
```

### 8.3 为什么拆两层

1. 需求主状态不被单次执行失败污染
2. 审批与执行可以分开重试
3. worker 掉线时只需恢复 phase execution
4. 阶段迁移不依赖漂移临时状态文件

### 8.4 状态推进事务要求

每次主状态推进必须在单事务内写入：

- requirement 更新
- phase execution 更新
- event log
- approval request
- sync outbox

---

## 9. 数据模型

### 9.1 关键表

- `requirements`
- `phase_executions`
- `jobs`
- `job_leases`
- `workers`
- `approvals`
- `operator_actions`
- `artifacts`
- `event_log`
- `sync_outbox`
- `file_locks`
- `module_locks`
- `environment_locks`
- `cost_records`

### 9.2 表设计建议

#### `requirements`

字段建议：

- `req_id`
- `project`
- `title`
- `priority`
- `risk_level`
- `lifecycle_state`
- `current_phase`
- `current_phase_execution_id`
- `owner_user_id`
- `created_at`
- `updated_at`

#### `phase_executions`

- `phase_execution_id`
- `req_id`
- `phase`
- `attempt`
- `status`
- `assigned_worker_id`
- `input_refs`
- `output_refs`
- `awaiting_human_reason`
- `started_at`
- `finished_at`

#### `jobs`

- `job_id`
- `phase_execution_id`
- `job_type`
- `required_labels`
- `priority`
- `payload_ref`
- `status`
- `retry_count`
- `max_retries`

#### `job_leases`

- `lease_id`
- `job_id`
- `worker_id`
- `leased_at`
- `expires_at`
- `last_renewed_at`
- `release_reason`

#### `approvals`

- `approval_id`
- `req_id`
- `phase_execution_id`
- `approval_type`
- `status`
- `requested_at`
- `resolved_at`
- `resolved_by`
- `resolution`

#### `operator_actions`

- `action_id`
- `req_id`
- `action_type`
- `payload`
- `requested_by`
- `requested_at`
- `processed_at`

### 9.3 事件模型

所有关键动作写入 `event_log`：

- `requirement.created`
- `requirement.confirmed`
- `phase.started`
- `phase.awaiting_human`
- `approval.granted`
- `job.leased`
- `job.retry_scheduled`
- `worker.circuit_opened`
- `artifact.synced`
- `release.deployed`
- `release.rollback_requested`

---

## 10. 六阶段流水线

## 10.1 P0 需求捕获

### 目标

将飞书自然语言转为结构化需求并获得用户确认。

### 输入

- 飞书消息
- 项目上下文

### 输出

- `.planning/{req_id}/requirement.json`
- requirement 记录
- 飞书确认卡片

### 流程

1. 用户在飞书发起需求
2. Ingress 调用 `capture_requirement`
3. Orchestrator 创建 requirement 和 P0 phase execution
4. `exec:claude-code` 或轻量结构化链路生成需求草稿
5. 发送确认卡片
6. 用户确认后推进到 `requirement_confirmed`

### 失败处理

- 连续结构化失败 -> 转人工补充
- 不做无限自修

## 10.2 P1 产品定义

### 目标

生成可审批、可测试的 PRD。

### 输出

- `PRD.md`
- `acceptance_criteria.json`
- PRD 审批卡

### 流程

1. Claude 读取 requirement 与项目上下文
2. 生成 `PRD.md`
3. 结构检查：
   - AC 可测试
   - 范围清晰
   - 依赖明确
4. 按风险级别决定是否触发 OpenAI gate review
5. 发送审批卡
6. 用户批准 -> `prd_approved`

### PRD 合格标准

- 每条 AC 必须有唯一编号
- AC 必须能映射到自动化测试或明确人工验证

## 10.3 P2 技术设计

### 目标

将 PRD 转成可实施的设计契约。

### 输出

- `DESIGN.md`
- `planned_modules.json`
- `test_contract.json`
- `risk_register.json`

### 流程

1. Claude 分析 PRD 与现有仓库
2. 生成设计文档
3. 提取模块边界、接口变更、数据变更
4. 生成 `test_contract.json`
5. 检查其他 in-flight requirement 的模块冲突
6. 发送审批卡
7. 用户批准 -> `design_approved`

### 关键修正

P2 不再只产出 `planned_files`，因为设计阶段无法可靠预知所有文件。改为：

- 模块范围
- 关键文件候选
- 测试契约
- 风险登记

## 10.4 P3 开发实现

### 目标

在 TDD 约束下完成测试、实现、验证、评审与人工批准。

### 子阶段

1. `P3A` 测试生成
2. `P3B` 代码实现
3. `P3C` 自动验证
4. `P3D` 模型评审
5. `P3E` 人工批准合并

### 详细流程

#### Step 1：Claude 生成测试

- 基于 `test_contract.json`
- 生成单元/集成/E2E 测试
- 允许测试失败，但必须可运行
- 测试落到 Git 分支

#### Step 2：TDD 门禁

只有满足以下条件才可派发 Codex 实现任务：

- 测试工单 `succeeded`
- 测试文件已提交
- AC -> tests 映射完整

#### Step 3：Codex 实现

- 读取 DESIGN + tests + 当前 diff
- 逐模块实现
- 按需多轮局部测试

#### Step 4：自动验证

- unit
- integration
- lint
- typecheck
- build verification

#### Step 5：模型评审

按 `risk_level`：

- `low`：可跳过模型评审
- `medium`：Claude review
- `high/release-critical`：Claude review + OpenAI independent review

#### Step 6：人工批准

卡片展示：

- diff 摘要
- 测试结果
- 关键风险
- 评审结论
- 回滚前提

操作：

- `批准合并`
- `要求返工`
- `放弃`

### TDD 强制总结

TDD 的核心不是“写文件时拦一下”，而是 **流程前置条件 + Git 证据 + CI 校验**。

## 10.5 P4 发布上线

### 目标

完成 staging/prod 发布、验证与发布记录归档。

### 输出

- `CHANGELOG.md` 片段
- release record
- environment url / build url
- rollback plan

### 发布 adapter

#### HealthAssit

- staging：`eas build --profile staging`
- prod：`eas build --profile production`
- iOS build 仅允许 M5

#### MaaS

- staging：K8s staging apply
- prod：K8s prod apply
- 发布前必须验证 config/schema compatibility

### 回滚

不再写“自动回滚到上一 tag”这种统一口号，改为类型化策略：

- Web/K8s：镜像/配置回滚
- Mobile：重新发布补丁版本或回退渠道包
- Schema change：必须具备前向/后向兼容或显式迁移计划

### 审批

- staging：单次审批
- prod：二次确认
- `release-critical`：附人工 checklist

## 10.6 P5 复盘沉淀

### 目标

将执行经验沉淀为工程知识，而不是自动生成空洞总结。

### 输出

- `postmortem.md`
- `anti_patterns.json`
- `exemplars/`
- `metrics` 更新

### 内容

- cycle time
- rework count
- 失败模式
- 新增反模式
- 可沉淀 exemplar

---

## 11. 风险分级与模型链路

### 11.1 风险级别定义

| 级别 | 场景 | 模型链路 |
|------|------|----------|
| `low` | UI 小改、文案、小 bug | Claude tests + Codex impl |
| `medium` | 普通功能、普通 API 变更 | low + Claude review |
| `high` | 登录、权限、支付、核心流程、数据迁移 | medium + OpenAI review |
| `release-critical` | 生产发布、集群变更、签名/iOS 上架 | high + human checklist |

### 11.2 风险来源

以下任意满足可上调风险：

- 改认证或权限
- 改数据模型或 schema
- 改发布链路
- 涉及生产环境
- 跨项目共享库
- 涉及财务、隐私、密钥、外部回调

---

## 12. 并发控制与锁

### 12.1 锁层级

1. `worker slot`
2. `module lock`
3. `file lock`
4. `environment lock`
5. `resource lock`

### 12.2 默认策略

- P2：先做模块冲突检测
- P3：进入编码前获取模块锁，必要时细化文件锁
- P4：发布前获取环境锁

### 12.3 示例

- `healthassit/auth`
- `maas/billing-api`
- `env:prod`
- `resource:ios-builder`

单纯文件锁不够，因为：

- 设计阶段无法穷举所有文件
- schema/config/shared-lib 的冲突往往不是单文件可表达

---

## 13. 人工审批与人工介入

### 13.1 审批不是改底层状态

飞书中所有操作都被转换为显式事件：

- `approve`
- `reject`
- `request_changes`
- `pause_requirement`
- `resume_requirement`
- `change_priority`
- `override_lock`

### 13.2 人工介入触发条件

任一满足即应抛人，不必等 3 轮失败：

1. 信息缺失导致 PRD 或设计无法收敛
2. 测试契约不可实施
3. 评审意见冲突
4. 资源不足持续阻塞
5. 发布前风险无法自动判定
6. 环境问题需要人工判断

### 13.3 卡片内容标准

人工介入卡片必须展示：

- 当前阶段
- 当前阻塞原因
- AI 已做尝试
- 推荐下一步
- 可点击动作

---

## 14. 三副本归档

### 14.1 职责

| 介质 | 职责 |
|------|------|
| Git | 代码、PRD、DESIGN、REVIEW、CHANGELOG 的权威存档 |
| Feishu Docs | 文档镜像、协作阅读 |
| Bitable | 运营索引、状态看板、审批结果、人工输入入口 |

### 14.2 同步机制

采用 outbox：

1. 主事务成功
2. 写入 `sync_outbox`
3. `artifact_sync_service` 重试同步到 Docs/Bitable
4. 失败告警，但不回滚主状态

### 14.3 幂等性

同步必须用业务 id 作为幂等键：

- `req_id`
- `phase_execution_id`
- `artifact_type`
- `artifact_version`

---

## 15. 密钥、凭据与权限模型

### 15.1 凭据种类

- Feishu app secret
- Bitable token
- Docs token
- OpenAI API key
- Claude/Anthropic key
- GitLab/GitHub token
- EAS token
- Apple 证书/凭据
- kubeconfig / cloud credentials

### 15.2 原则

1. 永不进 Git
2. 永不写入 artifact 正文
3. 不向无关 worker 发放
4. 以项目/环境/任务为维度最小授权

### 15.3 推荐方案

Phase 1：

- 环境变量
- 本地加密配置
- 权限最小化

Phase 2/3：

- 统一 secret provider
- 按 job 注入短期凭据或最小可用凭据

### 15.4 审计

记录：

- 哪类凭据被使用
- 哪个 worker 使用
- 用于哪个项目/环境

不记录明文。

---

## 16. 日志、观测与调试

### 16.1 观测面

- requirement timeline
- phase execution timeline
- queue backlog
- worker health
- lease timeout
- circuit events
- test/build/deploy logs
- token/cost usage

### 16.2 Trace 维度

每条日志至少带：

- `req_id`
- `phase_execution_id`
- `job_id`
- `worker_id`
- `project`
- `risk_level`

### 16.3 Debug 路径

任意线上问题都必须能从飞书卡片跳转到：

1. requirement
2. phase execution
3. job
4. worker log
5. Git diff
6. test/build/deploy report

没有这条链路，就不算生产可调试。

---

## 17. 系统测试策略

### 17.1 单元测试

- 状态机推进
- 选路逻辑
- lease 回收
- outbox retry
- lock manager

### 17.2 集成测试

- Orchestrator + DB
- Orchestrator + fake Feishu
- Orchestrator + fake Bitable
- Orchestrator + fake Docs
- Orchestrator + fake worker

### 17.3 E2E 回归

至少覆盖：

1. 正常路径：新需求 -> 发布完成
2. worker 掉线 -> lease timeout -> 重派
3. 审批拒绝 -> 返工 -> 再审批
4. Bitable 改优先级 -> 重新排队
5. 同模块冲突 -> 排队等待
6. 发布失败 -> 人工介入/回滚

### 17.4 仿真环境

必须具备：

- fake Feishu callback server
- fake Bitable API
- fake Docs API
- mock worker runtime
- sample project repos

---

## 18. 路由协议与配置建议

> 这里给的是 **Orchestrator 自有调度协议**，不是假设 OpenClaw 原生支持。

### 18.1 `workers.yaml`

```yaml
workers:
  - id: cloud-tencent
    host: 127.0.0.1
    tailscale_ip: 100.x.x.1
    labels:
      - exec:lite
      - exec:claude-code
      - exec:codex
      - exec:review:openai
      - exec:rn-build
      - exec:k8s
      - exec:release
    slots:
      heavy: 1
      light: 8
    env_access:
      - dev
      - staging
    status: active

  - id: home-mbp-2014
    host: <to_be_filled>
    tailscale_ip: 100.x.x.2
    labels:
      - exec:claude-code
      - exec:codex
      - exec:review:openai
      - exec:rn-build
      - exec:k8s
      - exec:release
    slots:
      heavy: 2
      light: 4
    env_access:
      - dev
      - staging
      - prod
    status: planned

  - id: mobile-m5-mba
    host: <to_be_filled>
    tailscale_ip: 100.x.x.3
    labels:
      - exec:claude-code
      - exec:codex
      - exec:rn-build
      - exec:ios-build
      - exec:xcode
      - exec:release
    slots:
      heavy: 3
      light: 4
      ios: 1
      xcode: 1
    env_access:
      - dev
      - staging
    status: planned
```

### 18.2 `routing.yaml`

```yaml
routing_rules:
  - name: ios_only_on_m5
    required_labels: [exec:ios-build]
    candidates: [mobile-m5-mba]
    strategy: strict
    on_unavailable: suspend_and_notify

  - name: xcode_only_on_m5
    required_labels: [exec:xcode]
    candidates: [mobile-m5-mba]
    strategy: strict
    on_unavailable: suspend_and_notify

  - name: k8s_prefer_cluster_ready_nodes
    required_labels: [exec:k8s]
    candidates: [home-mbp-2014, cloud-tencent]
    strategy: priority_with_health
    on_unavailable: queue

  - name: llm_prefer_local_then_cloud
    required_labels: [exec:claude-code, exec:codex]
    candidates: [mobile-m5-mba, home-mbp-2014, cloud-tencent]
    strategy: priority_with_slot_check
    on_unavailable: queue

  - name: lite_always_cloud
    required_labels: [exec:lite]
    candidates: [cloud-tencent]
    strategy: strict
    on_unavailable: retry

  - name: openai_review_anywhere
    required_labels: [exec:review:openai]
    candidates: [cloud-tencent, home-mbp-2014, mobile-m5-mba]
    strategy: round_robin_healthy
    on_unavailable: queue
```

### 18.3 调度补充规则

1. `required_labels` 是必须满足，不是任意一个命中
2. `env_access` 不满足则不能派发
3. `prod` 发布前必须同时满足：
   - 人工审批
   - 环境锁可获取
   - worker 有该环境权限

---

## 19. API 与外部交互契约

### 19.1 Ingress -> Orchestrator

建议暴露命令式接口：

- `POST /commands/capture-requirement`
- `POST /commands/approve`
- `POST /commands/reject`
- `POST /commands/request-changes`
- `POST /commands/pause-requirement`
- `POST /commands/resume-requirement`
- `POST /commands/change-priority`

### 19.2 Worker -> Orchestrator

- `POST /workers/register`
- `POST /workers/heartbeat`
- `POST /jobs/poll`
- `POST /jobs/{job_id}/ack`
- `POST /jobs/{job_id}/renew`
- `POST /jobs/{job_id}/complete`
- `POST /jobs/{job_id}/fail`

### 19.3 Sync Service

- `POST /sync/docs`
- `POST /sync/bitable`
- `POST /notifications/send`

---

## 20. 目录结构建议

```text
~/aioperator/
├── apps/
│   ├── ingress/
│   ├── orchestrator/
│   └── worker-runtime/
├── config/
│   ├── workers.yaml
│   ├── routing.yaml
│   ├── projects.yaml
│   ├── release.yaml
│   └── feishu.yaml
├── db/
│   ├── migrations/
│   └── seeds/
├── services/
│   ├── scheduler/
│   ├── dispatcher/
│   ├── lease_manager/
│   ├── approval_service/
│   ├── artifact_sync/
│   ├── lock_manager/
│   └── cost_tracker/
├── adapters/
│   ├── feishu/
│   ├── bitable/
│   ├── docs/
│   ├── git/
│   ├── openai/
│   ├── claude/
│   └── releases/
├── scripts/
│   ├── feishu_send.py
│   ├── feishu_docs.py
│   ├── bitable_sync.py
│   └── worker_healthcheck.py
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── fixtures/
├── learning/
│   ├── anti-patterns.json
│   └── exemplars/
├── .planning/
│   └── {req_id}/
└── docs/
    └── ARCHITECTURE_FOR_REVIEW.md
```

---

## 21. Phase 1 到 Phase 3 的落地顺序

### 21.1 第一优先级

先做这些，不然整条生产线没有底座：

1. Orchestrator DB schema
2. requirement / phase execution / jobs / approvals / outbox
3. ingress -> Orchestrator 命令链路
4. worker register / poll / ack / complete
5. Feishu 审批事件落库

### 21.2 第二优先级

1. P0/P1/P2 流程跑通
2. P3 的测试契约和 TDD 门禁
3. Git 产物归档
4. Docs/Bitable 异步同步

### 21.3 第三优先级

1. release adapters
2. lock manager
3. circuit breaker
4. 成本统计
5. 复盘沉淀

### 21.4 第四优先级

1. MBP 接入
2. M5 接入
3. iOS 专用路由
4. 高风险评审链路增强

---

## 22. 原草案关键假设的最终修订

| 原假设 | 最终结论 |
|--------|----------|
| OpenClaw 可直接承担 worker 标签路由 | 不作为架构前提；正式引入自有调度器 |
| `state.json` 可做权威状态 | 改为 DB 权威状态源 |
| Bitable 可双向主写 | 改为 operator action 入口，不直接改主状态 |
| Codex hook 可作为 TDD 强制主机制 | 不依赖；改为流程门禁 + Git/CI 门禁 |
| Phase 1 可跑 `2 Claude + 1 Codex` | 不成立；改为 `heavy_slot=1` |
| 文件锁足够表示冲突 | 不足；改为模块锁 + 文件锁 + 环境锁 |
| 所有需求都值得走双模型长链路 | 不成立；必须按风险分级 |
| 活跃需求可直接跟随 `state.json` 漂移 | 不成立；改为 DB + lease 恢复 |

---

## 23. 需要 Claude 重点复核的问题

以下是建议 Claude 在交叉评审时重点挑战的点：

1. `risk_level` 的分级标准是否还需要更细的项目化规则
2. `test_contract.json` 的最小字段集合是否足够支撑 TDD 门禁
3. `module lock` 的命名和粒度是否应按 bounded context 定义
4. `release adapter` 是否需要进一步拆成 staging/prod 不同能力集
5. Bitable 的人工输入是否还需要一层审批工作流防误操作
6. Phase 1 用 SQLite 是否足够，还是应直接上 Postgres
7. OpenAI 终审是否应仅限 `high/release-critical`
8. HealthAssit 的 iOS 流程是否还需要单独的签名/证书子状态机
9. MaaS 的 schema migration 是否应单列为 release gate
10. 复盘沉淀是否应拆成指标写入和文档生成两个独立任务

---

## 24. 最终结论

这版设计的立场很明确：

- 不缩水为简单 MVP
- 不继续堆叠未经验证的抽象
- 保留完整生产线的外部能力
- 把真正决定成败的底层控制面补齐

如果这版通过交叉评审，后续实现应按以下顺序推进：

1. 先落 Orchestrator 和数据模型
2. 再打通飞书入口和审批
3. 再打通 worker 调度与 lease
4. 再落 P0-P3 主链路
5. 再接入发布、复盘、扩容与高风险策略

只要坚持“DB 为流程权威、Orchestrator 为控制平面、worker 无状态、审批和同步事件化、TDD 以证据链保障”，这条生产线就能在弱资源起步，并在后续机器加入时自然扩容，而不会因为前提不稳而整体返工。
