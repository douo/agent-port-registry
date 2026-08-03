# APR 验收清单

## Agents-first

- [x] Agent 不参与服务身份。
- [x] project 位于 Service，不位于 Agent context。
- [x] ensure 只能修改当前节点，拒绝 target remote device。
- [x] Agent 指引明确：首次配置后持久化，后续启动不重复 ensure。
- [x] 不存在固定端口导入入口。

## 分配与数据

- [x] ensure 幂等。
- [x] 多资源原子分配。
- [x] 当前节点内端口唯一；不同 APR 实例天然隔离。
- [x] TCP/UDP 协议记录完整。
- [x] 显式 release 保留历史，删除服务级联清理。
- [x] 唯一当前 schema，无迁移兼容栈。

## 服务与 Web UI

- [x] 主节点通过 SSH 完整显示从节点服务列表，不复制到本地服务表。
- [x] 详情显示端口、路径、启动/停止、健康检查和配置位置。
- [x] 本机服务支持进程状态、控制台和日志。
- [x] 节点服务 item 显示转发、本机 URL 和详情链接。
- [x] reconnecting 与 failed 分开显示。

## 节点与转发

- [x] 从节点注册表是唯一权威；主节点没有远端 ensure/CRUD/release 接口。
- [x] 主节点只读查询和用户触发的 start/stop 全部经 SSH。
- [x] 转发记录、监听进程和状态只属于主节点本机。
- [x] 默认只向 ssh/autossh 传 Host 别名。
- [x] 可选择显式 SSH user/port/key 模式。
- [x] AutoSSH 存活但本机暂未监听时进入 reconnecting。
- [x] 同一本机端口只允许一条活动/重连中的转发。

## 自动验证

```bash
uv run pytest -q
cd web && npm run build
```

运行环境切换时还需人工验证：SSH config 实际选路、AutoSSH 重连、远端 HTTP
健康检查，以及 Web UI 直达链接。
