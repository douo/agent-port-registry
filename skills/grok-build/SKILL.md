---
name: agent-port-registry
description: >
  Configure a new or newly onboarded local HTTP/API service with an APR-assigned
  fixed port and persist it into the default startup configuration. For Grok
  Build, set agent.type=grok-build. Do not call ensure on every restart.
---

# Agent Port Registry for Grok Build

Follow `../common/SKILL.md` fully and set `"agent": { "type": "grok-build" }`.
Project belongs in `service.project_id`. Run ensure on the target machine's own
APR; never allocate or register a slave service through a master APR.
After first-time ensure, write the returned port into the service's normal
startup config. Ordinary starts use that persisted value without another ensure.
