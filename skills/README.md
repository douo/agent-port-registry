# Agent Skills for APR

| Path | Agent |
|---|---|
| `agent-port-registry/SKILL.md` | All supported Agents |

All Agents use the same first-configuration API and workflow:

```bash
svcctl ensure --json -
```

The Agent first checks whether the service already has a persisted APR port. It
calls `ensure` only for first setup, device moves, or explicit reconfiguration,
then writes the returned port into the service's default startup config. Normal
restarts use that config directly.

Business identity never depends on a specific Agent. `agent.type` is audit
metadata and should be set to the current Agent identifier. Each APR owns only
its node-local registry, so a remote service must be ensured on the remote
node's own APR, never through the master.

## Install to Agent skill directories

For a checkout that will be pulled and updated regularly, point every Agent's
native skill entry at the same canonical directory:

```bash
# From the repository root. Move an existing copied install aside first.
mkdir -p ~/.agents/skills ~/.codex/skills ~/.claude/skills ~/.grok/skills
ln -s "$(pwd)/skills/agent-port-registry" ~/.agents/skills/agent-port-registry
ln -s "$(pwd)/skills/agent-port-registry" ~/.codex/skills/agent-port-registry
ln -s "$(pwd)/skills/agent-port-registry" ~/.claude/skills/agent-port-registry
ln -s "$(pwd)/skills/agent-port-registry" ~/.grok/skills/agent-port-registry
```

After pulling this repository, the linked skill is updated without another
installation. Restart the agent session if it has already cached skill
metadata.

Each link points to the complete canonical directory, so additional scripts,
references, or resources are picked up by every Agent automatically.

For a copy-based install, use `npx skills`:

```bash
# From repo root — installs the canonical skill for the selected Agent
npx skills@latest add ./skills/agent-port-registry -g -a codex -y --copy

# Verify
npx skills@latest list -g -a codex
```
