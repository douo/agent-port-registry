# Agent instructions

Before changing APR code or operating a node, read `CONTEXT.md` and
`docs/architecture.md`.

## Non-negotiable master/slave authority

- Every APR instance owns only the services and allocations local to that node.
- A master reads slave service list/detail/status/logs through SSH.
- A master may proxy start/stop only for an already registered slave service and
  only when the user explicitly triggers that runtime action.
- Never use the master to run remote `ensure`, service CRUD, allocation release,
  database writes, package upgrades, config edits, or port rewrites on a slave.
- A slave's registry may be changed only by an Agent scoped to that slave or by
  explicit user-authorized maintenance of that exact node.
- SSH local forwards are owned by the master. A slave node is only the target;
  never store or manage the forward in the slave APR.
- Never interpret removal of compatibility code as permission to delete,
  rebuild, or migrate existing node data.
