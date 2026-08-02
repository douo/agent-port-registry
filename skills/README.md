# Agent Skills for APR

| Path | Agent |
|---|---|
| `common/SKILL.md` | Shared rules and workflow |
| `codex/SKILL.md` | Codex（自包含，`agent.type=codex`） |
| `claude-code/SKILL.md` | Claude Code adapter |
| `grok-build/SKILL.md` | Grok Build adapter |

All adapters call the same CLI:

```bash
svcctl ensure --json -
```

Business logic never depends on a specific Agent; only the injected `agent.type`
(and optional `project_id`) differs.

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
