---
name: agent-port-registry
description: >
  Claude Code adapter for Agent Port Registry. Before starting any local
  listening service, call svcctl ensure. Inject agent.type=claude-code.
---

# Agent Port Registry (Claude Code)

Follow `skills/common/SKILL.md` fully.

## Claude Code-specific

- Always set `"agent": { "type": "claude-code", "project_id": "<project-if-known>" }`.
- `project_id` is optional.
- Use stable `service.key` + `instance`.

## Install

```bash
# Example global skills location (adjust to your Claude Code setup)
mkdir -p ~/.claude/skills/agent-port-registry
cp skills/common/SKILL.md ~/.claude/skills/agent-port-registry/SKILL.md
```

Or install as a project skill under `.claude/skills/` when preferred.
