# Agent Port Registry (APR)

本机端口分配与服务索引工具。Coding Agent（Codex / Claude Code / Grok Build 等）在启动需要监听端口的服务前，通过 `svcctl ensure` 申请**固定且幂等**的端口，并登记服务元数据。

| 文档 | 路径 |
|---|---|
| 产品需求 | `Agent_Port_Registry_Local_PRD_v1.0.md` |
| 架构与选型 | `docs/architecture.md` |
| 实现计划 | `docs/plan.md` |
| 进度 | `docs/progress.md` |
| 验收 | `docs/acceptance.md` |
| Agent Skills | `skills/` |

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
  "agent": { "type": "codex", "project_id": "my-project" },
  "service": {
    "key": "model-api",
    "instance": "main",
    "name": "Model API",
    "description": "本地模型接口",
    "code_path": "/home/you/projects/model-platform",
    "start_command": "uv run python -m api --port {{ports.http}}"
  },
  "allocation_name": "default",
  "resources": [
    { "name": "http", "type": "single" },
    { "name": "metrics", "type": "single" }
  ]
}
EOF

# 人工快捷方式
uv run svcctl ensure --service model-api --port http --name "Model API"
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
| 服务详情 | 端口与占用进程、元数据、`{{ports.x}}` 渲染后的启动命令、分配历史 |
| 端口 | 端口反查、池内未登记的监听进程 |

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
Agent Skill → svcctl CLI → APR Registry (Unix Socket HTTP) → SQLite
```

- 默认端口池：`20000–39999`（可配置）
- 分配算法：First Fit；排除已 Claim 与本机 Listener
- 幂等键：`agent.type + agent.project_id + service.key + instance` + `allocation_name`

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
  start: 20000
  end: 39999
  exclude:
    - 22000
    - 25000-25100
auto_start: true
```

## Agent 集成

见 `skills/`：

- 通用规则：`skills/common/SKILL.md`
- Codex / Claude Code / Grok Build 适配说明

所有 Agent 只调用统一的 `svcctl` 接口。

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
