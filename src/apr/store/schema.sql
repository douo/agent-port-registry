-- Agent Port Registry's one current schema.

PRAGMA foreign_keys = ON;

-- A device is the port-allocation scope.  SSH settings are optional because
-- the local device has no SSH control path.
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL DEFAULT 'remote',
    ssh_host TEXT NULL,
    ssh_user TEXT NULL,
    ssh_port INTEGER NULL,
    identity_file TEXT NULL,
    ssh_config_managed INTEGER NOT NULL DEFAULT 1,
    apr_command TEXT NOT NULL DEFAULT 'svcctl',
    enabled INTEGER NOT NULL DEFAULT 1,
    refresh_interval_seconds INTEGER NOT NULL DEFAULT 30,
    last_seen_at TEXT NULL,
    last_error TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

INSERT OR IGNORE INTO nodes (
    id, name, kind, ssh_config_managed, enabled,
    refresh_interval_seconds, created_at, updated_at
) VALUES (
    'NODE_LOCAL', '本机', 'local', 1, 1, 30,
    strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
    strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
);

-- One row describes one configured deployment on one device.  Agent is the
-- latest actor and deliberately not part of the unique identity.
CREATE TABLE IF NOT EXISTS services (
    id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    project_id TEXT NULL,
    project_key TEXT NOT NULL,
    service_key TEXT NOT NULL,
    instance_key TEXT NOT NULL DEFAULT 'default',
    registered_by_agent TEXT NULL,
    project_origin TEXT NULL,
    name TEXT NOT NULL,
    description TEXT NULL,
    code_path TEXT NULL,
    working_directory TEXT NULL,
    start_command TEXT NULL,
    stop_command TEXT NULL,
    health_check TEXT NULL,
    configuration TEXT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (device_id) REFERENCES nodes(id),
    UNIQUE (device_id, project_key, service_key, instance_key)
);

CREATE TABLE IF NOT EXISTS allocations (
    id TEXT PRIMARY KEY,
    service_id TEXT NOT NULL,
    allocation_name TEXT NOT NULL DEFAULT 'default',
    request_spec_json TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'reserved',
    sticky INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    released_at TEXT NULL,
    release_reason TEXT NULL,
    FOREIGN KEY (service_id) REFERENCES services(id) ON DELETE CASCADE,
    UNIQUE(service_id, allocation_name)
);

CREATE TABLE IF NOT EXISTS allocated_ports (
    allocation_id TEXT NOT NULL,
    resource_name TEXT NOT NULL,
    port_name TEXT NULL,
    port INTEGER NOT NULL,
    transport TEXT NOT NULL DEFAULT 'tcp',
    ordinal INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (allocation_id) REFERENCES allocations(id) ON DELETE CASCADE,
    PRIMARY KEY (allocation_id, resource_name, ordinal)
);

-- A port claim is unique only inside one device and transport namespace.
CREATE TABLE IF NOT EXISTS active_port_claims (
    device_id TEXT NOT NULL,
    transport TEXT NOT NULL DEFAULT 'tcp',
    port INTEGER NOT NULL,
    allocation_id TEXT NOT NULL,
    resource_name TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    FOREIGN KEY (device_id) REFERENCES nodes(id),
    FOREIGN KEY (allocation_id) REFERENCES allocations(id) ON DELETE CASCADE,
    PRIMARY KEY (device_id, transport, port)
);

-- Remote observations are a cache only; centrally registered services above
-- remain the allocation authority.
CREATE TABLE IF NOT EXISTS node_snapshots (
    node_id TEXT PRIMARY KEY,
    fetched_at TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NULL,
    error TEXT NULL,
    duration_ms INTEGER NULL,
    FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS port_forwards (
    id TEXT PRIMARY KEY,
    node_id TEXT NOT NULL,
    remote_port INTEGER NOT NULL,
    remote_host TEXT NOT NULL DEFAULT '127.0.0.1',
    local_port INTEGER NOT NULL,
    label TEXT NULL,
    pid INTEGER NULL,
    state TEXT NOT NULL DEFAULT 'starting',
    last_error TEXT NULL,
    auto_reconnect INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    started_at TEXT NULL,
    stopped_at TEXT NULL,
    FOREIGN KEY (node_id) REFERENCES nodes(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_port_forwards_live_local
    ON port_forwards(local_port)
    WHERE state IN ('starting', 'active', 'reconnecting');

CREATE INDEX IF NOT EXISTS idx_port_forwards_node
    ON port_forwards(node_id);

CREATE TABLE IF NOT EXISTS managed_processes (
    id TEXT PRIMARY KEY,
    service_id TEXT NOT NULL,
    allocation_id TEXT NULL,
    command TEXT NOT NULL,
    working_directory TEXT NULL,
    pid INTEGER NULL,
    state TEXT NOT NULL DEFAULT 'starting',
    exit_code INTEGER NULL,
    log_path TEXT NULL,
    last_error TEXT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT NULL,
    stopped_at TEXT NULL,
    FOREIGN KEY (service_id) REFERENCES services(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_managed_processes_live
    ON managed_processes(service_id)
    WHERE state IN ('starting', 'running');

CREATE INDEX IF NOT EXISTS idx_managed_processes_service
    ON managed_processes(service_id);

CREATE INDEX IF NOT EXISTS idx_allocations_service
    ON allocations(service_id);

CREATE INDEX IF NOT EXISTS idx_allocated_ports_port
    ON allocated_ports(port);

CREATE INDEX IF NOT EXISTS idx_services_search
    ON services(device_id, project_key, service_key, name);
