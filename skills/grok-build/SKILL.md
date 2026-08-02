---
name: agent-port-registry
description: >
  Grok Build adapter for Agent Port Registry. Before starting any local
  listening service, call svcctl ensure. Inject agent.type=grok-build.
---

# Agent Port Registry (Grok Build)

Follow `skills/common/SKILL.md` fully.

## Grok Build-specific

- Always set `"agent": { "type": "grok-build", "project_id": "<workspace-if-known>" }`.
- `project_id` is optional.
- Use stable `service.key` + `instance`.

## Install

```bash
# User skills directory (Grok Build / agents)
mkdir -p ~/.agents/skills/agent-port-registry
cp skills/common/SKILL.md ~/.agents/skills/agent-port-registry/SKILL.md

# Or project-local
mkdir -p .grok/skills/agent-port-registry
cp skills/common/SKILL.md .grok/skills/agent-port-registry/SKILL.md
```

Ensure `svcctl` is on `PATH` (`uv tool install` / `uv sync` + venv activate).
