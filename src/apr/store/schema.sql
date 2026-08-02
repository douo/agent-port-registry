-- Agent Port Registry schema (PRD §14)
-- Applied idempotently by store/db.py

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS services (
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

    FOREIGN KEY (service_id) REFERENCES services(id),
    UNIQUE(service_id, allocation_name)
);

CREATE TABLE IF NOT EXISTS allocated_ports (
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

CREATE TABLE IF NOT EXISTS active_port_claims (
    port INTEGER PRIMARY KEY,
    allocation_id TEXT NOT NULL,
    resource_name TEXT NOT NULL,
    ordinal INTEGER NOT NULL,

    FOREIGN KEY (allocation_id) REFERENCES allocations(id)
);

CREATE INDEX IF NOT EXISTS idx_allocations_service
    ON allocations(service_id);

CREATE INDEX IF NOT EXISTS idx_allocated_ports_port
    ON allocated_ports(port);

CREATE INDEX IF NOT EXISTS idx_services_search
    ON services(service_key, name, agent_type_key);
