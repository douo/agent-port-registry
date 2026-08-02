# Agent Port Registry — 验收对照表

**PRD：** `Agent_Port_Registry_Local_PRD_v1.0.md` §18  
**自动化入口：** `uv run pytest`  
**日期：** 2026-07-31

| AC | 描述 | 结果 | 证据 |
|---|---|---|---|
| AC-001 | 单端口分配 | **pass** | `tests/api/test_ensure.py::test_ac001_single_port` |
| AC-002 | 幂等 | **pass** | `test_ac002_idempotent`（20 次同端口；CLI 集成再验证） |
| AC-003 | 连续 8 端口 | **pass** | `test_ac003_block` |
| AC-004 | 5 个非连续端口 | **pass** | `test_ac004_count` |
| AC-005 | 命名端口可查询 | **pass** | `test_ac005_named_ports_persist` |
| AC-006 | 多 Resource 原子性 | **pass** | `test_ac006_atomic_multi_resource_failure` |
| AC-007 | Claim 唯一 | **pass** | `test_ac007_unique_claims` + store 唯一约束测试 |
| AC-008 | OS Listener 排除 | **pass** | `tests/unit/test_allocator.py::test_skips_claimed_and_listening`；ensure 使用 `probe_listeners` |
| AC-009 | 固定端口占用仍返回原端口 | **pass** | ensure existing 路径返回 availability；单元/API 返回原分配 |
| AC-010 | 停止后保留 Claim | **pass** | release 前 claim 保留；无 auto-release 逻辑 |
| AC-011 | 重启持久化 | **pass** | SQLite 持久化；daemon 重启后 DB 文件保留（集成路径用同一 data_dir） |
| AC-012 | Agent 可空 | **pass** | `test_ac012_human_no_agent` |
| AC-013 | 多 Agent 同一 CLI | **pass** | CLI 不绑定 Agent；skills 仅注入 type（手工/文档） |
| AC-014 | 同项目多服务 | **pass** | 不同 `service.key` 独立 ensure（AC-007 用例） |
| AC-015 | 多 Allocation | **pass** | `test_ac015_multi_allocation` |
| AC-016 | 规格冲突 | **pass** | `test_ac016_spec_mismatch` |
| AC-017 | 显式释放 | **pass** | `test_ac017_release_and_reallocate` + CLI release |
| AC-018 | 端口反查 | **pass** | `test_ac018_port_lookup` + `inspect-port` |
| AC-019 | 元数据更新不改端口 | **pass** | `test_ac019_metadata_update_keeps_ports` |
| AC-020 | Skill 行为 | **pass** | `skills/**` 已提供；行为为 Agent 侧约定（文档验收） |

## P0 里程碑

- [x] Registry 常驻 + SQLite
- [x] `svcctl ensure` single / block / count
- [x] 幂等 ensure
- [x] OS Listener 排除
- [x] 多 Resource 原子性
- [x] Service 列表 + 端口反查
- [x] 显式 release
- [x] 通用 Skill + 三 Agent 目录
- [x] 自动化测试覆盖核心 AC

## P1（未作为阻塞）

| 项 | 状态 |
|---|---|
| 本机 Web 服务索引 | deferred |
| Shell 补全 | deferred |
| `svcctl check` PID/cmdline | **done**（listener probe 支持） |
| 服务搜索 | **done** |
| 数据库备份 | **done**（`svcctl backup`） |
