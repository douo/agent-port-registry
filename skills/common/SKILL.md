---
name: agent-port-registry
description: >
  Use when developing a new local HTTP/API service, onboarding a third-party
  service for the first time, moving a service to another device, or explicitly
  changing its port configuration. Obtain a fixed port from APR and persist it
  into the service's normal startup configuration. Do not run ensure on every restart.
---

# Agent Port Registry

APR is Agents-first: the Agent configures the service. The service does not need
APR integration and APR does not adapt itself around an already chosen port.

## Decide whether ensure is needed

1. Inspect the service's default startup script, command, environment file, or
   application config.
2. If it already contains the APR-assigned fixed port for this device, do not
   call `ensure`; start the service normally with that persisted configuration.
3. Call `svcctl ensure` only for:
   - first development/configuration of a new service;
   - first onboarding of a third-party service;
   - a device move;
   - a missing or intentionally changed port configuration.

## First-configuration workflow

1. Confirm this Agent is scoped to the node that actually runs the service,
   then identify the project, stable service key and instance.
2. Collect useful metadata: project origin, description, code path, working
   directory, default start/stop commands, health check, and configuration location.
3. Request the required TCP/UDP resources with `svcctl ensure`.
4. Parse the returned ports and verify availability.
5. Write the assigned values into the service's normal source of truth, such as:
   - its default startup script or checked-in development command;
   - `.env` or another local environment file;
   - the third-party application's supported config file;
   - a launch/service definition.
6. Update the registered `start_command` metadata so it describes the same
   default startup path. `{{ports.http}}` placeholders are allowed in APR metadata.
7. Start the service through its normal command, verify its health check, and
   report the persisted config location, service ID, device, and ports.

## Request example

```bash
cat <<'EOF' | svcctl ensure --json -
{
  "agent": { "type": "codex" },
  "service": {
    "key": "model-api",
    "instance": "main",
    "project_id": "model-platform",
    "project_origin": "self-built",
    "name": "Model API",
    "description": "Local model inference API",
    "code_path": "/path/to/project",
    "working_directory": "/path/to/project",
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
```

## Mandatory rules

- Never make `ensure` a dependency of every service start.
- Never choose a formal service port directly or assume a common port is free.
- Persist the returned fixed port before treating first configuration as complete.
- Agent type is audit metadata, not service identity.
- Call `ensure` only on the APR instance local to the service. A master APR must
  never call remote `ensure` or mutate a slave registry.
- Service identity inside one APR is project + service key + instance; the APR
  instance itself defines the node scope.
- A master may read slave data and proxy explicitly requested start/stop through
  SSH, but may not change slave metadata, allocations, config, database, or APR package.
- SSH local forwards belong to the master; a slave is only the routing target.
- A stopped service retains its allocation.
- Release or reconfigure only after an explicit user request.
- If a persisted port is occupied by an unknown process, report the conflict;
  do not silently allocate a replacement.
- Do not create a compatibility or fixed-port import path. Reconfigure the
  service to use its APR-assigned port.
