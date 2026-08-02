# Agent Port Registry — 实现计划

**对应 PRD：** `Agent_Port_Registry_Local_PRD_v1.0.md`  
**对应架构：** `docs/architecture.md`  
**进度跟踪：** `docs/progress.md`（每步完成后更新）

---

## 总览

目标：交付 Local v1 **P0 可用闭环**——Agent / 人工通过 `svcctl ensure` 获得固定端口，Registry 持久化服务索引，可查询、可反查、可释放。

实现分 **6 个步骤**。每步有明确交付物、验收点与落盘要求。**禁止跳步**；上一步验收通过后再开下一步。

---

## Step 0 — 技术选型与架构（文档）

**状态目标：** 已完成

| 交付物 | 路径 |
|---|---|
| 架构与选型 | `docs/architecture.md` |
| 本计划 | `docs/plan.md` |
| 进度日志 | `docs/progress.md` |

**验收：** 文档齐全，模块边界与 PRD API/数据模型对齐。

---

## Step 1 — 项目骨架与基础设施

**目标：** 可安装、可启动空 Registry、可打通 healthz。

### 任务

1. 初始化 `pyproject.toml`（包名 `apr`，入口 `svcctl = apr.cli.app:main`）
2. 建立 `src/apr/` 目录骨架（空模块可 import）
3. 实现 `config.py`：数据目录、socket 路径、端口池默认值、YAML 覆盖
4. 实现最小 Starlette app：`GET /healthz`
5. 实现 `svcctl serve` / `svcctl status`
6. 实现 CLI HTTP client（Unix Socket 或 TCP）
7. **Auto-start**：client 连接失败时尝试后台启动 serve（可选开关，默认开）
8. 基础 README 安装说明

### 交付物

- `pyproject.toml`
- `src/apr/config.py`
- `src/apr/api/app.py`（healthz）
- `src/apr/cli/app.py` + `serve.py` + `client.py`
- `README.md`
- `tests/test_healthz.py`

### 验收

```bash
uv sync
uv run svcctl serve --foreground &   # 或后台
uv run svcctl status                 # 显示 ok
curl --unix-socket $SOCK http://localhost/healthz
```

### 进度落盘

更新 `docs/progress.md` → Step 1 completed + 命令记录。

---

## Step 2 — 数据模型与 SQLite Store

**目标：** PRD §14 四表落地，repository 可 CRUD，迁移可重复执行。

### 任务

1. `store/schema.sql`：services / allocations / allocated_ports / active_port_claims + schema_version
2. `store/db.py`：连接、WAL、外键、`BEGIN IMMEDIATE`、迁移
3. `domain/models.py` + `identity.py`：规范化键（human / `-` / default）
4. `domain/errors.py`：错误码枚举
5. `store/repository.py`：
   - find/create service
   - find allocation by name
   - insert allocation + ports + claims（同事务）
   - release（删 claims，改 state，保留 history）
   - list services、get by id、lookup by port
6. 单元测试：唯一约束、release 后 claim 消失

### 交付物

- `src/apr/store/*`
- `src/apr/domain/*`
- `tests/unit/test_store.py`
- `tests/unit/test_identity.py`

### 验收

- pytest store 全绿
- 手工：插入 service → claim 端口 → release → 端口可再 claim

### 进度落盘

`docs/progress.md` Step 2。

---

## Step 3 — 端口分配算法 + OS Listener

**目标：** First Fit 正确；本机监听端口不会被新分配占用。

### 任务

1. `allocator/pool.py`：范围内枚举、exclude 解析
2. `allocator/engine.py`：
   - allocate_single / block / count
   - preferred_port + strict_preferred
   - within 范围
   - 多 resource 同一 snapshot 内互斥
3. `listener/probe.py`：
   - 解析 `/proc/net/tcp`、`/proc/net/tcp6`
   - 返回 `{port: {pid?, command?}}`（PID 通过 inode→/proc 或 ss 尽量获取）
4. 单元测试：模拟 claimed + listening 集合

### 交付物

- `src/apr/allocator/*`
- `src/apr/listener/probe.py`
- `tests/unit/test_allocator.py`
- `tests/unit/test_listener.py`（可 mock /proc）

### 验收

- single / block / count / contiguous 用例通过
- preferred strict 失败返回正确错误语义（领域层）
- 监听中端口不会被选中

### 进度落盘

`docs/progress.md` Step 3。

---

## Step 4 — Registry API（Ensure 闭环）

**目标：** PRD §10 全部 P0 API；ensure 幂等与原子性。

### 任务

1. Pydantic 请求/响应模型（ensure body、error envelope）
2. `service/ensure.py`：编排 identity + store + allocator + listener
3. 路由：
   - POST `/v1/allocations/ensure`
   - GET `/v1/services`（query / agent_type / agent_project_id）
   - GET `/v1/services/{id}`
   - PATCH `/v1/services/{id}`
   - GET `/v1/ports/{port}`
   - GET `/v1/allocations/{id}/check`
   - POST `/v1/allocations/{id}/release`
4. 错误映射中间件 / exception handler
5. API 测试覆盖 AC-001~AC-011、AC-015~AC-019 中可 API 化部分

### 交付物

- `src/apr/api/routes.py`、`errors.py`
- `src/apr/service/ensure.py`
- `tests/api/test_ensure.py` 等

### 验收

关键 pytest：

- 幂等 100 次同端口
- block size=8 连续
- 多 resource 失败全回滚
- spec mismatch
- release 后再分配
- existing occupied 返回原端口 + availability

### 进度落盘

`docs/progress.md` Step 4。

---

## Step 5 — svcctl CLI 完整命令

**目标：** PRD §11 人工与 Agent 调用路径全部可用。

### 任务

1. `ensure`：`--json -` / `--file` / flag 快捷（`--service` `--port` `--ports` `--block`）
2. `list` / `search` / `inspect-service` / `inspect-port`
3. `check` / `check-all`
4. `service update`
5. `release --yes`（无 yes 则 confirm）
6. 默认 JSON 输出；人类可读表格可选 `--table`
7. CLI 集成测试（TestClient 或真实 socket）

### 交付物

- `src/apr/cli/*.py`
- `tests/integration/test_cli.py`

### 验收

```bash
echo '{...}' | uv run svcctl ensure --json -
uv run svcctl list
uv run svcctl inspect-port <port>
uv run svcctl release <alloc_id> --yes
```

### 进度落盘

`docs/progress.md` Step 5。

---

## Step 6 — Agent Skills + 验收收口

**目标：** 多 Agent 可安装 Skill；验收清单勾选。

### 任务

1. `skills/common/SKILL.md`（PRD §12.6）
2. Codex / Claude Code / Grok Build 适配说明或安装脚本
3. `docs/acceptance.md`：AC-001…AC-020 对照表与自动化/手工结果
4. README 完善：安装、首次 serve、Agent 集成
5. 全量 `pytest` 绿
6. 可选：`svcctl backup` 最小实现（sqlite backup API）

### 交付物

- `skills/**`
- `docs/acceptance.md`
- 更新后的 `README.md`
- `docs/progress.md` 标记全部完成

### 验收

- P0 功能可演示完整链路
- AC 清单全部有结论（pass / deferred with reason）

### 进度落盘

`docs/progress.md` Step 6 + 项目完成纪要。

---

## 执行纪律

1. **一步一落盘**：每步结束必须更新 `docs/progress.md`，写明完成时间、改动摘要、验收命令与结果。
2. **测试先行优先**：分配与 ensure 等核心逻辑先写失败测试再实现（可适度 pragmatic）。
3. **不超范围**：Web UI、Shell 补全等 P1 不阻塞 P0；若顺手加骨架需在 progress 注明。
4. **API 字段名与 PRD JSON 一致**，保证 Agent 集成稳定。

---

## 步骤依赖图

```text
Step 0 (docs)
   ↓
Step 1 (skeleton + healthz)
   ↓
Step 2 (store)
   ↓
Step 3 (allocator + listener)
   ↓
Step 4 (API ensure)
   ↓
Step 5 (CLI)
   ↓
Step 6 (skills + AC)
```

---

## 里程碑检查清单（P0）

- [x] Registry 常驻 + SQLite 持久化
- [x] `svcctl ensure` single / block / count
- [x] 幂等 ensure
- [x] OS Listener 排除
- [x] 多 Resource 原子性
- [x] Service 列表 + 端口反查
- [x] 显式 release
- [x] 通用 Skill + 三 Agent 目录
- [x] 自动化测试覆盖核心 AC
