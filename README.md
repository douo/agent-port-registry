# Agent Port Registry (APR)

Agents-first 的本地 HTTP/API 服务端口与服务索引。Agent 在新服务开发、第三方服务首次接入、设备迁移或显式重配置时，通过 `svcctl ensure` 取得固定端口，并把端口写进服务的默认启动脚本、命令、环境变量或配置文件。日常重启直接使用已持久化配置，不依赖 APR。

| 文档 | 路径 |
|---|---|
| 产品需求 | `docs/PRD.md` |
| 架构与选型 | `docs/architecture.md` |
| 领域上下文与权限 | `CONTEXT.md` |
| 实现计划 | `docs/plan.md` |
| 验收 | `docs/acceptance.md` |
| Agent Skills | `skills/` |

本地交接 / 进度笔记（`docs/HANDOFF.md`、`docs/progress.md`）不入库，仅本机保留。

## 安装

需要 Python 3.12+ 与 [uv](https://github.com/astral-sh/uv)。

```bash
cd agent-port-registry
uv sync
```

```bash
uv run svcctl --help
# 或
uv run python -m apr --help
```

可选：将 venv 的 `svcctl` 加入 PATH，或 `uv tool install -e .`。

## 登录自启（推荐）

配置与 unit 均遵循 **XDG Base Directory**（Linux 上的用户级默认路径）：

| 用途 | 路径 |
|---|---|
| 配置 | `~/.config/apr/config.yaml`（`$XDG_CONFIG_HOME/apr/`） |
| 数据 / Socket / DB | `~/.local/share/apr/`（`$XDG_DATA_HOME/apr/`） |
| 日志 / PID（非 systemd 时） | `~/.local/state/apr/`（`$XDG_STATE_HOME/apr/`） |
| systemd user unit | `~/.config/systemd/user/apr.service` |

```bash
# 写入 ~/.config/apr/config.yaml，安装并启用 systemd --user 服务
uv run svcctl user-service install

# 查看状态
uv run svcctl user-service status
uv run svcctl status

# 日志
journalctl --user -u apr.service -f

# 卸载自启（可选：--remove-config）
uv run svcctl user-service uninstall
```

登录后由 `systemd --user` 自动拉起 APR（`WantedBy=default.target`）。

## 快速开始（手动）

```bash
# 启动 Registry（默认 Unix Socket: ~/.local/share/apr/apr.sock）
uv run svcctl serve --daemon
uv run svcctl status

# Agent / 脚本标准调用
cat <<'EOF' | uv run svcctl ensure --json -
{
  "agent": { "type": "codex" },
  "service": {
    "key": "model-api",
    "instance": "main",
    "project_id": "my-project",
    "project_origin": "self-built",
    "name": "Model API",
    "description": "本地模型接口",
    "code_path": "/home/you/projects/model-platform",
    "start_command": "./scripts/start --port {{ports.http}}",
    "stop_command": "./scripts/stop",
    "health_check": "http://127.0.0.1:{{ports.http}}/healthz",
    "configuration": ".env.local: MODEL_API_PORT"
  },
  "allocation_name": "default",
  "resources": [
    { "name": "http", "type": "single", "transport": "tcp" },
    { "name": "metrics", "type": "single", "transport": "tcp" }
  ]
}
EOF

# 首次配置快捷方式；拿到端口后必须写入服务默认配置
uv run svcctl ensure --service model-api --project my-project --port http --name "Model API"
uv run svcctl ensure --service workers --block workers=8
uv run svcctl ensure --service model-api --ports http,metrics,debug

# 查询
uv run svcctl list --table
uv run svcctl search "模型"
uv run svcctl inspect-port 20104
uv run svcctl check <service_id|alloc_id>

# 释放端口 Claim（保留历史；需确认或 --yes）
svcctl release <allocation_id> --yes --reason "service removed"
# 或
svcctl allocation release <allocation_id> --yes

# 彻底删除（无历史）
svcctl service delete <service_id> --yes --reason "cleanup"
svcctl allocation delete <allocation_id> --yes
svcctl delete <svc_id|alloc_id> --yes   # 按 id 前缀自动选择

# Service CRUD
svcctl service create --service demo --name "Demo" --agent codex
svcctl service list
svcctl service get <service_id>
svcctl service update <service_id> --description "新说明"
svcctl service delete <service_id> --yes

# Allocation
svcctl allocation get <allocation_id>
svcctl ensure ...   # 创建/幂等分配端口

# 备份
svcctl backup /tmp/apr-backup.db
```

CLI 在 Registry 未启动且 `auto_start=true`（默认）时会尝试后台拉起 `svcctl serve --daemon`。

## Web UI

```bash
# 临时开启
uv run svcctl serve --web

# 常驻开启：写入 ~/.config/apr/config.yaml 后重启
#   web:
#     enabled: true
systemctl --user restart apr.service
```

打开 <http://127.0.0.1:17989>。

开启后 Registry **同时**绑定两个传输：CLI 继续走 Unix socket，浏览器走 `127.0.0.1` TCP。
TCP 只绑回环，不要暴露到对外网卡（APR 没有鉴权，安全模型依赖本机文件权限）。

界面包含：

| 视图 | 内容 |
|---|---|
| 概览 | KPI、端口池占用图、按项目分布、已分配但无监听的端口 |
| 服务 | 过滤 / 排序 / 实时监听状态 |
| 服务详情 | 端口与占用进程、启动/停止/健康检查/配置位置、控制台、分配历史 |
| 端口 | 端口反查、池内未登记的监听进程 |
| 节点 | 中心登记的设备、节点服务详情、AutoSSH 转发及服务直达链接 |

`⌘K` / `Ctrl+K` 打开命令面板。

### 前端开发

终端用户**不需要 Node** —— 构建产物 `src/apr/webui/static/` 已提交进仓库。
只有修改界面时才需要：

```bash
cd web
npm install
npm run dev     # http://localhost:5273，API 自动代理到 127.0.0.1:17989
npm run build   # 产物写回 src/apr/webui/static/，需一并提交
```

## 架构摘要

```text
目标节点 Agent → 首次 ensure → 目标节点本地 APR
             → 写服务默认配置 → 后续正常启动

主节点 Web UI ──SSH 只读──> 从节点服务注册表
主节点 Web UI ──SSH 代理──> 用户触发的远端 start/stop/status/logs
主节点 APR   ──本机拥有──> SSH/AutoSSH 本机端口转发
```

- 默认端口池：`41000–45999`（避开常见开发端口与现有手工转发）
- 分配算法：First Fit；排除已 Claim 与本机 Listener
- 每个 APR 数据库只管理所在节点的服务和端口
- 服务身份：`service.project_id + service.key + instance`；节点由 APR 实例天然确定
- Agent 类型只记录“由谁登记”，不参与身份
- 主节点不得修改从节点服务注册表、端口、配置或 APR 程序

详见 `docs/architecture.md`。

## 配置

| 用途 | 默认路径 |
|---|---|
| 数据 / DB / Socket | `~/.local/share/apr/` |
| 配置 | `~/.config/apr/config.yaml` |
| 日志 / PID（serve 默认与 data 隔离时见 `data_dir/state/`） | `~/.local/state/apr/` |

环境变量：`APR_DATA_DIR`、`APR_SOCKET`、`APR_DB`、`APR_CONFIG`、`APR_USE_TCP`、`APR_HTTP_PORT`、`APR_AUTO_START`、`APR_WEB`。

```yaml
# ~/.config/apr/config.yaml
web:
  enabled: true       # 浏览器 UI，绑定 127.0.0.1:17989
port_pool:
  start: 41000
  end: 45999
  exclude:
    - 22000
    - 25000-25100
auto_start: true
```

## Agent 集成

见 `skills/`：

- 通用规则：`skills/common/SKILL.md`
- Codex / Claude Code / Grok Build 适配说明

所有 Agent 只调用统一的 `svcctl` 接口。`ensure` 是首次配置与重配置操作，不是每次启动的前置条件。

### 安装到 Codex 全局技能

```bash
npx skills@latest add ./skills/codex -g -a codex -y --copy
npx skills@latest list -g -a codex
```

技能目录：`~/.agents/skills/agent-port-registry`（并已镜像到 `~/.codex/skills/agent-port-registry`）。

## 开发与测试

```bash
uv sync
uv run pytest -q
```

## 许可证

MIT
