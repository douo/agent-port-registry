# APR v2 — Web UI + 进程管理 + 主从节点 + 端口转发

**版本：** v2.0
**对应 v1 计划：** `docs/plan.md`
**进度落盘：** `docs/progress.md`（v2 章节）
**状态：** 已批准，作为实现依据

---

## 1. 目标

Local v1 (P0) 已交付 `svcctl` CLI → Registry (Unix socket) → SQLite 的完整闭环。
v2 在此之上交付四件事：

1. **Web UI** —— 现代化仪表盘，成为主要查看入口（v1 的 P1 deferred 项）
2. **服务进程管理** —— `services.start_command` / `working_directory` 已入库但从未被执行，本次接上
3. **主从节点** —— 一台机做主节点，通过**纯 SSH 通道**拉取从节点的服务配置与运行状态
4. **一键端口转发** —— 主节点 `ssh -N -L` 把从节点端口映射到本地，UI 一键开关

### 1.1 突破的 PRD 边界

PRD §4.1「本机节点」写明：

> Local v1 只管理当前电脑上的服务和端口……请求中不需要传远程主机、SSH 主机或网络拓扑。

v2 显式突破这一条。突破方式受严格约束：

- **从节点零网络暴露** —— 继续只监听 Unix socket，不开任何 TCP 端口
- **不新增鉴权面** —— 完全复用机器间已配置的 SSH 信任，不引入 token / TLS / mTLS
- **从节点是自身数据的唯一权威** —— 主节点只读缓存快照，不反向写入从节点

因此 `services` 表的语义不变，仍然只描述**本机**服务；跨机数据走独立的 `node_snapshots`。

---

## 2. 现状约束

实现依赖以下既有事实：

| 事实 | 位置 | 影响 |
|---|---|---|
| Starlette + uvicorn，默认 Unix socket | `src/apr/cli/serve.py:78` | 浏览器无法直连 socket，Web 必须另开 TCP |
| `migrate()` 只跑 schema.sql，无增量迁移 | `src/apr/store/db.py:37-49` | **加表前必须先补迁移框架** |
| `schema.sql` 被 wheel force-include | `pyproject.toml:37-38` | 新增 migrations 目录要同步改打包配置 |
| `probe_listeners()` → port/pid/cmdline | `src/apr/listener/probe.py:100` | 运行状态与转发健康检查的现成原语 |
| `PortPool` + `active_claimed_ports()` | `allocator/pool.py`、`repository.py:313` | 挑选本地转发端口直接复用 |
| 测试各文件自建 fixture，无 conftest | `tests/api/test_crud.py:18` | 沿用该范式 |
| 全程无鉴权，安全靠 socket `0600` | — | Web / TCP 一律只绑 `127.0.0.1` |

---

## 3. 分阶段执行

每阶段独立可用、独立提交，完成后立即更新 `docs/progress.md`（沿用 v1「不得攒批」约定）。

### 阶段 1 — DB 迁移框架 + v2 数据模型

- `src/apr/store/migrations/002_v2.sql`；`db.py` 改为读 `schema_version` 后按序应用
  `NNN_*.sql`，事务内 bump 版本；`CURRENT_SCHEMA_VERSION = 2`
- `pyproject.toml` force-include 增加 migrations 目录
- 新表：

  | 表 | 用途 | 关键列 |
  |---|---|---|
  | `nodes` | 从节点定义 | ssh_host / ssh_user / ssh_port / identity_file、apr_command、enabled、last_seen_at、last_error |
  | `node_snapshots` | 从节点状态快照 | node_id、fetched_at、payload_json、status、error |
  | `port_forwards` | SSH 转发实例 | node_id、remote_port、local_port、pid、state、last_error |
  | `managed_processes` | 被托管的服务进程 | service_id、pid、state、log_path、exit_code |

- **设计决策**：从节点数据以 JSON 快照存储，不并入 `services` 表。理由：避免跨机 id 冲突；
  从节点 schema 可独立演进；主节点崩溃不影响从节点权威数据
- 测试：`tests/unit/test_migrations.py` —— v1 库升级 v2 后数据不丢、重复迁移幂等

### 阶段 2 — Web UI 骨架 + 只读仪表盘

**服务端**

- `svcctl serve --web`：同一 event loop 内跑**两个** uvicorn Server（uds + TCP），
  `asyncio.gather` —— CLI 继续走 socket，浏览器走 `127.0.0.1:17989`
- `src/apr/webui/` 挂载 `StaticFiles(html=True)` + SPA fallback
- 新只读端点：

  | 端点 | 用途 |
  |---|---|
  | `GET /v1/overview` | KPI 聚合（服务数、占用端口数、池利用率、节点数） |
  | `GET /v1/listeners` | `probe_listeners()` 结果，判断服务是否真在跑 |
  | `GET /v1/pool` | 端口池配置 + 占用图谱，供热条可视化 |

**前端** `web/` — Vite + React 19 + TS + Tailwind v4（`@tailwindcss/vite`）

- 构建产物输出到 `src/apr/webui/static/` 并提交，**终端用户零 Node**；仅改 UI 时需 Node
- TanStack Query 管服务端状态 + 轮询；React Router 管路由
- 视图：Dashboard（KPI 卡 + 端口占用热条）、Services（虚拟化表格 + 实时监听指示点）、
  Service 详情、Ports（端口反查）
- 暗色优先，中性色 + 单一强调色；⌘K 命令面板

### 阶段 3 — UI 写操作

- 复用现有 `/v1/*` 写端点：ensure / release / delete / patch
- 表单：新建服务与分配（含 block / count 资源）、编辑元数据、释放与删除二次确认
- 乐观更新 + 失败回滚；错误码映射为中文提示（复用 `api/errors.py`）

### 阶段 4 — 服务进程管理

- `POST /v1/services/{id}/start|stop`、`GET /v1/services/{id}/logs?tail=N`
- 渲染 `start_command` 中的 `{{ports.http}}` 占位符（README 已声明该语法但从未实现）
- `cwd=working_directory`，日志落 `state_dir/logs/{service_id}.log`，pid 记入 `managed_processes`
- 停止：SIGTERM → 超时 SIGKILL；服务启动时对账上一轮遗留 pid

> **安全说明**：此阶段引入「通过 Web 界面执行任意命令」的能力。
> 默认关闭，需配置 `process_management.enabled: true` 显式开启，且仅回环可达。

### 阶段 5 — 主从节点

- `nodes` CRUD 端点 + UI 节点管理页
- 拉取：`ssh -o BatchMode=yes {target} '{apr_command} list --json'`
- **命令注入防护**：list 形式 `subprocess`，不经 shell；host / user / port 做字符白名单校验
- 后台 asyncio 任务按间隔刷新 enabled 节点，结果写 `node_snapshots`
- UI：节点卡片（在线 / 离线 / 错误 + 最后同步时间），从节点服务列表与本机同构展示

### 阶段 6 — 一键端口转发

- `POST /v1/nodes/{id}/forwards {remote_port, local_port?}`
  1. 用 `PortPool` + `probe_listeners()` 选一个空闲本地端口
  2. spawn `ssh -N -o ExitOnForwardFailure=yes -L {local}:127.0.0.1:{remote} {target}`
  3. pid 记入 `port_forwards`
- `DELETE /v1/forwards/{id}` 杀进程
- 健康检查：pid 存活 **且** 本地端口在监听
- 服务启动时对账孤儿 pid
- UI：远程服务每个端口一个开关，开启后显示可点击的 `localhost:PORT`

---

## 4. 验证

每阶段结束都要跑通：

```bash
uv run pytest -q                      # 各阶段补测试，保持全绿
uv run svcctl serve --web             # 阶段 2 起
curl -s localhost:17989/v1/overview   # 聚合端点
curl -sI localhost:17989/             # SPA 入口
cd web && npm run build               # 产物同步回 src/apr/webui/static/
```

**端到端（阶段 6 完成后）**：主节点 UI 添加 SSH 从节点 → 看到从节点服务列表 →
点某端口的转发开关 → `curl localhost:<forwarded>` 命中从节点上的服务。

**无第二台机器时的降级验证**：把 `localhost` 自身注册为「从节点」（SSH 到自己），
全链路可完整跑通。

---

## 5. 落盘约定

- 本计划即 v2 实现依据
- `docs/progress.md` v2 章节**每完成一个阶段立即更新**，并单独 git commit
- 架构变更（尤其突破 PRD §4.1 单机边界）记入 `docs/architecture.md`
