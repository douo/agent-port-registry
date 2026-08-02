# Agent Port Registry — 技术选型与架构设计

**版本：** Local v1.0  
**对应 PRD：** `Agent_Port_Registry_Local_PRD_v1.0.md`  
**状态：** 已定稿，作为实现依据

---

## 1. 技术选型

### 1.1 选型结论

| 维度 | 选择 | 理由 |
|---|---|---|
| 语言 / 运行时 | **Python 3.12+**（本机 3.14） | 本机已有 `python3` + `uv`；开发迭代快；stdlib 含 `sqlite3` |
| 包管理 / 构建 | **uv** + `pyproject.toml` | 锁定依赖、单命令安装、可打包 console scripts |
| CLI 框架 | **Typer** | 子命令结构清晰；自动 `--help`；与 Pydantic 配合好 |
| HTTP API | **Starlette**（轻量 ASGI） | Registry 只需少量 REST 路由，无需完整 FastAPI 重量；自带 TestClient 生态 |
| ASGI 服务器 | **uvicorn** | 成熟、支持 Unix Socket / `127.0.0.1` |
| 数据校验 | **Pydantic v2** | 请求/响应模型、错误字段校验与 PRD JSON schema 对齐 |
| 持久化 | **SQLite**（stdlib `sqlite3`） | 与 PRD 一致；单文件可备份；本机零运维 |
| 并发控制 | SQLite **WAL + 事务 + 应用层单写锁** | 保证 ensure 原子性；主键约束为最终防线 |
| 传输 | **Unix Domain Socket 优先**，fallback `127.0.0.1` HTTP | 满足 NFR-003 本地安全 |
| 监听探测 | **/proc/net/tcp** + **ss** 兜底 | Linux 本机；无需 root；可选 PID/cmdline |
| 测试 | **pytest** + **httpx** ASGITransport | 单元 + API + CLI 集成 |
| 分发入口 | console script：`svcctl` | 单一二进制入口（CLI + `serve` 子命令启 daemon） |

### 1.2 未选用方案（及原因）

| 候选 | 放弃原因 |
|---|---|
| Go / Rust | 本机无 toolchain；引入成本高于收益 |
| FastAPI | 功能过剩；Starlette 足够且依赖更薄 |
| PostgreSQL / Redis | 违反「本机个人工具」边界 |
| gRPC | Agent 集成成本高；PRD 明确 JSON/HTTP |
| 仅文件系统 JSON | 并发与 Claim 唯一性难保证 |

### 1.3 关键依赖（最小集）

```
typer[all]
starlette
uvicorn
pydantic>=2
httpx          # CLI 调 Registry + 测试
pyyaml         # 配置文件
pytest         # dev
```

---

## 2. 系统架构

### 2.1 组件拓扑

```text
┌─────────────────────────────────────────────────────────┐
│  Agent Skill (Codex / Claude Code / Grok Build / Human) │
└───────────────────────────┬─────────────────────────────┘
                            │ stdin JSON / CLI flags
                            ▼
┌─────────────────────────────────────────────────────────┐
│  svcctl  (CLI 客户端)                                     │
│  ensure | list | search | inspect-* | check | release   │
│  serve  | status | backup                               │
└───────────────────────────┬─────────────────────────────┘
                            │ HTTP over Unix Socket
                            │ 或 http://127.0.0.1:<port>
                            ▼
┌─────────────────────────────────────────────────────────┐
│  APR Registry (本机常驻进程，由 svcctl serve 启动)         │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────────┐ │
│  │ HTTP API    │→ │ Domain /     │→ │ SQLite Store    │ │
│  │ /v1/*       │  │ Allocator    │  │ WAL mode        │ │
│  └─────────────┘  └──────┬───────┘  └─────────────────┘ │
│                          │                               │
│                          ▼                               │
│                 ┌─────────────────┐                      │
│                 │ Listener Probe  │  /proc + ss          │
│                 └─────────────────┘                      │
└─────────────────────────────────────────────────────────┘
```

### 2.2 进程与生命周期

1. **默认模式**：`svcctl <command>` 作为客户端连接已运行的 Registry。
2. **懒启动（P0 增强）**：若 socket 不可用，客户端可自动 `spawn` 后台 `svcctl serve --daemon`（可选，首版可要求显式 serve；实现时做 auto-start）。
3. **数据目录**（默认）：
   - `~/.local/share/apr/apr.db`
   - `~/.local/share/apr/apr.sock`
   - `~/.config/apr/config.yaml`
   - 日志：`~/.local/state/apr/apr.log`
4. **权限**：数据目录 `0700`，db/socket `0600`/`0700`。

### 2.3 模块划分

```text
agent-port-registry/
├── pyproject.toml
├── README.md
├── docs/
│   ├── architecture.md      # 本文档
│   ├── plan.md              # 实现计划
│   └── progress.md          # 步骤进度落盘
├── skills/
│   ├── common/SKILL.md
│   ├── codex/
│   ├── claude-code/
│   └── grok-build/
├── src/apr/
│   ├── __init__.py
│   ├── __main__.py          # python -m apr
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── app.py           # Typer 根应用
│   │   ├── ensure.py
│   │   ├── query.py
│   │   ├── release.py
│   │   ├── serve.py
│   │   └── client.py        # HTTP 客户端
│   ├── api/
│   │   ├── __init__.py
│   │   ├── app.py           # Starlette app 工厂
│   │   ├── routes.py
│   │   └── errors.py
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── models.py        # Pydantic 领域模型
│   │   ├── identity.py      # Service 唯一键规范化
│   │   ├── spec.py          # Resource / Allocation 规格比较
│   │   └── errors.py        # 业务错误码
│   ├── allocator/
│   │   ├── __init__.py
│   │   ├── engine.py        # First Fit 分配
│   │   └── pool.py          # 端口池 / exclude
│   ├── listener/
│   │   ├── __init__.py
│   │   └── probe.py         # 本机监听检测
│   ├── store/
│   │   ├── __init__.py
│   │   ├── db.py            # 连接、迁移、事务
│   │   ├── schema.sql
│   │   └── repository.py    # services/allocations/claims
│   ├── service/
│   │   ├── __init__.py
│   │   └── ensure.py        # Ensure 用例编排
│   └── config.py
└── tests/
    ├── unit/
    ├── api/
    └── integration/
```

### 2.4 核心用例：Ensure 事务流

严格按 PRD §15.4：

```text
BEGIN TRANSACTION
  1. normalize agent/service identity keys
  2. find or create Service (upsert 元数据字段)
  3. find Allocation by (service_id, allocation_name)
     ├── state=reserved 且存在：
     │     校验 request_spec 一致 → 否则 ALLOCATION_SPEC_MISMATCH
     │     读 allocated_ports → 探测 availability → 返回 existing=true
     └── 不存在 或 已 released：
           4. snapshot OS listeners
           5. First Fit 为所有 resources 选端口（内存集合防自冲突）
           6. INSERT allocation + allocated_ports + active_port_claims
           7. 任一步失败 → ROLLBACK
COMMIT
返回 ports + availability
```

并发：同一 db 上 ensure 串行化（`threading.Lock` 或 SQLite `BEGIN IMMEDIATE`）。

### 2.5 分配算法（MVP）

- 默认池：`20000–39999`（可配置）
- `exclude`：单端口或区间
- **First Fit**：
  - `single`：第一个可用端口（偏好端口优先）
  - `block`：第一个长度 ≥ size 的连续空闲段
  - `count` + contiguous：同 block
  - `count` + 非连续：前 N 个可用端口，按 `port_names` 映射
- 可用判定：`∉ active_port_claims ∧ ∉ OS listeners ∧ ∉ exclude ∧ ∈ within`

### 2.6 API 表面（PRD §10）

| Method | Path | 说明 |
|---|---|---|
| POST | `/v1/allocations/ensure` | 创建/幂等返回 Allocation |
| GET | `/v1/services` | 列表/搜索 |
| GET | `/v1/services/{id}` | 详情 |
| PATCH | `/v1/services/{id}` | 更新索引元数据 |
| GET | `/v1/ports/{port}` | 端口反查 |
| GET | `/v1/allocations/{id}/check` | 监听检查 |
| POST | `/v1/allocations/{id}/release` | 显式释放 |
| GET | `/healthz` | 健康检查 |

### 2.7 CLI 表面（PRD §11）

| 命令 | 映射 |
|---|---|
| `svcctl ensure --json -` / `--file` / flags | POST ensure |
| `svcctl list` / `search` | GET services |
| `svcctl inspect-service` / `inspect-port` | GET service / port |
| `svcctl check` / `check-all` | GET check |
| `svcctl service update` | PATCH service |
| `svcctl release` | POST release |
| `svcctl serve` | 启动 Registry |
| `svcctl status` | 健康/连接信息 |
| `svcctl backup` | SQLite 一致性备份（P1，骨架预留） |

### 2.8 错误模型

统一 JSON：

```json
{
  "error": {
    "code": "PORT_CAPACITY_EXHAUSTED",
    "message": "..."
  }
}
```

业务异常类映射 PRD §16 错误码；HTTP 状态：4xx 业务可预期错误，5xx `INTERNAL_ERROR`。

---

## 3. 数据模型

与 PRD §14 完全对齐，额外约定：

- `id` 格式：`svc_` / `alloc_` + ULID（可排序、无中心）
- 时间字段：ISO-8601 UTC 文本
- `request_spec_json`：规范化后的 resources 数组 JSON，用于规格一致性比较
- 迁移：`schema_version` 表 + 启动时 apply

---

## 4. 安全与本地约束

- 仅绑定 Unix Socket 或 `127.0.0.1`
- 无认证（本机单用户信任模型）
- 日志不记录 secret；`start_command` 只存模板
- 数据目录用户私有权限

---

## 5. 测试策略

| 层级 | 覆盖 |
|---|---|
| unit | identity 规范化、spec 比较、First Fit、exclude |
| store | 事务原子性、唯一约束、release 后可再分配 |
| api | ensure 幂等、spec mismatch、多 resource 回滚 |
| integration | CLI → socket → DB 端到端；AC-001…AC-019 抽样自动化 |

---

## 6. 交付边界（本迭代）

**P0 必做（见 plan.md）：**

- Registry + SQLite + ensure 全资源类型
- 幂等、Claim、OS 排除、list、端口反查、release
- 通用 Skill + 三 Agent 适配目录

**P1 本迭代可选骨架：**

- `check` 完整 PID/cmdline
- search、backup、Web UI 可后置

---

## 7. 决策记录

| ID | 决策 | 理由 |
|---|---|---|
| D1 | Python + uv | 环境就绪，交付速度优先 |
| D2 | 单入口 `svcctl`（含 serve） | 降低安装与使用心智负担 |
| D3 | Unix Socket 默认 | 无端口占用、本机限定 |
| D4 | Starlette 而非 FastAPI | 依赖更轻，API 面小 |
| D5 | stdlib sqlite3 | 零原生扩展风险，WAL 足够 |
| D6 | First Fit 仅 | PRD MVP 明确要求 |
| D7 | ensure 自动拉起 daemon | 提升 Agent 首次使用成功率 |
