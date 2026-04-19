# AIOperator v2.1 架构（Claude + Codex 二轮收敛稿）

> 本文是基于 Codex v1.0（[ARCHITECTURE_FOR_REVIEW.md](ARCHITECTURE_FOR_REVIEW.md)）的第二轮修订。继承 v1.0 的全部架构原则，但在**编排引擎选型、容量底座、风险流转、垂直切片落地**四件事上做了非平凡修正。
>
> **作者**：Claude（在 Codex v1.0 之上修订）
> **日期**：2026-04-19
> **版本**：v2.1
> **目的**：成为下一轮 Codex 评审的基线，并直接指导 Week 1 实施。
> **读者**：可能是 Codex（评审）、可能是 Claude Code（实施）、也可能是用户回顾决策。文档自包含，不依赖此前对话上下文。

---

## 0. TL;DR

AIOperator 是一个**自然语言驱动的 AI 软件交付控制平面**，覆盖六阶段（捕获→PRD→设计→开发→发布→复盘），驱动两个项目（HealthAssit RN、MaaS K8s），通过单一飞书机器人（ai-pm）作为人机入口，背后由 Claude + Codex 双模型按风险分级协作生产。

**与 v1.0 的核心差异（5 处）**：

1. **不自建 workflow engine，采用 Temporal**：v1.0 自建 scheduler/dispatcher/lease manager/lock manager 是 4-6 周纯框架工作；Temporal 原生覆盖 80% 控制面需求，工作量压到 1 周搭建 + 业务实现。
2. **DB 直接 Postgres**：v1.0 让 Phase 1 用 SQLite，但 Orchestrator 多组件并发写会撞 SQLite 单写锁；直接 Postgres docker 起，省一次迁移债。
3. **Worker pull/long-poll**：v1.0 文档自相矛盾（push vs poll），明确选 pull 模型——MBP 在家庭 NAT 后面，Temporal 原生 worker 也是 pull。
4. **垂直切片落地**：v1.0 §21 的"先建底座再做业务"会让用户 3 周看不到价值；改为 Week 1 跑通最小 P1 闭环，每周末有可演示成果。
5. **补上 v2.0 仍未收敛的 5 个实现内核**：确定性选路、环境亲和安全、锁归属、预算硬上限、审计模型。

**保留 v1.0 全部 9 项架构原则**（DB 权威、两层状态机、TDD 证据链、风险分级、heavy_slot=1、模块/文件/环境锁、operator_action 事件化、outbox 异步同步、无状态 worker）。

**补齐 v1.0 的 6 个缺口**（test_contract.json schema、release-critical 触发器、kubeconfig 节点亲和、单需求成本上限、iOS 凭据生命周期、OpenClaw 资产保留清单）。

**v2.1 额外修正 v2.0 的 5 个问题**：

1. workflow 不再直接读取在线 worker 信息做分支，改为 `resolve_execution_lane` activity
2. `k8s`/发布类队列按能力 + 环境拆分，避免错误节点抢活
3. 锁归属于 `phase_execution_id`，由 workflow 驱动续约，不再由 worker 持有
4. 成本上限改为“预留 + 对账”两阶段，不再只是事后发现超支
5. 审计从 `cost_records` 中剥离，恢复独立 `audit_log` / `credential_usage_log`

---

## 1. 目标与边界

### 1.1 业务范围（继承 v1.0）

- **HealthAssit**：React Native + Expo 移动 App
- **MaaS Service**：K8s + GitLab CI/CD 服务
- 后续可纳管更多项目，每个项目独立 Git 仓库 + 项目级配置

### 1.2 系统目标（继承 v1.0）

1. 用户全程在飞书内发起、审批、查看、干预需求
2. 需求从捕获到复盘形成完整闭环
3. 所有关键流程可追踪、可重放、可恢复、可审计
4. Phase 1 单节点真实可运行
5. Phase 2/3 通过加 worker 节点扩容，不推翻流程
6. 双模型协作按风险分级，不制造默认吞吐瓶颈
7. 系统本身具备测试、观测、报警、容量控制与恢复机制

### 1.3 非目标（继承 v1.0 + 新增 1 项）

1. 不把 OpenClaw 当作任务调度内核
2. 不让 Bitable 直接成为主状态源
3. 不要求所有任务都经过多轮模型互评
4. 不在 Phase 1 承诺大规模并发、iOS 构建、重型多任务扇出
5. 不让人工通过改底层字段直接破坏系统状态一致性
6. **【新】不自建可被成熟开源 workflow engine 替代的能力**

---

## 2. 原则（继承 v1.0）

- **2.1 单一事实来源**：运行时流程真相 = Temporal workflow history；运营与查询真相 = Postgres `aiop` 投影表；Bitable/Docs 不是主状态源
- **2.2 显式事件**：审批、重试、暂停、恢复、返工、冲突、回滚都是显式事件
- **2.3 无状态 worker**：worker 只持有 lease + payload + 临时工作目录 + 局部日志
- **2.4 失败可恢复**：任何外部调用都支持重试/幂等/超时/死信/人工接管
- **2.5 上层完整、底层保守**：六阶段+双模型+多副本+审批可以完整；底层容量/路由/同步必须保守真实
- **2.6【新】不重造轮子**：Temporal/Postgres/Tailscale 等成熟基础设施直接使用

---

## 3. 顶层架构

### 3.1 分层图

```text
┌─────────────────────────────────────────────────────────────────┐
│ User Layer                                                      │
│  飞书 chat / cards / Bitable views / Feishu Docs                │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ Ingress Layer (云端常驻)                                         │
│  ai-pm bot (OpenClaw 长连接) + Bitable webhook receiver         │
│  - 飞书消息/卡片回调 → Orchestrator command                     │
│  - Bitable 字段变更 → operator_action event                     │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ Control Plane                                                   │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ Temporal Server (workflow engine)                          │ │
│  │  - workflow execution, history, signals, queries           │ │
│  │  - task queue dispatch, worker polling, lease, heartbeat   │ │
│  │  - retry, timeout, dead-letter, versioning                 │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ Orchestrator App (薄业务层)                                 │ │
│  │  - workflow definitions (6 phases)                         │ │
│  │  - activity implementations (Claude/Codex/Git/Feishu/...)  │ │
│  │  - business projection: requirements / costs / locks       │ │
│  │  - operator action handlers                                │ │
│  └────────────────────────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ Postgres                                                   │ │
│  │  - Temporal namespace (Temporal 内部使用)                  │ │
│  │  - aiop schema (业务投影表)                                 │ │
│  └────────────────────────────────────────────────────────────┘ │
└──────────┬───────────────────────────────────────────┬──────────┘
           │ Temporal SDK long-poll (pull)             │
   ┌───────┴────────┬─────────────────┬────────────────┘
   ▼                ▼                 ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ worker-cloud │ │ worker-mbp   │ │ worker-m5    │
│ task queues: │ │ task queues: │ │ task queues: │
│  lite, llm*, │ │  llm, build, │ │  llm, build, │
│  build*, k8s*│ │  k8s         │ │  ios, xcode  │
│ (* Phase 1   │ │              │ │              │
│  降级承载)    │ │  Phase 2 接入 │ │  Phase 3 接入│
└──────────────┘ └──────────────┘ └──────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│ Artifact Plane                                                  │
│  Git repos (权威) / Feishu Docs (镜像) / Bitable (运营索引)      │
│  Temporal UI / build logs / test reports / Grafana metrics      │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 组件职责

| 组件 | 职责 | 实现方式 |
|------|------|---------|
| Ingress | 飞书消息→Orchestrator command；Bitable webhook→operator_action | OpenClaw 长连接（保留）+ FastAPI |
| Temporal Server | workflow 编排、worker 调度、lease、retry、history | 开源 docker-compose 部署 |
| Orchestrator App | workflow/activity 定义、业务投影、人机交互 | Python（temporalio SDK） |
| Postgres | Temporal 元数据 + 业务投影表 | 开源 docker |
| Worker | 领 activity task、执行、上报 | Python 进程，每节点一份 |
| Artifact Sync | Git 提交后异步推 Docs/Bitable | Temporal activity（outbox 语义） |

---

## 4. 关键架构决策

### 4.1 Temporal 作为 workflow runtime（v2 新增）

**放弃**：自建 scheduler / dispatcher / lease manager / retry / dead-letter / circuit breaker / workflow engine。

**采用**：Temporal（开源、Apache 2.0，可自托管），原生提供：

- **Workflow**：六阶段编排逻辑写成 workflow code，Temporal 保证 deterministic replay
- **Activity**：每个外部副作用（调 Claude API、跑 Codex CLI、git commit、发飞书卡）写成 activity，Temporal 管 retry/timeout/heartbeat
- **Task Queue**：替代 v1.0 的 worker 标签路由——每个 task queue 名字 = 一个 worker 能力/环境 lane（如 `llm-cloud`, `llm-local`, `build-rn-local`, `release-ios-m5`）
- **Signal**：用户在飞书点"批准" → Orchestrator 发 signal 给等待中的 workflow
- **Query**：飞书卡片要展示"当前进度"→ query workflow state，不用读 DB
- **Schedule**：P5 复盘、AC drift 检测等定时任务用 Temporal Schedule
- **Versioning**：workflow 升级时不影响历史 in-flight workflow

**收益**：
- 工作量从 4-6 周（自建）压到 ~1 周（部署 + 学习 SDK）
- 内置 Web UI 用于 debug / replay / 强制 reset
- 故障恢复语义已被生产验证

**约束**：
- Workflow code 必须 deterministic（不能直接调系统时间、随机数、IO，全部走 activity）
- 学习曲线：team 需要理解 workflow vs activity 的边界
- Temporal Server 自身需要 Postgres，运维成本 +1 个组件

### 4.1.1 确定性选路边界（v2.1 补）

v2.0 的表述里，workflow code 直接根据“当前有哪些 worker 在线”选择 task queue，这不成立：

- workflow 不能直接依赖瞬时外部状态做分支
- Temporal Visibility API 也不是业务级在线 worker registry

因此 v2.1 明确：

1. **workflow 内只消费“已记录到 history 的路由决策结果”**
2. 实时选路通过一个短 activity `resolve_execution_lane(...)` 完成
3. `resolve_execution_lane` 读取 Postgres 中的 `worker_capabilities` 投影表和静态配置
4. 该 activity 返回：
   - `task_queue`
   - `lane_reason`
   - `selected_worker_class`
   - `required_env`
5. 返回值被记录进 workflow history，后续 replay 保持确定性

也就是说：

- **动态发现** 在 activity 里
- **控制流分支** 在 workflow 里
- **分支输入** 必须来自已记录的 activity result

### 4.2 单一权威状态源（继承 v1.0，细化）

**Temporal 自带 workflow execution history** 是流程状态的最终权威。
**业务投影表**（在同一 Postgres 的 `aiop` schema）用于支持：
- Bitable 双向同步（Bitable 不查 Temporal）
- 跨 workflow 查询（如"列出当前所有 in-flight 需求"）
- 报表与成本统计

投影表通过 Temporal activity 在状态推进时写入，**不允许业务代码绕过 workflow 直接改投影表**。

Git 仍是交付物权威；Bitable/Docs 是镜像。

### 4.3 TDD 证据链（继承 v1.0，细化）

由 5 层共同保证，这 5 层都直接映射到 Temporal workflow 控制流，**不依赖任何 CLI hook**：

1. **P2 activity 产出 `test_contract.json`**（schema 见 §17.1），落 Git
2. **P3A activity = "Claude 写测试"**，必须 succeeded 才能继续
3. **Workflow 控制流**：P3B（Codex 实现）只在 P3A activity 返回 success 后才被 schedule
4. **Pre-merge activity**：调 git diff，断言"测试文件先于实现文件出现在 commit history 中"
5. **CI 校验**：合并前 GitLab/GitHub Actions 跑 contract validator，确认 AC→test→implementation 映射矩阵完整

任一层失败 → workflow 进入 `awaiting_human` signal 等待。

### 4.4 风险分级模型链路 + 显式分级流转（继承 v1.0，新增 G1 缺口修复）

**4 级链路**（继承 v1.0 §11）：

| 级别 | 模型链路 | 单需求估算成本 |
|------|---------|--------------|
| `low` | Claude tests + Codex impl + 自动验证 + **轻量 Claude diff review** | $0.5-2 |
| `medium` | low + Claude 完整 review | $2-5 |
| `high` | medium + OpenAI 独立终审 | $5-12 |
| `release-critical` | high + 人工 checklist + 发布前验证 | $8-20 |

**v2 修正**：v1.0 让 low 完全跳过模型评审，但自动验证只能抓测试覆盖到的逻辑。**low 也保留一个轻量 Claude diff review activity（约 $0.05、30 秒），结构性检查"测试是否覆盖 AC"**——这不是质量打分，是契约检查。

**风险级别的写入流程**（v1.0 缺）：

1. **P0 阶段**：Claude 在生成需求草稿时给出建议级别 + 理由（基于 §4.5 触发规则）
2. **P0 确认卡片**：用户必须在下拉选项里**显式选定**级别，不能跳过
3. **运行中提级**：通过 `change_risk_level` operator_action，无门槛
4. **运行中降级**：通过 `change_risk_level` operator_action，需在飞书卡片二次确认（防误操作）
5. **当前级别始终在 Bitable 主视图可见**

### 4.5 release-critical 触发器（v1.0 缺，v2 补）

满足任一即升 `release-critical`：

- 目标环境为 prod
- 涉及数据库 schema 变更（含 alembic / prisma migrate / k8s CRD）
- 涉及外部支付、签名、上架（如 EAS submit、App Store、kubectl apply 到 prod 集群）
- 涉及密钥轮换或访问控制策略变更
- 已发生过一次回滚的需求重新发布

**强制约束**：release-critical 的 P4 阶段必须人工 checklist 全部勾选才能 dispatch 部署 activity。

### 4.6 单需求成本硬上限（v1.0 缺，v2 补）

每个 requirement 在创建时按 priority 设定 `cost_cap_usd`：

| Priority | 默认上限 | 触达后行为 |
|---------|---------|-----------|
| P0 | $30 | 暂停 workflow，飞书卡片请求"加预算 / 终止" |
| P1 | $15 | 同上 |
| P2 | $5 | 同上 |

v2.1 将“硬上限”从事后检测改为 **预留 + 对账** 两阶段：

1. 每个高成本 activity 派发前先执行 `reserve_budget`
2. `reserve_budget` 基于 activity 类型、模型、上下文大小给出 `estimated_usd`
3. 若 `used + reserved + estimated > cost_cap_usd`，则 **不派发 activity**，workflow 进入 `awaiting_human`
4. activity 完成后执行 `reconcile_budget`
5. `reconcile_budget` 用实际 token/cost 回写 `cost_records`，并释放多余预留

这样预算控制点在 **activity 开始前**，而不是“2 小时任务跑完后才发现超支”。

---

## 5. 硬件拓扑与容量

继承 v1.0 §5，无变化。三阶段：

| 阶段 | 节点 | task queues | heavy/light slot |
|------|------|------------|-----------------|
| Phase 1（当前）| `cloud-tencent` 3.6GB | `lite`, `llm-cloud`, `build-rn-cloud`, `k8s-staging-cloud` | heavy=1, light=8 |
| Phase 2（≥2026-04-26）| 加 `home-mbp-2014` 8GB | `llm-local`, `build-rn-local`, `k8s-staging-mbp`, `k8s-prod-mbp` | heavy=2, light=4 |
| Phase 3（M5 稳定后）| 加 `mobile-m5-mba` 32GB | `llm-fast`, `build-rn-local`, `release-ios-m5`, `xcode-m5` | heavy=3, light=4, ios=1 |

Phase 1 的 `cloud-tencent` 同时挂多个 task queue，但 `llm-cloud` 实际并发 = 1（Worker 配置 `max_concurrent_activity_tasks=1`），物理保证。

---

## 6. Worker 与 Task Queue 模型（替代 v1.0 §6 §7 §18）

### 6.1 Task Queue 命名

| Task Queue | 含义 | 哪些节点订阅 |
|-----------|------|------------|
| `lite` | 飞书 I/O、Bitable 同步、状态投影写入 | cloud only |
| `llm-cloud` | 云端 LLM 任务（Phase 1 兜底）| cloud |
| `llm-local` | 本地 LLM 任务（Phase 2/3 主力）| mbp, m5 |
| `llm-fast` | 高优 LLM（M5 加速）| m5 |
| `build-rn-cloud` / `build-rn-local` | RN/Node 构建 | cloud(P1)/mbp/m5 |
| `k8s-staging-cloud` | staging K8s 任务 | cloud |
| `k8s-staging-mbp` | staging K8s 任务 | mbp |
| `k8s-prod-mbp` | prod K8s 任务 | mbp only |
| `release-ios-m5` | iOS 构建/EAS submit | m5 only |
| `xcode-m5` | Xcode simulator/真机 | m5 only |
| `review-openai` | OpenAI 终审 | 任意（仅需出网） |

### 6.2 Workflow 怎么选 task queue

**风险/优先级 → task queue 映射** 不再直接写死在 workflow 对“在线节点”的判断中。v2.1 改为：

1. workflow 读取静态项目配置
2. workflow 调用 `resolve_execution_lane` activity
3. activity 读取 `worker_capabilities` 投影表和项目/环境配置
4. activity 返回确定的 `task_queue`
5. workflow 再用这个结果调度后续 activity

```python
# 伪代码
lane = await workflow.execute_activity(
    resolve_execution_lane,
    LaneRequest(kind="llm", risk=risk, priority=priority, target_env=env),
)

await workflow.execute_activity(
    claude_generate_design,
    ...,
    task_queue=lane.task_queue,
)
```

`resolve_execution_lane` 的决策规则是：

- 先满足环境/凭据亲和
- 再满足能力匹配
- 再按优先级选择更快节点
- 都不可用时返回 `blocked_reason`，由 workflow 进入等待人工或排队

**不允许**：

- 直接在 workflow 中调用 Visibility API
- 用共享 `k8s` 队列让错误节点先抢到再在 activity 内自检失败

### 6.3 Worker 注册

Temporal 的 poller 存活信息只够 Temporal 自己分发任务，不够业务层做安全选路和审计。

因此 v2.1 改为：

- **Temporal 层**：worker 继续 long-poll task queue
- **业务层**：worker 启动时额外执行 `register_worker_capability`，周期性 `heartbeat_worker_capability`

`worker_capabilities` 投影表至少包含：

- `worker_id`
- `node_class` (`cloud` / `mbp` / `m5`)
- `task_queue`
- `allowed_envs`
- `labels`
- `status`
- `last_heartbeat_at`
- `current_heavy_slots`
- `max_heavy_slots`

每个节点的 worker 进程（`worker-runtime`）启动配置：

```yaml
# worker-cloud.yaml 示例
node_id: cloud-tencent
task_queues:
  - name: lite
    max_concurrent_activities: 8
  - name: llm-cloud
    max_concurrent_activities: 1   # heavy_slot 物理保证
  - name: build-rn-cloud
    max_concurrent_activities: 1
  - name: k8s-staging-cloud
    max_concurrent_activities: 1
circuit_breaker:
  mem_percent: 85
  swap_percent: 85
```

熔断由 worker 自身实现：定期检查系统资源，超阈值时：

1. 停止 long-poll
2. 将 `worker_capabilities.status` 置为 `circuit_open`
3. 让 `resolve_execution_lane` 不再选择该 lane

---

## 7. Workflow 编排（替代 v1.0 §7 §10）

### 7.1 顶层 workflow：`RequirementWorkflow`

每个需求 = 一个长生命周期 workflow，跨越六阶段。

```python
# 伪代码骨架
@workflow.defn
class RequirementWorkflow:
    @workflow.run
    async def run(self, req: RequirementInput):
        # P0
        await self._capture(req)
        await workflow.wait_condition(lambda: self.confirmed)

        # P1
        prd = await self._generate_prd()
        await workflow.wait_condition(lambda: self.prd_approved)

        # P2
        design = await self._generate_design(prd)
        await workflow.wait_condition(lambda: self.design_approved)

        # P3
        await self._tdd_loop(design)
        await workflow.wait_condition(lambda: self.code_approved)

        # P4
        await self._release()

        # P5 (signal-driven, 24h 后由 schedule 触发)

    @workflow.signal
    def approve_prd(self, by: str):
        self.prd_approved = True

    @workflow.signal
    def change_risk_level(self, new_level: str, by: str):
        self.risk_level = new_level

    @workflow.query
    def status(self) -> dict:
        return {"phase": self.current_phase, "risk": self.risk_level, ...}
```

### 7.2 P3 子 workflow：`TddImplementWorkflow`

P3 拆成 child workflow，独立重试（v1.0 §8.3 的"两层状态机"在 Temporal 里天然成立——父 workflow 状态 = requirement，child workflow 状态 = phase execution）。

```python
@workflow.defn
class TddImplementWorkflow:
    async def run(self, design: DesignSpec, risk: str):
        # P3A: tests
        lane = await workflow.execute_activity(
            resolve_execution_lane,
            LaneRequest(kind="llm", risk=risk, phase="p3_tests"),
        )
        test_result = await workflow.execute_activity(
            generate_tests, design,
            task_queue=lane.task_queue,
            start_to_close_timeout=timedelta(minutes=20),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )
        self._verify_test_contract(test_result)  # TDD 门禁第 3 层

        # P3B: implementation
        impl_lane = await workflow.execute_activity(
            resolve_execution_lane,
            LaneRequest(kind="codex", risk=risk, phase="p3_impl"),
        )
        impl_result = await workflow.execute_activity(
            codex_implement, design, test_result,
            task_queue=impl_lane.task_queue,
            start_to_close_timeout=timedelta(hours=2),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        # P3C: auto verify
        await workflow.execute_activity(run_ci_locally, ...)

        # P3D: review (按风险级别)
        if risk != "low":
            await workflow.execute_activity(claude_review, ...)
        else:
            await workflow.execute_activity(claude_lite_review, ...)  # v2 修正
        if risk in ("high", "release-critical"):
            await workflow.execute_activity(openai_review, task_queue="review-openai")

        # P3E: human approval signal (在父 workflow)
```

### 7.3 Activity 清单

每个 activity = 一个可重试的副作用单元：

| Activity | Task Queue | 典型超时 | Heartbeat |
|---------|-----------|---------|-----------|
| `resolve_execution_lane` | `lite` | 10 sec | - |
| `reserve_budget` | `lite` | 5 sec | - |
| `reconcile_budget` | `lite` | 5 sec | - |
| `claude_capture_requirement` | `llm-cloud`/`llm-local` | 5 min | - |
| `claude_generate_prd` | llm-* | 20 min | 3 min |
| `claude_generate_design` | llm-* | 30 min | 3 min |
| `claude_generate_tests` | llm-* | 20 min | 3 min |
| `codex_implement` | llm-* | 2 hr | 5 min |
| `claude_review` | llm-* | 15 min | 3 min |
| `claude_lite_review` | llm-* | 2 min | - |
| `openai_review` | llm-* | 10 min | - |
| `git_commit` | `lite` | 1 min | - |
| `run_ci_locally` | `build-rn-*` | 30 min | 5 min |
| `eas_build` | `release-ios-m5` | 1 hr | 5 min |
| `k8s_apply` | `k8s-*` | 10 min | 1 min |
| `feishu_send_card` | `lite` | 30 sec | - |
| `bitable_upsert` | `lite` | 30 sec | - |
| `feishu_doc_sync` | `lite` | 1 min | - |

**v2.2 修正（2026-04-19）**：Codex CLI 在 M5 可用（codex-cli 0.121.0），M5 节点订阅 `llm-fast` 队列处理 `codex_implement`。云端无 Codex CLI，仅处理 Claude activities。

### 7.3.1 预算守卫插入点（v2.1 补）

所有高成本 activity 前都必须先跑：

1. `reserve_budget`
2. 若允许则执行真实 activity
3. activity 完成后 `reconcile_budget`

典型包围点：

- `claude_generate_prd`
- `claude_generate_design`
- `claude_generate_tests`
- `codex_implement`
- `claude_review`
- `openai_review`

### 7.4 Outbox 用 Temporal 怎么做

v1.0 §14.2 提到 outbox。在 Temporal 里：
- 主 workflow 状态推进 = workflow history（强一致）
- 同步 Bitable/Docs = 异步 activity（自动 retry，失败进 dead-letter workflow 通知人）
- **不需要手写 outbox 表** —— Temporal history + activity retry 等价于 outbox 语义

---

## 8. 状态机（继承 v1.0 §8，简化映射）

### 8.1 Requirement 生命周期 = `RequirementWorkflow` 的状态字段

```text
captured → requirement_confirmed → prd_approved → design_approved
  → code_approved → released → closed
辅助：paused / blocked / cancelled
```

存储在 workflow state（query 可读）+ Postgres `requirements` 投影表。

### 8.2 Phase Execution = child workflow + activity

每次 phase 重试 = 新一次 child workflow 实例（Temporal 自带 attempt 编号）。

### 8.3 状态推进事务

Temporal 保证 workflow state transition + signal handling 的原子性。**业务投影表写入是 activity**，最终一致即可（Bitable 看到的状态可能比 workflow 真相滞后秒级，可接受）。

---

## 9. 数据模型（精简 v1.0 §9）

由于 Temporal 接管了大部分流程状态，业务投影表只需：

### 9.1 `aiop` schema 的表

| 表 | 职责 | 关键字段 |
|----|------|---------|
| `requirements` | Bitable / 跨需求查询的投影 | `req_id` (= workflow_id), `project`, `title`, `risk_level`, `priority`, `lifecycle_state`, `current_phase`, `cost_used_usd`, `cost_cap_usd` |
| `operator_actions` | 飞书/Bitable 输入的事件日志 | `action_id`, `req_id`, `action_type`, `payload`, `requested_by`, `processed_at` |
| `cost_records` | LLM 调用成本与预算对账 | `record_id`, `req_id`, `phase`, `model`, `estimated_usd`, `reserved_usd`, `actual_usd`, `input_tokens`, `output_tokens`, `at` |
| `worker_capabilities` | 业务级 worker 注册表 | `worker_id`, `node_class`, `task_queue`, `allowed_envs`, `status`, `last_heartbeat_at`, `max_heavy_slots` |
| `module_locks` | 模块级互斥 | `lock_key`, `held_by_phase_execution_id`, `lease_owner_workflow_id`, `lease_expires_at`, `state` |
| `file_locks` | 文件级互斥（必要时） | `path`, `held_by_phase_execution_id`, `lease_owner_workflow_id`, `lease_expires_at`, `state` |
| `environment_locks` | 环境级互斥（prod 部署）| `env_key`, `held_by_phase_execution_id`, `lease_owner_workflow_id`, `lease_expires_at`, `state` |
| `audit_log` | 审批/重试/同步/状态推进审计 | `event_id`, `req_id`, `phase`, `event_type`, `actor`, `payload`, `at` |
| `credential_usage_log` | 凭据类别使用审计 | `usage_id`, `req_id`, `worker_id`, `credential_type`, `target_env`, `phase`, `at` |
| `artifacts_index` | 三副本归档地址索引 | `req_id`, `phase`, `kind` (prd/design/code/review/release), `git_url`, `feishu_doc_url`, `bitable_row_id` |

**v1.0 的下列表不再需要**（Temporal 自带）：`jobs`, `job_leases`。

**仍建议保留概念性投影**：

- `phase_executions`：若后续 Bitable/报表要直接展示 phase attempt，建议补回轻量投影表
- `audit_log`：不能完全依赖 Temporal history 替代业务审计

### 9.2 索引与约束

- `requirements.req_id` 主键，与 Temporal `workflow_id` 一致
- `module_locks.lock_key` 唯一约束 → 防止双锁
- `cost_records` 按 `req_id, at` 索引 → 快速求和
- `worker_capabilities (task_queue, status, last_heartbeat_at)` 复合索引 → 供 `resolve_execution_lane` 查询
- `audit_log (req_id, at)` 索引 → 支持审计回放
- 所有表加 `created_at, updated_at, version`（乐观锁）

---

## 10. 六阶段流水线（继承 v1.0 §10，标注 v2 修正）

### 10.1 P0 需求捕获

继承 v1.0。**v2 新增**：P0 确认卡片必须包含**风险级别下拉**（Claude 给出建议 + 理由），用户必须显式选定。

### 10.2 P1 产品定义

继承 v1.0。**v2 修正**：
- PRD 不做 4 维度评分（v1.0 已简化，v2 保持）
- 结构性检查：每条 AC 唯一编号 + 可映射到自动化测试或人工验证步骤
- 输出 `acceptance_criteria.json`（与 PRD.md 同时落 Git）

### 10.3 P2 技术设计

继承 v1.0。**v2 新增**：`test_contract.json` 必须输出，schema 见 §17.1。

### 10.4 P3 开发实现（双模型 TDD）

继承 v1.0 五子阶段。**v2 修正**：
- P3D 模型评审：低风险也跑 `claude_lite_review`（不是 v1.0 的"完全跳过"）
- 实现 → 测试映射矩阵在 P3E 人工卡片上必须可视化

### 10.5 P4 发布上线

继承 v1.0。**v2 新增**：
- release-critical 触发器列表（§4.5）
- 节点亲和：MaaS prod 部署只能在持有 prod kubeconfig 的节点（默认 = MBP；MBP 离线时阻塞 + 飞书告警，**不允许把 prod kubeconfig 复制到云端**）

### 10.6 P5 复盘沉淀

继承 v1.0。改为 Temporal Schedule 在 `released` 后 24 小时触发。

---

## 11. 风险分级与模型链路

完整定义见 §4.4、§4.5。补充：

### 11.1 风险来源信号（自动检测，给 Claude 做 P0 建议级别）

- PRD/需求文本含关键词：`认证 / 鉴权 / 支付 / schema / migration / 上架 / 发布到生产 / 密钥`
- 影响目录命中黑名单（项目级配置）：如 `healthassit/src/auth/**`, `maas/billing/**`
- 历史相似需求曾发生回滚

只用于**建议**，最终级别由用户在 P0 卡片选定。

---

## 12. 并发控制与锁（继承 v1.0 §12）

- **Worker slot**：Temporal `max_concurrent_activities`
- **Module lock**：进入 P3 前 acquire `module_locks` 表行级锁；冲突则 workflow `wait_condition` 等待 `lock_released` signal
- **File lock**：模块锁不够细时手动追加
- **Environment lock**：P4 进入前 acquire；prod 部署期间其他需求 prod 阻塞

v2.1 明确：**锁归属于 `phase_execution_id`，不归属于某个 worker 进程**。

原因：

- worker 只是瞬时执行者
- P3/P4 经常会进入等待人工审批
- 如果锁绑在 worker 上，activity 一结束锁就可能被错误释放

因此采用：

1. workflow/child workflow 通过 `acquire_lock` activity 获取锁
2. 锁表记录 `held_by_phase_execution_id`
3. workflow 在等待审批或长阶段内用定时器驱动 `renew_lock` activity
4. merge / reject / cancel / timeout 时由 workflow 显式 `release_lock`
5. 只有当 `lease_expires_at` 超时且 workflow 已不可恢复时，后台清理任务才释放陈旧锁

补充约定：

- P3 模块锁默认持有到 `code_approved` 或需求放弃
- P4 环境锁持有到部署完成或回滚结束

---

## 13. 人工审批与人工介入（继承 v1.0 §13）

所有飞书操作 → `operator_actions` 表 → Orchestrator 翻译为 workflow signal：

| operator_action | workflow signal |
|----------------|----------------|
| `approve` | `approve_<phase>` |
| `reject` | `reject_<phase>` |
| `request_changes` | `request_changes_<phase>` |
| `change_risk_level` | `change_risk_level` |
| `change_priority` | `change_priority` |
| `pause_requirement` | `pause` |
| `resume_requirement` | `resume` |
| `extend_cost_cap` | `extend_cost_cap` |
| `override_lock` | `override_lock`（管理员） |

人工介入卡片标准（继承 v1.0 §13.3）：当前阶段、阻塞原因、AI 已尝试、推荐下一步、可点击动作。

---

## 14. 三副本归档（继承 v1.0 §14）

- Git：权威
- Feishu Docs：镜像，文档型协作
- Bitable：运营索引、看板、人工输入入口

同步通过 Temporal activity（`feishu_doc_sync`, `bitable_upsert`），自动 retry，失败进 dead-letter workflow 触发飞书告警。幂等键 = `(req_id, phase, kind)`。

---

## 15. 密钥与节点亲和（v1.0 §15 + 新增 G3 缺口）

### 15.1 凭据清单（继承 v1.0）

Feishu app secret / Bitable token / Docs token / OpenAI key / Anthropic key / GitLab token / EAS token / Apple 证书 / kubeconfig

### 15.2 节点亲和矩阵（v2 新增）

| 凭据 | 持有节点 | 影响 |
|------|---------|------|
| Feishu / Bitable / Docs token | cloud | ingress 必须在云端 |
| Anthropic / OpenAI key | 所有节点 | 任意节点跑 LLM activity |
| GitLab/GitHub token | 所有节点 | 任意节点 git push |
| MaaS staging kubeconfig | cloud + mbp | staging 部署可任选 |
| **MaaS prod kubeconfig** | **mbp only** | prod 部署 MBP 离线时阻塞 |
| EAS token + Apple 证书 | **m5 only** | iOS 构建/上架 M5 离线时阻塞 |

prod kubeconfig 不复制到云端，是有意的安全决策（云端共享主机风险更高）。MBP 长期离线 → 通过 OOB 流程把 kubeconfig 临时部署到指定 backup 节点（人工授权）。

### 15.3 注入方式

Phase 1：环境变量 + 本地加密配置文件（`age` / `sops`）
Phase 2/3：每节点 worker 启动时读本地凭据，**Temporal payload 不传明文**

### 15.4 审计

v2.1 改为独立审计：

- `cost_records`：只记录预算与实际成本
- `audit_log`：记录审批、重试、signal、同步失败、状态推进
- `credential_usage_log`：记录哪个 worker 在哪个 req_id / phase / env 使用了哪类凭据

三者都不记录明文。

### 15.5 iOS 凭据生命周期（v2.1 补最小闭环）

v2.0 只定义了 “M5 only” 亲和，v2.1 补齐最小可执行策略：

1. Apple 证书、EAS token、Apple Account 会话都归类为 `ios_release_credentials`
2. 每次 `release-ios-m5` activity 前先执行 `validate_ios_credentials`
3. `validate_ios_credentials` 检查：
   - 证书未过期
   - token 未失效
   - 本次发布所需 profile/identifier 可用
4. 校验失败则 workflow 进入 `awaiting_human`
5. 不在 v2.1 引入独立 iOS 凭据子状态机，但把它明确列为后续可拆的 release support workflow

---

## 16. 观测、调试与告警

| 维度 | 工具 |
|------|------|
| Workflow 执行链路 | Temporal Web UI（自带）|
| 重放 / 强制 reset | Temporal CLI |
| 业务报表（吞吐、cost、cycle time） | Postgres + Grafana 仪表盘 |
| 告警 | Temporal worker 健康 → Prometheus → Alertmanager → 飞书告警机器人 |
| Trace 维度 | `req_id`, `workflow_id`, `phase`, `attempt`, `worker_id`, `risk_level` |
| Debug 路径 | 飞书卡片含 `req_id` → Temporal UI 链接 → workflow 执行历史 → 具体 activity 日志 |

---

## 17. 关键契约 schema（v1.0 缺，v2 补）

### 17.1 `test_contract.json` (v2 新增)

```json
{
  "version": "1.0",
  "req_id": "REQ-20260419-001",
  "ac_to_tests": [
    {
      "ac_id": "AC-001",
      "ac_text": "用户使用错误密码登录时显示错误提示",
      "test_strategy": "unit",
      "framework": "jest",
      "test_files": ["src/screens/__tests__/Login.error.test.tsx"],
      "verification": "automated"
    },
    {
      "ac_id": "AC-005",
      "ac_text": "首次登录引导用户完成画像",
      "test_strategy": "e2e",
      "framework": "detox",
      "test_files": ["e2e/onboarding.e2e.ts"],
      "verification": "automated"
    },
    {
      "ac_id": "AC-009",
      "ac_text": "iOS 上的生物识别符合 Apple HIG",
      "test_strategy": "manual",
      "checklist_path": "docs/manual_tests/biometrics.md",
      "verification": "manual_qa"
    }
  ],
  "coverage_targets": {
    "unit": 0.8,
    "integration": 0.6
  },
  "risks_to_validate": [
    "并发登录请求时的状态一致性",
    "网络断开时的退化体验"
  ]
}
```

**TDD 门禁第 4 层**校验：`ac_to_tests` 中所有 `verification=automated` 的条目对应的 `test_files` 必须在 P3A activity 完成后存在于 Git 工作树中。

### 17.2 `risk_register.json`

```json
{
  "version": "1.0",
  "req_id": "REQ-20260419-001",
  "risk_level": "medium",
  "level_history": [
    {"at": "2026-04-19T10:00:00Z", "from": null, "to": "medium", "by": "claude:p0_suggest"},
    {"at": "2026-04-19T10:05:00Z", "from": "medium", "to": "high", "by": "user:Yvetteqf"}
  ],
  "triggers_matched": ["改鉴权"],
  "rollback_plan": "..."
}
```

---

## 18. OpenClaw 资产保留清单（v2 新增 G6）

迁移到新架构时必须显式保留/淘汰：

| 资产 | 处置 |
|------|------|
| 9 个飞书机器人配置（[/root/.openclaw/openclaw.json](file:///root/.openclaw/openclaw.json)）| **只保留 ai-pm**，其余 8 个先停用，后续按需重启 |
| OpenClaw gateway 长连接 WebSocket | **保留**，作为 ingress 飞书消息接收器 |
| `feishu_send.py` token 缓存机制 | **保留**，封装成 `feishu_*` activity |
| `insert_records.js` Bitable CRUD 模板 | **作为参考**，重写成 Python `bitable_*` activity |
| `/root/.openclaw/workspace/pm/AGENT.md` 4 阶段编排 | **替换**为 Temporal workflow code |
| `/root/.openclaw/workspace/pm/state.json` | **废弃**，状态全部移到 Postgres + Temporal |
| OpenClaw agent 调用机制（`openclaw agent --agent <id>`）| **废弃**，所有 agent 协作通过 workflow + activity |

---

## 19. 路由与配置文件（替代 v1.0 §18）

### 19.1 `config/projects.yaml`

```yaml
projects:
  healthassit:
    repo: git@github.com:user/healthassit.git
    type: react-native
    risk_blacklist_paths:
      - src/auth/**
      - src/api/payment/**
    test_frameworks: [jest, detox]
    release:
      staging: { kind: eas, profile: staging, allowed_workers: [m5] }
      prod: { kind: eas, profile: production, allowed_workers: [m5], requires: release-critical }

  maas:
    repo: git@github.com:user/maas.git
    type: k8s-service
    risk_blacklist_paths:
      - billing/**
      - migrations/**
    test_frameworks: [pytest]
    release:
      staging: { kind: kubectl, context: maas-staging, allowed_workers: [cloud, mbp] }
      prod: { kind: kubectl, context: maas-prod, allowed_workers: [mbp], requires: release-critical }
```

### 19.2 `config/workers.yaml`

每节点一份，决定订阅的 task queues 和并发上限（示例见 §6.3）。

v2.1 修正：

- **仍然没有独立 router 服务**
- 但也**不再允许 workflow 直接基于在线节点状态硬编码选路**
- 选路逻辑由 `resolve_execution_lane` activity + `projects.yaml` + `worker_capabilities` 共同完成

也就是说，路由规则存在，只是不以单独 daemon 形式存在，而是以：

- 静态配置
- 业务投影表
- 一个短 activity

三者组合实现。

### 19.3 `config/risk.yaml`

```yaml
default_levels:
  bug_fix: low
  ui_change: low
  feature: medium
  refactor: medium
  schema_migration: high
  payment: release-critical
  auth: high

cost_caps:
  P0: 30
  P1: 15
  P2: 5

triggers_to_release_critical:
  - target_env: prod
  - touches: [migrations/**, billing/**, src/auth/**]
  - keywords: [上架, 发布到生产, 密钥轮换]
  - prior_rollback: true
```

---

## 20. 目录结构

```text
~/aioperator/                     # 元仓库
├── apps/
│   ├── ingress/                  # FastAPI: 接飞书 + Bitable webhook
│   ├── orchestrator/             # workflow + activity 定义
│   └── worker_runtime/           # 节点 worker 启动器
├── workflows/
│   ├── requirement.py            # RequirementWorkflow
│   ├── tdd_implement.py          # TddImplementWorkflow (child)
│   └── release.py                # ReleaseWorkflow (child)
├── activities/
│   ├── claude/                   # claude_generate_prd, claude_review, ...
│   ├── codex/                    # codex_implement
│   ├── openai/                   # openai_review
│   ├── feishu/                   # feishu_send_card, feishu_doc_sync
│   ├── bitable/                  # bitable_upsert
│   ├── git/                      # git_commit, git_pr
│   ├── ci/                       # run_ci_locally
│   └── release/
│       ├── eas.py
│       └── k8s.py
├── config/
│   ├── projects.yaml
│   ├── workers.yaml
│   ├── risk.yaml
│   └── feishu.yaml
├── db/
│   ├── migrations/               # alembic
│   └── schema.sql
├── deploy/
│   ├── docker-compose.yml        # temporal + postgres + ingress
│   └── workers/                  # 各节点 worker 部署单元
├── tests/
│   ├── unit/
│   ├── integration/              # 用 temporalio test framework
│   └── e2e/
├── learning/
│   ├── anti_patterns.json
│   └── exemplars/
└── docs/
    ├── ARCHITECTURE_FOR_REVIEW.md   # Codex v1.0
    └── ARCHITECTURE_v2.md           # 本文（Claude 修订）

~/projects/healthassit/                # 业务仓库（独立）
~/projects/maas/                       # 业务仓库（独立）
```

---

## 21. 落地路径（替代 v1.0 §21）

**核心理念：垂直切片，每周末有可演示成果。**

### Week 1（Phase 1，云端单节点）：跑通最小 P1 闭环

**目标**：用户在飞书发"做一个登录页" → 30 分钟后收到 PRD 卡片 → 点批准 → 看到 Git commit

任务：
- docker-compose 起 Temporal + Postgres
- 同机起 **至少两个 worker 进程**：`worker-lite` 与 `worker-llm-cloud`，即使都在云端，也先验证 task queue/poll 模型
- 写 `RequirementWorkflow` 的 P0 + P1 部分
- 实现 activity：`claude_capture_requirement`, `claude_generate_prd`, `feishu_send_card`, `git_commit`
- 写 ingress：飞书消息接收 + 卡片回调（复用 OpenClaw gateway 的 WebSocket）
- 写 `worker_capabilities` 注册/心跳最小实现
- 不做：P2/P3/P4/P5、复杂动态选路、Bitable 同步

### Week 2：补 P2 + P3A/3B（仍单节点）

**目标**：用户批准 PRD → 自动产出 DESIGN → 测试 → 实现 → PR

任务：
- 写 P2 activity：`claude_generate_design`, `validate_test_contract`
- 写 P3 child workflow：`TddImplementWorkflow`
- TDD 门禁第 1-3 层（test_contract + P3A 先成功 + workflow 控制流）
- 落 `resolve_execution_lane` activity（先用单机注册表）
- 不做：P3D 模型评审（直接 P3E 人工批准）、完整风险分级、完整 cost cap

### Week 3：MBP 接入 + lease + outbox

**目标**：MBP 到家后注册成 worker，云端只跑 ingress + Temporal + lite activity

任务：
- MBP 装 worker_runtime + Tailscale + Temporal SDK
- 把 LLM activity 标到 `llm-local` task queue，云端 `llm-cloud` 改为 `max_activities=0`（不接活）
- 加 `claude_review`, `claude_lite_review`，启用风险分级
- Bitable 同步 activity 跑起来（异步）
- TDD 门禁第 4-5 层（git diff 校验 + CI 校验）
- 落 worker 级熔断状态回写 `worker_capabilities`

### Week 4：补 P4 + P5 + 锁 + cost cap

**目标**：完整闭环可发布到 staging

任务：
- P4 activity：`eas_build` (m5 placeholder), `k8s_apply`（staging）
- 模块/文件/环境锁实现，锁归属到 `phase_execution_id`
- cost cap 的 `reserve_budget` / `reconcile_budget`
- P5 Schedule

### Week 5+：M5 接入 + iOS + release-critical + OpenAI 终审

**目标**：高风险需求走完整链路，HealthAssit 可发 staging iOS build

任务：
- M5 装 worker，订阅 `release-ios-m5`, `xcode-m5`, `llm-fast`
- `openai_review` activity
- `release-critical` 完整流程 + 人工 checklist
- 学习闭环（exemplar 写入 + anti-pattern 检测）

---

## 22. v1.0 → v2 关键决策对照

| 主题 | v1.0 | v2 | 理由 |
|------|------|----|----|
| Workflow runtime | 自建 | Temporal | 4-6 周 → 1 周 |
| DB | SQLite (P1) → Postgres | 直接 Postgres | 避免单写者瓶颈与迁移 |
| Worker 通信 | push (§3.2) ↔ poll (§19.2) 矛盾 | 统一 long-poll | NAT 友好 + Temporal 原生 |
| Outbox | 自建表 + 重试服务 | Temporal activity 自动 retry | 等价语义，零代码 |
| Worker 注册 | 显式注册 + heartbeat 表 | Temporal poll + `worker_capabilities` 投影 | Temporal 负责分发，业务层仍需可审计选路 |
| 状态机 | 自建两层 | Workflow + Child Workflow | Temporal 原生 |
| Lock manager | 自建服务 | DB 表 + workflow 驱动续约 | 避免锁绑到瞬时 worker |
| risk_level 来源 | 未定义 | P0 Claude 建议 + 用户显式选 + operator_action 改 | 闭环 |
| low 风险评审 | 跳过 | claude_lite_review (~$0.05) | 防漏 |
| release-critical 触发 | 未定义 | §4.5 明确 5 条 | 可执行 |
| 成本上限 | cost_records 表无熔断 | `reserve_budget` + `reconcile_budget` | 在 activity 开始前守住预算 |
| 节点亲和 | 未定义 | §15.2 矩阵明确 | prod kubeconfig 不上云 |
| test_contract.json | 反复引用未定义 | §17.1 完整 schema | TDD 门禁可实现 |
| OpenClaw 资产 | 隐式废弃 | §18 显式保留/迁移清单 | 不浪费已验证资产 |
| 落地顺序 | 先建框架再做业务 | 垂直切片，Week 1 跑通 P1 | 用户每周看到价值 |

---

## 23. 待 Codex 评审挑战的问题

1. Temporal 学习曲线和运维负担是否真的低于自建（特别是 deterministic workflow 的限制）？
2. 用 Postgres 同时承载 Temporal 元数据 + 业务投影表是否合理？要不要分实例？
3. `claude_lite_review` 在 low 风险下 ~$0.05/次的成本估算是否过乐观？
4. `resolve_execution_lane` 作为短 activity 是否已经足够，还是仍需要独立 route service？
5. 模块锁靠 DB 行 + workflow 续约，没用 Redis/Etcd，会不会在锁数量多时变慢？
6. `test_contract.json` 的 `ac_to_tests` 在 RN/K8s 两种项目下结构是否需要分裂？
7. risk_level 的"用户必须显式选"是否与"自然语言驱动、最少干预"原则冲突？要不要默认接受 Claude 建议、只在 P1 卡片上允许改？
8. prod kubeconfig "MBP only" 在 MBP 长期离线时的 OOB 授权流程是否需要更具体？
9. `validate_ios_credentials` 是否已经足够，还是应该尽快拆成独立的 iOS release support workflow？
10. `reserve_budget` 的估算模型应该按 token、按 activity 类型，还是按项目历史统计三者混合？

---

## 24. 最终结论

v2.1 在 v1.0 的架构正确性基础上，**用 Temporal 砍掉一半自建工作量**，**补齐 6 个具体缺口**，并进一步把 **选路、亲和、锁、预算、审计** 这 5 个会阻塞实现的内核问题收敛到可执行形态，让 Week 1 就有用户可见的价值，Week 3 完成 MBP 接入，Week 5 接近完整生产线形态。

如果这版通过 Codex 评审，下一步：
1. Week 1 拆任务建 Bitable + 启动 Temporal/Postgres docker
2. 实现 `RequirementWorkflow` 的 P0/P1 + 4 个核心 activity
3. 用 HealthAssit 的"做一个 demo 登录页"作为 Week 1 验收用例
