---
name: agent-port-registry
description: >
  Use before starting or configuring any local service that listens on one or
  more TCP or UDP ports. Requests fixed ports via svcctl ensure (Agent Port Registry).
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

## Example

```bash
cat <<'EOF' | svcctl ensure --json -
{
  "agent": {
    "type": "codex",
    "project_id": "optional-project-id"
  },
  "service": {
    "key": "model-api",
    "instance": "main",
    "name": "Model API",
    "description": "Local model inference API",
    "code_path": "/path/to/project",
    "working_directory": "/path/to/project",
    "start_command": "uv run python -m api --port {{ports.http}}"
  },
  "allocation_name": "default",
  "resources": [
    { "name": "http", "type": "single" },
    { "name": "metrics", "type": "single" }
  ]
}
EOF
```

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
- If `svcctl` / APR returns an error, do not bypass APR to start a formal service.
