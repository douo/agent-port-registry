# Agent Skills for APR

| Path | Agent |
|---|---|
| `common/SKILL.md` | Shared rules and workflow |
| `codex/SKILL.md` | Codex（自包含，`agent.type=codex`） |
| `claude-code/SKILL.md` | Claude Code adapter |
| `grok-build/SKILL.md` | Grok Build adapter |

All adapters use the same first-configuration API:

```bash
svcctl ensure --json -
```

The Agent first checks whether the service already has a persisted APR port. It
calls `ensure` only for first setup, device moves, or explicit reconfiguration,
then writes the returned port into the service's default startup config. Normal
restarts use that config directly.

Business identity never depends on a specific Agent. `agent.type` is audit
metadata. Each APR owns only its node-local registry, so a remote service must
be ensured on the remote node's own APR, never through the master.

## Install to Codex global skills (`npx skills`)

```bash
# From repo root — installs to ~/.agents/skills and registers for Codex
npx skills@latest add ./skills/codex -g -a codex -y --copy

# Verify
npx skills@latest list -g -a codex
```

Optional mirror for Codex-native path `$CODEX_HOME/skills`:

```bash
mkdir -p ~/.codex/skills
cp -a ~/.agents/skills/agent-port-registry ~/.codex/skills/
```

Remove:

```bash
npx skills@latest remove agent-port-registry -g -a codex -y
rm -rf ~/.codex/skills/agent-port-registry
```
