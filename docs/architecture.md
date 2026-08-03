# APR 架构

## 1. 设计约束

每个 APR 实例都是所在节点的本地数据权威。Agent 是该节点服务的配置执行者，
主节点只是通过 SSH 聚合从节点信息，不是从节点的写入者。

```text
首次配置
目标节点 Agent ──ensure(project, service)──> 目标节点本地 APR
目标节点 Agent <──────── fixed ports ───── 目标节点本地 APR
目标节点 Agent ──写默认脚本/env/config──> 该节点本地服务

日常启动
Agent/用户 ──默认启动命令──> 服务（不访问 APR）
```

## 2. 组件

- `svcctl`：Agent 友好的 JSON/CLI 客户端。
- Registry API：loopback HTTP/Unix socket 控制面。
- Ensure service：只对当前 APR 所在节点做身份解析、幂等检查和事务写入。
- SQLite：保存当前节点本地服务、分配、Claim 和进程；主节点另外保存节点快照与
  本机转发记录。
- Web UI：复用同一 API 的服务、端口、节点、控制台和转发界面。
- SSH control plane：使用 SSH config 别名访问节点。
- AutoSSH manager：建立并监测节点到本机的端口转发。

## 3. 数据模型

### Node

`nodes.id` 是主节点用于寻址 SSH 目标的标识，不赋予主节点修改远端数据的权限。

远端节点默认设置 `ssh_config_managed=true`：APR 不传 `-p`、`-i` 或 user，
避免覆盖用户在 SSH config 中的 Match、ProxyJump 和网络切换策略。

### Service

唯一键：

```text
(project_key, service_key, instance_key)
```

`registered_by_agent` 只表示最近登记者。项目来源、路径、命令、健康检查和配置位置
属于服务元数据。

### Allocation 与 Claim

- Allocation 保存资源规格和历史。
- AllocatedPort 保存名称、协议、端口和顺序。
- ActivePortClaim 保存当前节点内的独占关系，主键为 `(transport, port)`。
- release 删除 Claim 并保留 Allocation 历史；service delete 才级联删除全部历史。

### Process 与 Forward

- ManagedProcess 保存受 APR 启动的进程、日志和运行态。
- PortForward 只保存在主节点，保存本机端口、目标节点/远端端口、PID 与 AutoSSH
  状态。目标节点是路由引用，不是转发所有者。
- 活动态唯一约束覆盖 `starting`、`active`、`reconnecting`，防止同一本机端口重复转发。

## 4. Ensure 事务

1. 确认请求作用于当前 APR 所在节点；不接受“替远端节点 ensure”。
2. 规范化项目、服务与实例键。
3. 在事务中查找或创建 Service。
4. 查找同名 Allocation：规格一致则幂等返回，不一致则报错。
5. 读取当前节点 Claims 并探测当前节点 Listener。
6. First Fit 计算全部资源，任一资源失败则整体回滚。
7. 同一事务写 Allocation、AllocatedPort 和 ActivePortClaim。
8. 返回端口和可用性。

并发写由 SQLite `BEGIN IMMEDIATE` 串行化；数据库唯一约束作为最终防线。

## 5. Agent 配置边界

APR 不修改任意第三方文件。Agent 在目标节点和用户授权的项目范围内完成修改：

- 自研项目优先改默认开发启动脚本或本地 env 模板；
- 第三方项目优先使用其官方配置机制，减少源代码改动；
- 记录 `configuration`，让人和后续 Agent 能找到端口来源；
- 修改后启动并执行健康检查；
- 后续启动只读取该持久化配置。

## 6. 主从节点职责与 SSH 控制面

从节点本地 Service/Allocation 是该节点唯一权威。主节点通过 SSH 调用从节点
`svcctl`，完整展示服务列表、详情、进程、日志和控制台；快照只是主节点侧的只读缓存。

主节点允许的远端调用：

- `list`、`inspect-service`、`process status`、`process logs` 等只读查询；
- 用户在 UI 明确触发后，对已登记服务执行 `process start/stop`。

主节点禁止的远端调用：

- `ensure`、service create/update/delete、allocation release/delete；
- 修改启动命令、端口、元数据、数据库或配置；
- 安装或升级从节点 APR。

远端首次配置必须由作用域在该节点的 Agent 调用该节点本地 APR 完成。

SSH 目标构造：

```text
ssh_config_managed=true  -> ssh <alias> -- ...
ssh_config_managed=false -> ssh [-p port] [-i key] [user@]host -- ...
```

AutoSSH 连接断开时父进程通常仍存活。此时 APR 标记 `reconnecting`，不误杀父进程；
恢复监听后重新标记 `active`。只有父进程退出或确定启动失败才标记 `failed`。

转发进程和本机监听端口全部属于主节点。节点详情可以派生显示“本机映射”，但从节点
APR 不保存、不创建也不停止任何主节点转发。

## 7. 安全

- API 与 Web UI 默认只绑定本机回环；没有鉴权时禁止暴露到外网卡。
- Unix socket、数据和状态目录使用用户私有权限。
- 进程管理默认关闭，因为 start command 可执行任意受信命令。
- SSH 使用 argv，不经本地 shell；Host 和显式字段均校验。
- 删除、释放和停止是显式操作。
- 任何远端数据库、配置、端口或程序变更都要求用户明确授权该具体节点；“删除遗留
  代码”本身不构成远端数据迁移授权。

## 8. 端口范围

默认 `41000–45999`。该 5000 端口范围：

- 与常见框架默认 HTTP 端口的重叠较少；
- 不包含当前手工转发 `23459`、`28188`、`31000`、`31201`；
- 足够容纳多服务、多实例和连续块；
- 只需修改 APR 配置和首次接入服务，不要求整体迁移现有第三方代码结构。

## 9. 源码边界

项目尚未发布稳定数据格式，只维护 `src/apr/store/schema.sql` 这一份当前 schema。
不存在固定端口导入、旧身份字段、迁移目录或兼容分支。
