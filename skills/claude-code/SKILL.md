---
name: agent-port-registry
description: >
  Configure a new or newly onboarded local HTTP/API service with an APR-assigned
  fixed port and persist it into the default startup configuration. For Claude
  Code, set agent.type=claude-code. Do not call ensure on every restart.
---

# Agent Port Registry for Claude Code

Follow `../common/SKILL.md` fully and set `"agent": { "type": "claude-code" }`.
Project belongs in `service.project_id`. Run ensure on the target machine's own
APR; never allocate or register a slave service through a master APR.
After first-time ensure, write the returned port into the service's normal
startup config. Ordinary starts use that persisted value without another ensure.
