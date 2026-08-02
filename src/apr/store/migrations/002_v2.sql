-- APR v2 迁移：主从节点、端口转发、服务进程管理
-- 由 store/db.py 依据 schema_version 增量应用（事务内 bump 版本）
--
-- 设计要点：
--   从节点的服务数据以 JSON 快照存入 node_snapshots，不并入 services 表。
--   services 表的语义保持不变 —— 始终只描述本机服务。
--   这样跨机 id 不会冲突，从节点也始终是自身数据的唯一权威。

-- ---------------------------------------------------------------------------
-- nodes：从节点定义（主节点侧持有）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,

    -- local = 本机自身；remote = 经 SSH 访问的从节点
    kind TEXT NOT NULL DEFAULT 'remote',

    -- SSH 连接参数（kind='local' 时全部为 NULL）
    ssh_host TEXT NULL,
    ssh_user TEXT NULL,
    ssh_port INTEGER NULL,
    identity_file TEXT NULL,

    -- 从节点上 svcctl 的调用方式（可能是绝对路径或 uv run svcctl）
    apr_command TEXT NOT NULL DEFAULT 'svcctl',

    enabled INTEGER NOT NULL DEFAULT 1,
    refresh_interval_seconds INTEGER NOT NULL DEFAULT 30,

    last_seen_at TEXT NULL,
    last_error TEXT NULL,

    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- node_snapshots：从节点状态快照（每节点一行，覆盖写）
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS node_snapshots (
    node_id TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,

    -- ok | error
    status TEXT NOT NULL,

    -- 从节点 `svcctl list --json` 的原文，主节点不做 schema 假设
    payload_json TEXT NULL,
    error TEXT NULL,
    duration_ms INTEGER NULL,

    FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE CASCADE
);

-- ---------------------------------------------------------------------------
-- port_forwards：ssh -N -L 转发实例
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS port_forwards (
    id TEXT PRIMARY KEY,
    node_id TEXT NOT NULL,

    remote_port INTEGER NOT NULL,
    remote_host TEXT NOT NULL DEFAULT '127.0.0.1',
    local_port INTEGER NOT NULL,

    -- 展示用：来源服务名 / 端口名
    label TEXT NULL,

    pid INTEGER NULL,
    -- starting | active | stopped | failed
    state TEXT NOT NULL DEFAULT 'starting',
    last_error TEXT NULL,

    auto_reconnect INTEGER NOT NULL DEFAULT 1,

    created_at TEXT NOT NULL,
    started_at TEXT NULL,
    stopped_at TEXT NULL,

    FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE CASCADE
);

-- 同一本地端口同时只能有一个存活转发；已停止的历史行不受限
CREATE UNIQUE INDEX IF NOT EXISTS idx_port_forwards_live_local
    ON port_forwards(local_port)
    WHERE state IN ('starting', 'active');

CREATE INDEX IF NOT EXISTS idx_port_forwards_node
    ON port_forwards(node_id);

-- ---------------------------------------------------------------------------
-- managed_processes：由 APR 拉起的服务进程
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS managed_processes (
    id TEXT PRIMARY KEY,
    service_id TEXT NOT NULL,
    allocation_id TEXT NULL,

    -- 渲染掉 {{ports.x}} 占位符之后的实际命令
    command TEXT NOT NULL,
    working_directory TEXT NULL,

    pid INTEGER NULL,
    -- starting | running | stopped | failed | exited
    state TEXT NOT NULL DEFAULT 'starting',
    exit_code INTEGER NULL,
    log_path TEXT NULL,
    last_error TEXT NULL,

    created_at TEXT NOT NULL,
    started_at TEXT NULL,
    stopped_at TEXT NULL,

    FOREIGN KEY (service_id) REFERENCES services(id) ON DELETE CASCADE
);

-- 同一服务同时只能有一个存活进程
CREATE UNIQUE INDEX IF NOT EXISTS idx_managed_processes_live
    ON managed_processes(service_id)
    WHERE state IN ('starting', 'running');

CREATE INDEX IF NOT EXISTS idx_managed_processes_service
    ON managed_processes(service_id);
