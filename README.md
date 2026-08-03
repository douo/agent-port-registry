# Agent Port Registry (APR)

**Agent-first 的本地 HTTP/API 服务注册表与固定端口分配器。** APR 的首要使用者是
Coding Agent：Agent 在开发新服务、首次接入第三方服务、迁移设备或显式重配置时，
向目标设备本地的 APR 申请端口，登记服务元数据，再把端口写进项目的正常启动脚本、
命令、环境变量或配置文件。

```text
目标节点上的 Agent ──ensure──> 目标节点本地 APR ──返回固定端口──> Agent
        Agent ──写入默认配置──> 服务后续直接按该配置启动，不再依赖 APR
```

APR 不是“每次启动前都必须调用”的中央端口服务，也不会擅自修改第三方项目文件。
端口只在首次配置或明确重配置时分配；持久化端口和适配服务配置是 Agent 的职责。

## 为什么是 Agent-first

- **Agent 主动登记**：服务描述、项目来源、代码路径、工作目录、启动/停止命令、
  健康检查和配置位置都随 `ensure` 一次登记。
- **固定且幂等**：相同项目、服务、实例和 allocation 重复 `ensure` 返回原端口；
  规格变化不会静默替换已有端口。
- **节点本地权威**：每台设备的 APR 只管理该设备本地服务、端口和进程。
- **适配自研与第三方服务**：自研项目可改默认开发脚本；第三方开源项目优先使用其
  官方 env、配置文件或启动参数，尽量不改源码。
- **人可见、Agent 可调用**：`svcctl` 提供稳定 JSON/CLI，Web UI 提供相同的服务、
  端口、控制台、节点和转发视图。

## 能力概览

| 能力 | 说明 |
|---|---|
| 固定端口 | TCP/UDP 单端口、多个命名端口、连续端口块；默认池 `41000–45999` |
| 服务索引 | 项目、来源、描述、路径、启动/停止命令、健康检查、配置位置和登记 Agent |
| 本地进程 | 可选的 start/stop/status/logs；`{{ports.http}}` 等占位符会替换为已分配端口 |
| Web UI | 服务详情、实时监听、控制台、分配历史、节点详情及本机转发直达链接 |
| SSH 节点 | 主节点通过 SSH 查看从节点完整服务信息，并代理用户明确触发的启停与日志操作 |
| 本机转发 | 主节点管理 SSH/AutoSSH 本地端口转发；断线时显示 `reconnecting` 并自动恢复 |

## 主从节点权限边界

从节点始终是自身服务数据的唯一权威。主节点提供聚合视图，但不拥有从节点的服务。

| 操作 | 主节点 | 目标节点本地 APR / Agent |
|---|---|---|
| 列表、详情、状态、日志 | 通过 SSH 读取 | 权威数据源 |
| 已登记服务 start/stop | 用户明确触发后通过 SSH 代理 | 实际执行并记录 |
| `ensure`、端口分配 | 不得替从节点执行 | Agent 在目标节点本地执行 |
| 服务 CRUD、release | 不得修改从节点 | 只修改本节点注册表 |
| SSH 本地转发 | 在主节点创建、启动和停止 | 从节点只是目标，不保存转发记录 |

主节点不会把从节点快照转换成本机 Service/Allocation，也不会远程改写从节点端口、
启动命令、配置、数据库或 APR 程序。

## 系统要求

- Python 3.12+
- [uv](https://github.com/astral-sh/uv)
- OpenSSH（使用远端节点时）
- AutoSSH（需要持续自动重连的本机转发时，可选）
- Node.js 只在修改 Web 前端时需要；仓库已包含构建产物

## 安装

```bash
git clone git@github.com:douo/agent-port-registry.git
cd agent-port-registry
uv sync
uv run svcctl --help
```

在仓库外长期调用时，可选择安装到用户工具目录：

```bash
uv tool install -e .
svcctl --help
```

下面的示例统一使用 `uv run svcctl`。如果已经安装为工具，可直接替换成 `svcctl`。

## 通用配置与数据初始化

macOS 和 Linux 使用相同的 XDG 风格路径：

| 用途 | 默认路径 |
|---|---|
| 配置 | `~/.config/apr/config.yaml` |
| 数据库、Unix Socket | `~/.local/share/apr/` |
| 日志、PID、转发日志 | `~/.local/state/apr/` |

先生成默认配置，再按需编辑：

```bash
uv run svcctl user-service write-config
$EDITOR ~/.config/apr/config.yaml
```

推荐的个人设备配置：

```yaml
use_unix_socket: true
# CLI 在 APR 不可达时是否尝试启动 APR 自身；不是服务级自启动。
auto_start: true

web:
  enabled: true
  host: 127.0.0.1
  port: 17989

# 允许 APR 执行登记过的 start_command。默认关闭；只应在可信个人设备开启。
process_management:
  enabled: false
  stop_timeout_seconds: 10
  user_shell_env: true

port_pool:
  start: 41000
  end: 45999
  exclude: []
```

APR 不需要单独的建库或迁移命令。第一次启动会自动创建私有目录、SQLite 数据库、
当前 schema 和 Unix Socket；后续启动直接复用已有数据。

### macOS 初始化

macOS 没有 `systemd --user`，先使用内置后台模式启动：

```bash
uv run svcctl user-service write-config
$EDITOR ~/.config/apr/config.yaml
uv run svcctl serve --daemon
uv run svcctl status
open http://127.0.0.1:17989
```

排查日志与停止进程：

```bash
tail -f ~/.local/state/apr/apr.log
kill "$(cat ~/.local/state/apr/apr.pid)"
```

需要登录自启时，建议先执行 `uv tool install -e .`，然后创建
`~/Library/LaunchAgents/io.github.douo.apr.plist`。`ProgramArguments` 中必须使用
`command -v svcctl` 返回的绝对路径；launchd 下应以前台模式运行：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>io.github.douo.apr</string>
  <key>ProgramArguments</key>
  <array>
    <string>/ABSOLUTE/PATH/TO/svcctl</string>
    <string>serve</string>
    <string>--foreground</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
</dict>
</plist>
```

```bash
plutil -lint ~/Library/LaunchAgents/io.github.douo.apr.plist
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/io.github.douo.apr.plist
launchctl kickstart -k "gui/$(id -u)/io.github.douo.apr"
uv run svcctl status
```

当前 CLI 不自动安装 launchd plist；上述配置显式保留可审计的绝对执行路径。

### Linux 初始化

使用 systemd 的桌面或服务器发行版，推荐安装用户级 unit：

```bash
# 写配置与 unit、登录自启，但先不启动，便于首次编辑配置
uv run svcctl user-service install --no-start
$EDITOR ~/.config/apr/config.yaml

systemctl --user start apr.service
uv run svcctl user-service status
uv run svcctl status
journalctl --user -u apr.service -f
```

`apr.service` 会在用户登录后启动。若发行版没有 systemd user session，可使用和
macOS 相同的通用后台模式：

```bash
uv run svcctl serve --daemon
uv run svcctl status
tail -f ~/.local/state/apr/apr.log
```

## Agent 首次接入服务

简洁调用：

```bash
uv run svcctl ensure \
  --agent codex \
  --project model-platform \
  --service model-api \
  --name "Model API" \
  --project-origin self-built \
  --code-path "$PWD" \
  --working-directory "$PWD" \
  --start-command './scripts/start --port {{ports.http}}' \
  --health-check 'http://127.0.0.1:{{ports.http}}/healthz' \
  --configuration '.env.local: MODEL_API_PORT' \
  --port http
```

完整 JSON 调用适合 Agent 和自动化工具：

```bash
cat <<'EOF' | uv run svcctl ensure --json -
{
  "agent": { "type": "codex" },
  "service": {
    "key": "model-api",
    "instance": "main",
    "project_id": "model-platform",
    "project_origin": "self-built",
    "name": "Model API",
    "description": "本地模型 HTTP API",
    "code_path": "/absolute/path/to/model-platform",
    "working_directory": "/absolute/path/to/model-platform",
    "start_command": "./scripts/start --port {{ports.http}}",
    "stop_command": "./scripts/stop",
    "health_check": "http://127.0.0.1:{{ports.http}}/healthz",
    "auto_start": true,
    "configuration": ".env.local: MODEL_API_PORT"
  },
  "allocation_name": "default",
  "resources": [
    { "name": "http", "type": "single", "transport": "tcp" },
    { "name": "metrics", "type": "single", "transport": "tcp" }
  ]
}
EOF
```

Agent 收到 `ports` 后必须把值写入该服务认可的持久化配置，并验证启动和健康检查。
普通日常启动只读取这份配置，**不要在每次启动前重复 `ensure`**。

常用资源形式：

```bash
uv run svcctl ensure --service api --project demo --port http
uv run svcctl ensure --service api --project demo --ports http,metrics,debug
uv run svcctl ensure --service workers --project demo --block workers=8
```

## 查询与本地运行控制

```bash
uv run svcctl list --table
uv run svcctl search "模型"
uv run svcctl inspect-service <service_id>
uv run svcctl inspect-port 41000
uv run svcctl check <service_id|allocation_id>
uv run svcctl check-all

# process_management.enabled=true 后可用
uv run svcctl process start <service_id>
uv run svcctl process status <service_id>
uv run svcctl process logs <service_id> --tail 200
uv run svcctl process stop <service_id>

# 配置单个服务随本机 APR 启动；关闭使用 --no-auto-start
uv run svcctl service update <service_id> --auto-start
```

服务详情与 `svcctl process status` 同时返回 `process` 和 `runtime`。`process` 只表示
APR 启动并管理的进程；`runtime.source=external` 表示 APR 在该服务已分配的 TCP
端口上发现了外部 Listener。外部进程会阻止重复启动，但 APR 不会停止或接管它。
没有已分配 TCP 端口的外部进程无法可靠识别，状态会保持 `unknown`，自动启动也会
保守跳过；用户仍可显式执行 `process start`。

释放端口 Claim 会保留历史；彻底删除才移除记录：

```bash
uv run svcctl release <allocation_id> --yes --reason "service removed"
uv run svcctl service delete <service_id> --yes --reason "cleanup"
uv run svcctl backup /tmp/apr-backup.db
```

## Web UI

配置 `web.enabled: true` 后重启 APR，打开 <http://127.0.0.1:17989>。临时前台启动也可：

```bash
uv run svcctl serve --web
```

浏览器 API 只绑定 `127.0.0.1`；CLI 同时继续使用 Unix Socket。APR 当前没有 Web
鉴权，不要把 HTTP 监听暴露到外部网卡。

界面包含：

- 概览、端口池占用、项目和 Agent 分布；
- 本地服务列表、详情、启动/停止、健康检查、控制台、日志和分配历史；
- 从节点完整服务列表及与本地服务一致的详情视图；
- 主节点本机拥有的 SSH/AutoSSH 转发、状态、重启和服务直达链接。

`⌘K` / `Ctrl+K` 打开命令面板。

## SSH 节点与 AutoSSH

主节点通过 SSH 调用从节点已有的 `svcctl`。推荐先在 `~/.ssh/config` 中定义别名，
并让节点保持默认的 `ssh_config_managed=true`：

```sshconfig
Host p44
  HostName 192.0.2.44
  User tiou
  IdentityFile ~/.ssh/id_ed25519
  # Match、ProxyJump 等网络切换规则也继续由 OpenSSH 处理
```

此模式下 APR 只执行 `ssh p44 -- ...`，不会追加 user、`-p` 或 `-i` 覆盖 SSH config。
网络环境变化后，OpenSSH 重新解析相同别名；AutoSSH 在连接中断时保持
`reconnecting`，线路恢复后重新监听原本机端口。

端口转发始终属于主节点本机。节点 ID 只用于确定 SSH 路由和远端端口，转发记录、
本机监听端口及 AutoSSH 进程都不会写入从节点 APR。

节点详情可以添加、启动、停止、配置自启动和移除转发规则。启停只控制当前运行状态，
不改变自启动配置；APR 启动时只拉起开启自启动的规则。当前应运行的规则在 AutoSSH
父进程异常退出后仍会在原本机端口重建。转发只判断 SSH 主机连接和本机监听，不探测
目标服务端口，远端服务可以由用户独立启停。`forward-only` 主机只是 SSH 目标，不会
被当作运行 APR 的从节点或远程服务管理入口。

## 环境变量

常用覆盖项：

`APR_DATA_DIR`、`APR_STATE_DIR`、`APR_SOCKET`、`APR_DB`、`APR_CONFIG`、
`APR_USE_TCP`、`APR_HTTP_HOST`、`APR_HTTP_PORT`、`APR_AUTO_START`、`APR_WEB`、
`APR_PROCESS_MANAGEMENT`、`APR_PROCESS_USER_SHELL`。

环境变量优先于配置文件。CLI 在 Registry 未启动且 `auto_start=true` 时会尝试拉起
`svcctl serve --daemon`。

## Agent 集成

`skills/` 提供统一 APR 工作流及 Codex、Claude Code、Grok Build 适配说明：

```bash
npx skills@latest add ./skills/codex -g -a codex -y --copy
npx skills@latest list -g -a codex
```

所有 Agent 都遵守同一原则：在目标节点本地 ensure、持久化端口、不替远端节点
修改服务注册表。

## 开发与测试

```bash
uv sync
uv run pytest -q

cd web
npm install
npm run dev
npm run build
```

前端生产构建写入 `src/apr/webui/static/`，提交前需一并纳入版本控制。

## 文档

| 文档 | 路径 |
|---|---|
| 领域上下文与权限 | [`CONTEXT.md`](CONTEXT.md) |
| 产品需求 | [`docs/PRD.md`](docs/PRD.md) |
| 架构与选型 | [`docs/architecture.md`](docs/architecture.md) |
| 实现计划 | [`docs/plan.md`](docs/plan.md) |
| 验收标准 | [`docs/acceptance.md`](docs/acceptance.md) |
| Agent Skills | [`skills/`](skills/) |

## License

MIT
