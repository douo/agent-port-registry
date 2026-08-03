---
name: agent-port-registry
description: >
  Configure a new or newly onboarded local HTTP/API service with an APR-assigned
  fixed port and persist it into the default startup configuration. For Codex,
  set agent.type=codex. Do not call ensure on every restart.
---

# Agent Port Registry for Codex

Follow the Agents-first workflow in `../common/SKILL.md`.

- Set `"agent": { "type": "codex" }`.
- Put the project identifier in `service.project_id`, not in Agent context.
- Run `svcctl ensure` on the same node that will run the service. Do not use a
  master APR to allocate or register a slave service.
- Use a stable `service.key` and `instance`.
- On first setup, call `svcctl ensure`, then edit the service's default startup
  script, command, env, or config to persist the returned port.
- On ordinary restarts, detect and use that persisted configuration directly;
  do not call `ensure` again solely because the service is starting.
- Register description, code path, working directory, start/stop commands,
  health check, project origin, and configuration location when known.
- When operating a master, remote access is limited to SSH read operations and
  explicitly requested start/stop of existing services. Never mutate a slave
  registry, allocation, config, database, port, or APR package.
