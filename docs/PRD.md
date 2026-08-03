# Agent Port Registry 产品需求

## 1. 产品定义

APR 是面向 Coding Agent 的节点本地端口分配与服务目录。每台设备运行独立 APR，
主节点通过 SSH 聚合从节点服务，但不拥有从节点数据。

核心原则是 **Agents first**：Agent 负责理解并修改服务；APR 只负责分配、记录、
查询和展示，不要求第三方服务集成 APR，也不接受服务先自行占用固定端口再导入。

## 2. 用户目标

- 所有正式本地 HTTP/API 服务的端口由服务所在节点的本地 APR 分配。
- 新服务开发或第三方服务首次接入时，先取得端口，再写入默认启动配置。
- 后续启动不依赖 APR 在线，也不需要重复 ensure。
- 主节点能够通过 SSH 完整查看各从节点服务，并代理用户触发的运行控制。
- 从节点服务拥有与本机服务一致的详情、控制台信息和本机转发入口。
- SSH 网络线路变化时，由已有 SSH config 规则选路，AutoSSH 自动重连。

## 3. 非目标

- 不做通用服务发现或流量代理。
- 不给第三方项目增加 APR SDK 或运行时依赖。
- 不在每次服务启动时动态申请端口。
- 不保留固定端口导入、兼容旧字段或数据库升级路径。
- 不绕过用户现有的 SSH config 去维护第二套网络选路规则。

## 4. 服务首次配置流程

1. Agent 检查服务默认启动脚本、命令、env 或配置文件中是否已有 APR 固定端口。
2. 已有有效配置时直接启动，不调用 ensure。
3. 首次配置、首次接入、设备迁移或显式重配置时，Agent 收集服务元数据。
4. Agent 向目标节点本地 APR 调用 `POST /v1/allocations/ensure`。
5. 该节点 APR 分配固定端口并返回。
6. Agent 把端口写入该服务原生支持的默认配置来源。
7. Agent 使用正常启动命令启动服务，执行健康检查并报告结果。

ensure 必须幂等，但幂等性用于配置重试，不代表它是日常启动依赖。

## 5. 身份与归属

服务身份为：

```text
project_id + service.key + instance
```

- 节点作用域由当前 APR 实例天然确定，不由请求指定远端 `device_id`。
- `project_id`：服务所属项目；缺失时规范化为 `-`。
- `service.key`：项目内稳定服务标识。
- `instance`：同一服务的运行变体，默认 `default`。
- `agent.type`：最近一次登记该服务的 Agent，仅审计，不参与身份。

## 6. 服务元数据

Agent 应尽量主动登记：

- 名称与描述；
- 项目来源：`self-built`、`third-party-open-source`、`external`；
- 代码路径与工作目录；
- 默认启动命令与停止命令；
- 健康检查；
- 端口写入的配置位置；
- TCP/UDP 资源名称与用途。

## 7. 端口分配

- 默认池为 `41000–45999`。
- 选择该范围是为了避开常见开发服务默认端口和现有手工 SSH 转发端口
  `23459`、`28188`、`31000`、`31201`。
- Claim 至少按当前节点内的 `transport + port` 唯一。
- 支持单端口、连续块、多个命名端口和 preferred port。
- 分配避开当前节点真实 Listener；主节点不替从节点分配端口。
- 停止服务不释放端口；只有显式释放或删除才回收 Claim。
- 冲突时报告错误，不静默换号。

## 8. 节点与 SSH

- 节点记录使用稳定 `device_id`。
- 默认 `ssh_config_managed=true`，APR 只把 `ssh_host` 当作 SSH Host 别名传入。
- 用户、端口、密钥、ProxyJump、Match/Match exec 等由 `~/.ssh/config` 决定。
- AutoSSH 在连接断开后重试；每次新 SSH 连接都会重新解析 SSH config，因此网络变化后可切换线路。
- 转发状态包含 `starting`、`active`、`reconnecting`、`failed`、`stopped`。

### 8.1 主从职责

- 从节点 APR 是从节点服务、端口、元数据和进程记录的唯一权威。
- 主节点通过 SSH 获取完整服务列表、详情、状态和日志。
- 用户明确触发后，主节点可以通过 SSH 代理已有服务的 start/stop。
- 主节点不得对从节点执行 ensure、服务 CRUD、allocation release/delete，也不得修改
  从节点 APR 程序、数据库、配置、启动命令或端口。
- 节点快照是只读缓存，不得写回或转换为主节点本地 Service/Allocation。

### 8.2 本机转发归属

- SSH/AutoSSH 转发由主节点本地 APR 创建、保存、监控和停止。
- 转发记录引用从节点仅为了确定 SSH 目标和远端端口。
- 从节点 APR 不保存主节点转发状态。
- 节点服务 item 可以显示主节点派生的本机映射和跳转链接，但不得暗示转发属于从节点。

## 9. Web UI

Web UI 必须提供：

- 中心服务列表、设备/项目/Agent 过滤、端口和运行态；
- 与本机一致的服务详情：端口、元数据、启动/停止命令、健康检查、配置位置、控制台与历史；
- 节点服务 item 中直接显示相关转发；
- 服务详情链接与可访问的本机转发 URL；
- 对 `reconnecting` 与真正 `failed` 的区分。

## 10. API 请求示例

```json
{
  "agent": { "type": "codex" },
  "service": {
    "key": "model-manager",
    "instance": "main",
    "project_id": "model-platform",
    "project_origin": "self-built",
    "name": "Model Manager",
    "description": "Model management HTTP API",
    "code_path": "/path/to/model-manager",
    "working_directory": "/path/to/model-manager",
    "start_command": "./scripts/start --port {{ports.http}}",
    "stop_command": "./scripts/stop",
    "health_check": "http://127.0.0.1:{{ports.http}}/healthz",
    "configuration": ".env.local: PORT"
  },
  "allocation_name": "default",
  "resources": [
    { "name": "http", "type": "single", "transport": "tcp" }
  ]
}
```

## 11. 验收标准

- 两个不同 Agent 在同一节点配置同一项目/服务/实例时得到同一个服务身份与端口。
- 不同节点拥有独立端口空间，同一节点内不可重复 Claim。
- 首次 ensure 返回后，Agent 能将端口持久化并在 APR 不参与的情况下重启服务。
- API 和 Web UI 不存在固定端口导入入口或旧身份字段。
- 服务详情完整展示所有主动登记元数据。
- 节点转发能链接到对应服务详情与本机 URL。
- 主节点完整显示从节点清单，但不能修改从节点注册表和端口配置。
- 主节点所有远端信息与用户触发的启停均经 SSH；转发只在主节点保存和运行。
- AutoSSH 断线时显示 reconnecting；SSH config 线路恢复后可重新变为 active。
- 当前 schema 是唯一 schema，不携带迁移兼容栈。
