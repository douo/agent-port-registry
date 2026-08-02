# Agent Port Registry 产品需求文档

**版本：** Local v1.0  
**状态：** 可直接交付开发  
**产品简称：** APR  
**目标用户：** 在单台开发电脑上使用 Codex、Claude Code、Grok Build 等 Coding Agent 的个人开发者

---

## 1. 产品定义

Agent Port Registry 是一个运行在本机的端口分配与服务索引工具。

当 Agent 准备启动需要监听端口的服务时，Agent 向 APR 提交：

1. 服务相关信息；
2. 所需端口资源。

APR 返回并持久化：

- 一个固定端口；
- 一个连续端口范围；
- 或指定数量的命名端口。

相同服务重复申请相同资源时，APR 必须返回原来的分配，不得重新选择端口。

APR 同时根据申请信息建立本机服务索引，使用户能够查询：

- 当前登记了哪些服务；
- 每个服务的用途；
- 代码位于哪里；
- 工作目录是什么；
- 如何启动；
- 占用了哪些端口；
- 端口属于哪个服务。

---

## 2. 产品核心链路

```text
Agent 准备启动监听服务
        ↓
收集服务信息和端口需求
        ↓
调用 svcctl ensure
        ↓
本机 APR 查询已有固定分配
        ├── 已存在：返回原分配
        └── 不存在：检查并分配本机可用端口
        ↓
APR 保存服务索引和端口归属
        ↓
Agent 使用返回端口启动服务
```

产品的核心输入和输出为：

```text
服务信息 + 端口资源需求
              ↓
固定且幂等的本机端口分配
              +
可查询的本机服务索引
```

---

## 3. 产品目标

### 3.1 端口分配

APR 必须支持：

- 申请一个端口；
- 申请一个连续端口范围；
- 申请指定数量的端口；
- 为多个用途申请命名端口；
- 限制端口必须从指定范围中分配；
- 提供偏好端口；
- 重复申请返回原分配；
- 服务停止后继续保留端口；
- 显式释放端口；
- 避免与 APR 已登记端口冲突；
- 避免给新服务分配当前已被本机进程监听的端口。

### 3.2 服务索引

APR 必须能够登记并查询：

- Agent 类型；
- 可选的 Agent 项目标识；
- 服务稳定标识；
- 服务名称和用途；
- 代码路径；
- 工作目录；
- 启动命令模板；
- 端口名称和端口值；
- 创建时间；
- 更新时间；
- 当前登记状态。

### 3.3 Agent 集成

APR 必须提供统一 CLI，并提供适用于以下 Agent 的全局 Skill 或指令模板：

- Codex；
- Claude Code；
- Grok Build；
- 其他能够执行本机命令的 Agent。

所有 Agent 必须调用同一个 `svcctl` 接口。APR 的业务逻辑不得依赖某个特定 Agent。

---

## 4. 使用范围

### 4.1 本机节点

Local v1 只管理当前电脑上的服务和端口。

所有 Service 的运行节点固定为：

```text
local
```

请求中不需要传远程主机、SSH 主机或网络拓扑。

### 4.2 本机组件

系统由三个本机组件组成：

```text
Agent Skill
    ↓
svcctl CLI
    ↓
APR Registry
    ↓
SQLite
```

推荐 Registry 作为本机常驻进程运行，并通过以下任一接口提供服务：

- Unix Domain Socket；
- 或仅监听 `127.0.0.1` 的 HTTP API。

Registry 不承载业务流量，只负责端口资源和服务信息管理。

---

## 5. 核心概念

### 5.1 Agent Context

表示申请来自哪个 Agent。

```yaml
agent:
  type: codex
  project_id: project-model-platform
```

字段说明：

| 字段 | 必填 | 说明 |
|---|---:|---|
| `type` | 否 | Agent 类型，例如 `codex`、`claude-code`、`grok-build` |
| `project_id` | 否 | Agent 提供的项目或工作区标识 |

人工调用时，`agent` 可以为空：

```yaml
agent: null
```

Agent Context 用于服务分组和查询，不作为端口本身的身份。

### 5.2 Service

Service 表示本机上一个具体、可独立启动的服务实例。

示例：

- `model-api/main`
- `frontend/dev`
- `notebook/experiment-a`
- `postgres/test`

字段：

```yaml
service:
  key: model-api
  instance: main
  name: Model API
  description: 提供本地模型推理接口
  code_path: /home/kai/projects/model-platform
  working_directory: /home/kai/projects/model-platform/api
  start_command: uv run python -m api --port {{ports.http}}
```

### 5.3 Allocation

Allocation 是 Service 拥有的一组固定端口资源。

同一个 Service 可以拥有多组 Allocation：

```text
default
workers
debug
test-cluster
```

每组 Allocation 使用 `allocation_name` 标识。

### 5.4 Resource

Resource 是一次 Allocation 中的端口需求。

支持三种类型：

- `single`
- `block`
- `count`

---

## 6. 服务身份和幂等规则

### 6.1 Service 唯一键

Service 唯一键由以下字段构成：

```text
agent.type
+ agent.project_id
+ service.key
+ service.instance
```

空值必须规范化：

```text
agent.type 为空        → human
agent.project_id 为空  → -
service.instance 为空  → default
```

示例：

```text
codex + project-model-platform + model-api + main
```

人工服务：

```text
human + - + local-dashboard + default
```

### 6.2 Allocation 唯一键

```text
service_id + allocation_name
```

相同唯一键重复调用 `ensure` 时：

- 返回已有 Allocation；
- 返回原端口；
- `existing` 为 `true`；
- 不重新执行分配；
- 不因偏好端口变化而改变已有结果。

### 6.3 规格一致性

若 Allocation 已存在，但新请求与原规格不同，返回：

```text
ALLOCATION_SPEC_MISMATCH
```

以下变化视为规格不一致：

- 资源数量变化；
- Resource 类型变化；
- `count` 变化；
- 连续性变化；
- 命名端口列表变化；
- `block.size` 变化。

APR 不得静默扩容、缩容或替换原端口。

---

## 7. 端口资源申请

### 7.1 申请一个端口

请求：

```json
{
  "name": "http",
  "type": "single"
}
```

返回：

```json
{
  "ports": {
    "http": 20104
  }
}
```

可选参数：

```json
{
  "name": "http",
  "type": "single",
  "preferred_port": 28080,
  "strict_preferred": false,
  "within": {
    "start": 20000,
    "end": 29999
  }
}
```

规则：

- 偏好端口空闲时优先使用；
- 偏好端口不可用且 `strict_preferred=false` 时，继续寻找其他端口；
- 偏好端口不可用且 `strict_preferred=true` 时，返回错误；
- 端口必须位于 `within` 范围内。

### 7.2 申请连续端口范围

请求：

```json
{
  "name": "workers",
  "type": "block",
  "size": 8,
  "within": {
    "start": 20000,
    "end": 29999
  }
}
```

返回：

```json
{
  "blocks": {
    "workers": {
      "start": 20120,
      "end": 20127,
      "size": 8
    }
  }
}
```

APR 必须确认范围内所有端口：

- 未被有效 Allocation 登记；
- 当前未被本机进程监听；
- 未出现在排除列表中。

### 7.3 申请指定数量的端口

请求三个非连续命名端口：

```json
{
  "name": "service-ports",
  "type": "count",
  "count": 3,
  "contiguous": false,
  "port_names": [
    "http",
    "metrics",
    "debug"
  ]
}
```

返回：

```json
{
  "ports": {
    "http": 20130,
    "metrics": 20131,
    "debug": 20135
  }
}
```

请求连续命名端口：

```json
{
  "name": "service-ports",
  "type": "count",
  "count": 3,
  "contiguous": true,
  "port_names": [
    "http",
    "metrics",
    "debug"
  ]
}
```

命名端口按 `port_names` 的顺序映射到连续端口。

### 7.4 一次申请多个 Resource

```json
{
  "resources": [
    {
      "name": "http",
      "type": "single"
    },
    {
      "name": "workers",
      "type": "block",
      "size": 8
    },
    {
      "name": "aux",
      "type": "count",
      "count": 2,
      "contiguous": false,
      "port_names": ["metrics", "debug"]
    }
  ]
}
```

整个请求必须原子执行：

- 所有 Resource 成功后才写入；
- 任意 Resource 无法满足时，所有新 Claim 回滚；
- 不得产生部分 Allocation。

---

## 8. 本机端口冲突规则

APR 管理两类端口状态：

```text
Registry Claim
OS Listener
```

### 8.1 新 Allocation

为新 Allocation 分配端口时，候选端口必须同时满足：

- 不属于其他有效 Registry Claim；
- 当前没有本机进程监听；
- 不在配置排除范围；
- 满足请求的范围和连续性。

### 8.2 已有 Allocation

Service 已有固定端口时，`ensure` 必须返回原端口。

若原端口当前被本机进程监听：

- APR 仍返回原固定分配；
- 同时返回占用检测结果；
- 不得自动重新分配端口。

示例响应：

```json
{
  "existing": true,
  "ports": {
    "http": 20104
  },
  "availability": {
    "http": {
      "state": "occupied",
      "pid": 18273,
      "command": "python -m http.server 20104"
    }
  }
}
```

Agent 必须判断该进程是否为预期服务。无法确认时，不得在其他端口偷偷启动同一服务。

### 8.3 服务停止

服务停止后：

```text
OS Listener 消失
Registry Claim 保留
```

该端口仍不得分配给其他 Service。

---

## 9. 功能需求

### FR-001 创建或匹配 Service

`ensure` 根据 Service 唯一键：

- 查找已有 Service；
- 不存在时创建；
- 存在时复用。

### FR-002 更新服务索引信息

Service 已存在时，`ensure` 可更新：

- `name`
- `description`
- `code_path`
- `working_directory`
- `start_command`

更新这些字段不得改变端口。

### FR-003 创建或返回 Allocation

根据 `service_id + allocation_name`：

- 已存在时返回原 Allocation；
- 不存在时执行新分配。

### FR-004 分配单端口

支持 `single` Resource。

### FR-005 分配连续端口段

支持 `block` Resource。

### FR-006 分配指定数量端口

支持连续和非连续 `count` Resource。

### FR-007 多 Resource 原子分配

一次 `ensure` 中所有 Resource 必须共同成功或共同失败。

### FR-008 端口持久保留

Allocation 默认：

```yaml
state: reserved
sticky: true
```

Registry 重启或电脑重启后必须保持原分配。

### FR-009 显式释放

只有显式调用 release 才能释放 Allocation。

释放后：

- Allocation 状态变为 `released`；
- 保留历史端口；
- 删除有效 Claim；
- 原端口可以重新分配。

### FR-010 服务列表

支持查看所有 Service，并显示：

- Agent；
- Agent Project ID；
- Service Key；
- Instance；
- 名称；
- 描述；
- 代码路径；
- 启动命令；
- 所有 Allocation 和端口。

### FR-011 按端口反查

输入端口号，返回唯一 Service 和 Allocation。

### FR-012 搜索服务

支持按以下内容搜索：

- 名称；
- Service Key；
- 描述；
- Agent 类型；
- Agent Project ID；
- 代码路径。

### FR-013 本机监听检测

支持检查：

```bash
svcctl check <service-or-allocation>
```

返回各端口当前是否监听，以及可获取时的 PID 和命令。

### FR-014 人工登记

人工用户可以不传 Agent Context，直接通过 CLI 创建 Service 和申请端口。

---

## 10. 核心 API

Registry 可通过 Unix Socket HTTP 或 localhost HTTP 实现以下 API。

### 10.1 Ensure Allocation

```http
POST /v1/allocations/ensure
```

请求：

```json
{
  "agent": {
    "type": "codex",
    "project_id": "project-model-platform"
  },
  "service": {
    "key": "model-api",
    "instance": "main",
    "name": "Model API",
    "description": "提供本地模型推理接口",
    "code_path": "/home/kai/projects/model-platform",
    "working_directory": "/home/kai/projects/model-platform/api",
    "start_command": "uv run python -m api --http-port {{ports.http}} --metrics-port {{ports.metrics}}"
  },
  "allocation_name": "default",
  "resources": [
    {
      "name": "http",
      "type": "single"
    },
    {
      "name": "metrics",
      "type": "single"
    }
  ]
}
```

成功响应：

```json
{
  "service_id": "svc_01K4MODELAPI",
  "allocation_id": "alloc_01K4PORTS",
  "existing": false,
  "sticky": true,
  "ports": {
    "http": 20104,
    "metrics": 20105
  },
  "availability": {
    "http": {
      "state": "free"
    },
    "metrics": {
      "state": "free"
    }
  }
}
```

### 10.2 查询 Service

```http
GET /v1/services
GET /v1/services/{service_id}
```

### 10.3 搜索

```http
GET /v1/services?query=model
GET /v1/services?agent_type=codex
GET /v1/services?agent_project_id=project-model-platform
```

### 10.4 按端口查询

```http
GET /v1/ports/{port}
```

### 10.5 更新 Service

```http
PATCH /v1/services/{service_id}
```

### 10.6 检查监听状态

```http
GET /v1/allocations/{allocation_id}/check
```

### 10.7 释放 Allocation

```http
POST /v1/allocations/{allocation_id}/release
```

请求：

```json
{
  "reason": "service deleted by user"
}
```

### 10.8 Registry 健康检查

```http
GET /healthz
```

---

## 11. CLI 需求

命令名称：

```text
svcctl
```

### 11.1 Agent 标准调用

通过标准输入：

```bash
svcctl ensure --json -
```

通过文件：

```bash
svcctl ensure --file request.json
```

默认输出 JSON。

### 11.2 人工申请一个端口

```bash
svcctl ensure \
  --service model-api \
  --instance main \
  --name "Model API" \
  --description "本地模型接口" \
  --port http
```

### 11.3 人工申请连续端口段

```bash
svcctl ensure \
  --service worker-cluster \
  --block workers=8
```

### 11.4 人工申请多个命名端口

```bash
svcctl ensure \
  --service model-api \
  --ports http,metrics,debug
```

### 11.5 查询

```bash
svcctl list
svcctl list --agent codex
svcctl list --agent-project project-model-platform
svcctl search "模型接口"
svcctl inspect-service svc_01K4MODELAPI
svcctl inspect-port 20104
```

### 11.6 检查端口

```bash
svcctl check svc_01K4MODELAPI
svcctl check-all
```

### 11.7 更新服务索引

```bash
svcctl service update svc_01K4MODELAPI \
  --description "新的服务说明" \
  --start-command "uv run python -m api --port {{ports.http}}"
```

### 11.8 释放

```bash
svcctl release alloc_01K4PORTS \
  --reason "service removed" \
  --yes
```

没有 `--yes` 时必须进行交互确认。

---

## 12. Agent Skill 需求

### 12.1 Skill 目的

当 Agent 即将启动或配置本机监听端口的服务时，强制 Agent：

1. 描述服务；
2. 描述端口需求；
3. 调用 `svcctl ensure`；
4. 使用 APR 返回的端口；
5. 不自行选择端口。

### 12.2 触发条件

遇到以下行为时必须使用 Skill：

- 启动 HTTP、HTTPS、WebSocket、RPC、TCP 或 UDP 服务；
- 启动前端开发服务器；
- 启动 API；
- 启动 Notebook；
- 启动调试服务；
- 启动本机数据库；
- 配置 Docker 主机端口；
- 启动需要多个端口的本机程序；
- 为测试或开发创建连续端口范围。

### 12.3 Agent 应提供的信息

Agent 应尽最大可能提供：

- Agent 类型；
- 可选 Agent Project ID；
- 稳定 Service Key；
- Instance；
- 服务名称；
- 服务用途；
- 代码路径；
- 工作目录；
- 启动命令模板；
- 端口资源需求。

Agent Project ID 缺失不得阻止申请。

### 12.4 Agent 执行流程

1. 确认当前操作会启动监听端口的本机服务。
2. 识别 Service 身份。
3. 确定端口需求。
4. 构造 JSON 请求。
5. 执行 `svcctl ensure --json -`。
6. 解析端口结果。
7. 检查 `availability`。
8. 若端口空闲，将端口注入启动命令。
9. 若已有端口被未知进程占用，停止启动并说明冲突。
10. 启动服务。
11. 向用户报告服务名称、端口和查询命令。

### 12.5 强制规则

Agent 必须遵守：

- 不得直接选择监听端口；
- 不得默认使用常见端口；
- 不得以随机端口绕过 APR；
- 相同 Service 和 Allocation 必须复用原分配；
- 不得因冲突静默修改固定端口；
- 服务停止后不得释放 Allocation；
- 只有用户明确要求时才能释放；
- Agent Project ID 是可选字段；
- 一个 Service 可以申请多个命名端口；
- APR 返回错误时不得绕过 APR 启动正式服务。

### 12.6 通用 SKILL.md

```markdown
---
name: agent-port-registry
description: >
  Use before starting or configuring any local service that listens on one or
  more TCP or UDP ports.
---

# Agent Port Registry

Before starting a local listening service, request its port resources through
`svcctl ensure`.

## Required workflow

1. Identify the service:
   - Agent type;
   - optional Agent project ID;
   - stable service key;
   - optional instance key;
   - service name and purpose;
   - code path;
   - working directory;
   - start command template.

2. Determine the resource requirement:
   - one port;
   - one contiguous port block;
   - or a specified number of named ports.

3. Call `svcctl ensure` with a JSON request.

4. Parse the returned JSON.

5. Check each returned port's availability.

6. Substitute the ports into the service command or environment.

7. Start the service.

8. Report the registered service and allocated ports.

## Mandatory rules

- Never select a listening port directly.
- Never assume a common port is available.
- Never silently replace a fixed allocation.
- Reuse the same allocation on every restart.
- A stopped service retains its allocation.
- Release only after an explicit user request.
- The Agent project ID is optional.
- A service may own multiple named ports.
- When an existing port is occupied by an unknown process, stop and report the
  conflict instead of allocating a replacement.
```

### 12.7 多 Agent 适配

仓库提供：

```text
skills/
├── common/
│   └── SKILL.md
├── codex/
├── claude-code/
└── grok-build/
```

适配层只负责：

- 将通用规则安装到对应 Agent 的全局 Skill 或指令目录；
- 注入 Agent 类型；
- 获取 Agent Project ID（若 Agent 能提供）；
- 调用统一 `svcctl`。

---

## 13. 服务索引展示

MVP 提供 CLI 服务索引；可同时提供一个简单本机 Web 页面。

### 13.1 服务列表字段

```text
Agent
Agent Project
Service Key
Instance
Name
Description
Code Path
Allocation
Ports
Updated At
```

### 13.2 服务详情

详情应显示：

- 完整 Service 信息；
- 所有 Allocation；
- 每个 Resource；
- 命名端口；
- 连续端口范围；
- 启动命令模板；
- 当前端口监听状态；
- 创建时间；
- 更新时间。

### 13.3 端口反查

输入：

```text
20104
```

输出示例：

```text
Port:          20104
Service:       Model API
Service Key:   model-api
Instance:      main
Agent:         codex
Agent Project: project-model-platform
Purpose:       提供本地模型推理接口
Code Path:     /home/kai/projects/model-platform
Start Command:
  uv run python -m api --port 20104
```

---

## 14. 数据模型

### 14.1 services

```sql
CREATE TABLE services (
    id TEXT PRIMARY KEY,

    agent_type TEXT NULL,
    agent_project_id TEXT NULL,
    agent_type_key TEXT NOT NULL,
    agent_project_key TEXT NOT NULL,

    service_key TEXT NOT NULL,
    instance_key TEXT NOT NULL DEFAULT 'default',

    name TEXT NOT NULL,
    description TEXT NULL,

    code_path TEXT NULL,
    working_directory TEXT NULL,
    start_command TEXT NULL,

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    UNIQUE (
        agent_type_key,
        agent_project_key,
        service_key,
        instance_key
    )
);
```

### 14.2 allocations

```sql
CREATE TABLE allocations (
    id TEXT PRIMARY KEY,
    service_id TEXT NOT NULL,
    allocation_name TEXT NOT NULL DEFAULT 'default',

    request_spec_json TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'reserved',
    sticky INTEGER NOT NULL DEFAULT 1,

    created_at TEXT NOT NULL,
    released_at TEXT NULL,
    release_reason TEXT NULL,

    FOREIGN KEY (service_id) REFERENCES services(id),
    UNIQUE(service_id, allocation_name)
);
```

### 14.3 allocated_ports

```sql
CREATE TABLE allocated_ports (
    allocation_id TEXT NOT NULL,
    resource_name TEXT NOT NULL,
    port_name TEXT NULL,
    port INTEGER NOT NULL,
    ordinal INTEGER NOT NULL DEFAULT 0,

    FOREIGN KEY (allocation_id) REFERENCES allocations(id),

    PRIMARY KEY (
        allocation_id,
        resource_name,
        ordinal
    )
);
```

### 14.4 active_port_claims

```sql
CREATE TABLE active_port_claims (
    port INTEGER PRIMARY KEY,
    allocation_id TEXT NOT NULL,
    resource_name TEXT NOT NULL,
    ordinal INTEGER NOT NULL,

    FOREIGN KEY (allocation_id) REFERENCES allocations(id)
);
```

释放 Allocation 时：

- 删除对应 `active_port_claims`；
- 保留 `allocated_ports`；
- 更新 Allocation 状态。

---

## 15. 分配算法

### 15.1 默认端口池

配置示例：

```yaml
port_pool:
  start: 20000
  end: 39999
  exclude:
    - 22000
    - 25000-25100
```

### 15.2 First Fit

MVP 使用 First Fit：

- `single`：寻找第一个可用端口；
- `block`：寻找第一个足够长的连续可用范围；
- 非连续 `count`：依次选择前 N 个可用端口；
- 连续 `count`：按连续范围处理。

### 15.3 可用判断

端口可用条件：

```text
不在 active_port_claims
AND 当前没有本机 Listener
AND 不在 exclude
AND 位于请求范围
```

### 15.4 事务

每次新 Allocation 必须在单个数据库事务中完成：

1. 查找或创建 Service；
2. 查找已有 Allocation；
3. 已存在则校验规格并返回；
4. 获取当前本机 Listener 集合；
5. 计算所有 Resource 的候选端口；
6. 写入 `active_port_claims`；
7. 写入 Allocation；
8. 写入端口历史；
9. 提交。

数据库主键约束是并发冲突的最终防线。

---

## 16. 错误码

| 错误码 | 含义 |
|---|---|
| `INVALID_REQUEST` | 请求字段或资源规格无效 |
| `SERVICE_IDENTITY_CONFLICT` | Service 身份与现有记录冲突 |
| `ALLOCATION_SPEC_MISMATCH` | 已有 Allocation 的资源规格不同 |
| `PORT_CAPACITY_EXHAUSTED` | 指定范围没有足够端口 |
| `PREFERRED_PORT_UNAVAILABLE` | 严格偏好端口不可用 |
| `PORT_OCCUPIED` | 固定端口当前被本机进程占用 |
| `ALLOCATION_RELEASED` | Allocation 已释放 |
| `SERVICE_NOT_FOUND` | Service 不存在 |
| `ALLOCATION_NOT_FOUND` | Allocation 不存在 |
| `INTERNAL_ERROR` | 未分类内部错误 |

错误响应：

```json
{
  "error": {
    "code": "PORT_CAPACITY_EXHAUSTED",
    "message": "No contiguous block of 8 ports is available in 20000-20010."
  }
}
```

---

## 17. 非功能需求

### NFR-001 个人本机工具

APR 面向一个用户和一台电脑。

### NFR-002 持久化

Registry 或电脑重启后，所有未释放 Allocation 必须保持不变。

### NFR-003 本地安全

- Registry 只通过 Unix Socket 或 `127.0.0.1` 提供服务；
- 数据文件默认仅当前用户可读写；
- 日志不得记录环境变量秘密；
- `start_command` 可以记录模板，但不得记录密钥值。

### NFR-004 API 稳定

Agent 使用的 JSON 字段必须保持向后兼容。

### NFR-005 性能

在 10,000 个有效端口 Claim 内：

- 单端口 Ensure P95 小于 200 ms；
- Service 查询 P95 小于 100 ms。

### NFR-006 可备份

SQLite 数据库应支持本地一致性备份命令。

---

## 18. 验收标准

### AC-001 单端口

新 Service 申请一个端口时，返回一个未登记且当前未监听的本机端口。

### AC-002 幂等

相同 Service 和 Allocation 连续调用 100 次，返回完全相同的端口。

### AC-003 连续范围

申请 8 个连续端口，返回恰好 8 个连续端口。

### AC-004 指定数量

申请 5 个非连续端口，返回恰好 5 个不同端口。

### AC-005 命名端口

申请 `http`、`metrics`、`debug` 后，名称和端口映射可持久查询。

### AC-006 多 Resource 原子性

一次申请包含多个 Resource，任一无法满足时，不保留任何新 Claim。

### AC-007 Registry 唯一性

两个不同 Service 不得获得相同的有效端口 Claim。

### AC-008 OS Listener 排除

某端口已被本机进程监听时，新 Allocation 不得获得该端口。

### AC-009 固定端口冲突

已有 Allocation 的端口被其他进程监听时，Ensure 返回原端口和占用信息，不自动换端口。

### AC-010 服务停止后保留

服务停止后，端口仍属于原 Service，不得被新 Service 分配。

### AC-011 重启持久化

Registry 和电脑重启后，Service 和 Allocation 不变。

### AC-012 Agent 项目可空

人工操作不提供 Agent Project ID 时仍可登记 Service。

### AC-013 多 Agent

Codex、Claude Code 和 Grok Build 均可调用同一 CLI 登记服务。

### AC-014 同一 Agent 项目多服务

一个 Agent Project 可登记多个独立 Service。

### AC-015 多 Allocation

同一 Service 可拥有 `default` 和 `workers` 等多组 Allocation。

### AC-016 规格冲突

已有单端口 Allocation 用相同名称请求 3 个端口时，返回 `ALLOCATION_SPEC_MISMATCH`。

### AC-017 显式释放

释放后 Claim 删除，端口可重新分配，历史 Allocation 仍可查询。

### AC-018 按端口反查

任意有效 Claim 可以唯一反查 Service、用途、代码路径和启动命令。

### AC-019 元数据更新

修改服务描述和启动命令后，端口保持不变。

### AC-020 Skill 行为

Agent 启动本机监听服务前调用 `svcctl ensure`，并使用返回端口，不自行选择端口。

---

## 19. 开发优先级

### P0：可用闭环

- 本机 Registry；
- SQLite；
- `svcctl ensure`；
- `single`、`block`、`count`；
- 幂等；
- 端口 Claim；
- OS Listener 排除；
- Service 列表；
- 端口反查；
- 显式释放；
- 通用 Agent Skill；
- Codex、Claude Code、Grok Build 适配。

### P1：使用体验

- 本机 Web 服务索引；
- 服务搜索；
- `svcctl check`；
- PID 和命令识别；
- 数据库备份；
- Shell 补全。

---

## 20. 最终产品边界

Local v1 的完整产品闭环是：

```text
Agent 提供本机服务信息
        +
申请一个端口、连续范围或指定数量端口
        ↓
APR 返回固定端口资源
        ↓
Agent 使用端口启动服务
        ↓
APR 提供本机服务和端口索引
```

所有设计和实现决策应优先保证这条链路简单、可靠、幂等。
