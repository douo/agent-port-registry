import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  Pencil,
  Plus,
  Square,
  Terminal,
  Trash2,
  Play,
  ScrollText,
} from 'lucide-react'
import {
  api,
  errorLabel,
  invalidateServiceViews,
  queryKeys,
  type Allocation,
  type Service,
} from '../lib/api'
import { absoluteTime, relativeTime } from '../lib/format'
import EditServiceForm from '../components/EditServiceForm'
import EnsureForm from '../components/EnsureForm'
import {
  Button,
  ConfirmDialog,
  ErrorNote,
  FormError,
  Loading,
  Panel,
  PanelHeader,
  StatusDot,
} from '../components/ui'

/** Preview of `start_command` with {{ports.x}} resolved — phase 4 will run this. */
function renderCommand(command: string, ports: Record<string, number>): string {
  return command.replace(/\{\{\s*ports\.([A-Za-z0-9_-]+)\s*\}\}/g, (whole, name: string) =>
    name in ports ? String(ports[name]) : whole,
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1 px-4 py-3 sm:flex-row sm:items-baseline sm:gap-4">
      <div className="w-32 shrink-0 text-xs text-faint">{label}</div>
      <div className="min-w-0 flex-1 break-words text-sm">{children}</div>
    </div>
  )
}

export default function ServiceDetail() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const qc = useQueryClient()

  const [editOpen, setEditOpen] = useState(false)
  const [ensureOpen, setEnsureOpen] = useState(false)
  const [releaseTarget, setReleaseTarget] = useState<Allocation | null>(null)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [actionError, setActionError] = useState<unknown>(null)

  const service = useQuery({
    queryKey: queryKeys.service(id),
    queryFn: () => api.service(id),
    enabled: Boolean(id),
  })
  const listenersQuery = useQuery({
    queryKey: queryKeys.listeners,
    queryFn: () => api.listeners(),
  })
  const overview = useQuery({ queryKey: queryKeys.overview, queryFn: api.overview })
  const pmEnabled = overview.data?.features?.process_management === true
  const logsQuery = useQuery({
    queryKey: queryKeys.serviceLogs(id),
    queryFn: () => api.serviceLogs(id, 200),
    enabled: Boolean(id) && pmEnabled,
    refetchInterval: 3000,
  })

  const startMut = useMutation({
    mutationFn: () => api.startService(id),
    onSuccess: async () => {
      setActionError(null)
      await invalidateServiceViews(qc, id)
      await qc.invalidateQueries({ queryKey: queryKeys.serviceLogs(id) })
    },
    onError: (err) => setActionError(err),
  })

  const stopMut = useMutation({
    mutationFn: () => api.stopService(id),
    onSuccess: async () => {
      setActionError(null)
      await invalidateServiceViews(qc, id)
      await qc.invalidateQueries({ queryKey: queryKeys.serviceLogs(id) })
    },
    onError: (err) => setActionError(err),
  })

  const releaseMut = useMutation({
    mutationFn: (alloc: Allocation) =>
      api.releaseAllocation(alloc.id, 'released from web ui'),
    onMutate: async (alloc) => {
      setActionError(null)
      await qc.cancelQueries({ queryKey: queryKeys.service(id) })
      const previous = qc.getQueryData<Service>(queryKeys.service(id))
      if (previous) {
        qc.setQueryData<Service>(queryKeys.service(id), {
          ...previous,
          allocations: previous.allocations.map((a) =>
            a.id === alloc.id
              ? {
                  ...a,
                  state: 'released',
                  released_at: new Date().toISOString(),
                  release_reason: 'released from web ui',
                }
              : a,
          ),
        })
      }
      return { previous }
    },
    onError: (err, _alloc, ctx) => {
      if (ctx?.previous) qc.setQueryData(queryKeys.service(id), ctx.previous)
      setActionError(err)
    },
    onSuccess: async () => {
      setReleaseTarget(null)
      await invalidateServiceViews(qc, id)
    },
  })

  const deleteMut = useMutation({
    mutationFn: () => api.deleteService(id, 'deleted from web ui'),
    onMutate: async () => {
      setActionError(null)
      await qc.cancelQueries({ queryKey: queryKeys.services })
      const previous = qc.getQueryData<Service[]>(queryKeys.services)
      if (previous) {
        qc.setQueryData<Service[]>(
          queryKeys.services,
          previous.filter((s) => s.id !== id),
        )
      }
      return { previous }
    },
    onError: (err, _v, ctx) => {
      if (ctx?.previous) qc.setQueryData(queryKeys.services, ctx.previous)
      setActionError(err)
    },
    onSuccess: async () => {
      setDeleteOpen(false)
      await invalidateServiceViews(qc)
      navigate('/services')
    },
  })

  if (service.isError) return <ErrorNote error={service.error} />
  if (!service.data) return <Loading />

  const s = service.data
  const listeners = new Map((listenersQuery.data ?? []).map((l) => [l.port, l]))
  const reserved = s.allocations.filter((a) => a.state === 'reserved')
  const released = s.allocations.filter((a) => a.state === 'released')

  const portMap: Record<string, number> = {}
  for (const alloc of reserved) {
    for (const p of alloc.ports) portMap[p.port_name ?? p.resource_name] = p.port
  }
  const anyLive = Object.values(portMap).some((p) => listeners.has(p))
  const process = s.process ?? null
  // Backend reconcile should clear dead "running" rows; still require alive so a
  // stale payload never shows 启动中 after command-not-found.
  const running =
    process != null &&
    (process.state === 'starting' || process.state === 'running') &&
    process.alive === true
  const startFailed = process?.state === 'failed'
  const hasStartCommand = Boolean(s.start_command?.trim())
  const processBusy = startMut.isPending || stopMut.isPending

  return (
    <div className="space-y-5">
      <div>
        <Link
          to="/services"
          className="mb-3 inline-flex items-center gap-1.5 text-xs text-faint transition-colors hover:text-fg"
        >
          <ArrowLeft size={13} />
          返回服务列表
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <StatusDot live={anyLive || running} />
          <h2 className="text-xl">{s.name}</h2>
          <span className="chip">{s.id}</span>
          {running && (
            <span className="rounded bg-live/15 px-1.5 py-0.5 text-[11px] text-live">
              进程运行中 · pid {process?.pid}
            </span>
          )}
          {startFailed && !running && (
            <span className="rounded bg-danger/15 px-1.5 py-0.5 text-[11px] text-danger">
              启动失败
              {process?.exit_code != null ? ` · exit ${process.exit_code}` : ''}
            </span>
          )}
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {pmEnabled && hasStartCommand && (
              running ? (
                <Button
                  variant="danger"
                  onClick={() => {
                    setActionError(null)
                    stopMut.mutate()
                  }}
                  disabled={processBusy}
                >
                  <Square size={14} />
                  {stopMut.isPending ? '停止中…' : '停止'}
                </Button>
              ) : (
                <Button
                  variant="primary"
                  onClick={() => {
                    setActionError(null)
                    startMut.mutate()
                  }}
                  disabled={processBusy}
                >
                  <Play size={14} />
                  {startMut.isPending ? '启动中…' : '启动'}
                </Button>
              )
            )}
            <Button variant="secondary" onClick={() => setEnsureOpen(true)}>
              <Plus size={14} />
              申请端口
            </Button>
            <Button variant="secondary" onClick={() => setEditOpen(true)}>
              <Pencil size={14} />
              编辑
            </Button>
            <Button variant="danger" onClick={() => setDeleteOpen(true)}>
              <Trash2 size={14} />
              删除
            </Button>
          </div>
        </div>
        {s.description && <p className="mt-2 text-sm text-muted">{s.description}</p>}
        {Boolean(startMut.isError || stopMut.isError || actionError) &&
          releaseTarget == null &&
          !deleteOpen && (
            <div className="mt-3">
              <FormError error={actionError ?? startMut.error ?? stopMut.error} />
            </div>
          )}
      </div>

      <Panel>
        <PanelHeader title="端口" hint={`${Object.keys(portMap).length} 个生效端口`} />
        {reserved.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm text-faint">
            该服务当前没有生效的端口分配
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line-soft text-left text-xs text-faint">
                <th className="py-2 pl-4 font-normal">名称</th>
                <th className="py-2 pr-3 font-normal">端口</th>
                <th className="py-2 pr-3 font-normal">状态</th>
                <th className="hidden py-2 pr-4 font-normal md:table-cell">进程</th>
              </tr>
            </thead>
            <tbody>
              {reserved.flatMap((alloc) =>
                alloc.ports.map((p) => {
                  const listener = listeners.get(p.port)
                  return (
                    <tr
                      key={`${alloc.id}-${p.resource_name}-${p.ordinal}`}
                      className="border-b border-line-soft/60 last:border-0"
                    >
                      <td className="py-2.5 pl-4 font-mono text-xs">
                        {p.port_name ?? p.resource_name}
                      </td>
                      <td className="py-2.5 pr-3">
                        <a
                          href={`http://127.0.0.1:${p.port}`}
                          target="_blank"
                          rel="noreferrer"
                          className="chip transition-colors hover:border-brand/50 hover:text-brand"
                          title="在新标签打开 http://127.0.0.1:该端口"
                        >
                          {p.port}
                        </a>
                      </td>
                      <td className="py-2.5 pr-3">
                        {listener ? (
                          <span className="text-xs text-live">监听中</span>
                        ) : (
                          <span className="text-xs text-idle">无监听</span>
                        )}
                      </td>
                      <td
                        className="hidden max-w-md truncate py-2.5 pr-4 font-mono text-[11px] text-faint md:table-cell"
                        title={listener?.command ?? ''}
                      >
                        {listener
                          ? `${listener.pid ?? '?'} · ${listener.command ?? '—'}`
                          : '—'}
                      </td>
                    </tr>
                  )
                }),
              )}
            </tbody>
          </table>
        )}
      </Panel>

      {(pmEnabled || hasStartCommand) && (
        <Panel>
          <PanelHeader
            title="进程"
            hint={
              !pmEnabled
                ? '进程管理未开启'
                : running
                  ? `pid ${process?.pid}`
                  : process
                    ? process.state
                    : '未启动'
            }
            action={
              pmEnabled ? (
                <span className="flex items-center gap-1 text-[11px] text-faint">
                  <ScrollText size={12} />
                  日志自动刷新
                </span>
              ) : undefined
            }
          />
          {!pmEnabled ? (
            <div className="space-y-2 px-4 py-4 text-sm text-muted">
              <p>
                启动 / 停止需要显式开启进程管理。在{' '}
                <code className="font-mono text-xs text-fg">~/.config/apr/config.yaml</code>{' '}
                中设置：
              </p>
              <pre className="rounded-lg bg-raised px-3 py-2 font-mono text-xs text-fg">
                {`process_management:\n  enabled: true`}
              </pre>
              <p className="text-xs text-faint">
                或环境变量 <code className="font-mono">APR_PROCESS_MANAGEMENT=1</code>
                ，然后重启 registry。此能力可执行任意命令，默认关闭。
              </p>
            </div>
          ) : (
            <div className="space-y-3 px-4 py-3">
              {process ? (
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                  <span className="chip">{process.id}</span>
                  <span
                    className={[
                      'rounded px-1.5 py-0.5',
                      running ? 'bg-live/15 text-live' : 'bg-raised text-faint',
                    ].join(' ')}
                  >
                    {process.state}
                    {process.exit_code != null ? ` · exit ${process.exit_code}` : ''}
                  </span>
                  {process.started_at && (
                    <span>启动于 {relativeTime(process.started_at)}</span>
                  )}
                  {process.last_error && (
                    <span className="text-danger">{process.last_error}</span>
                  )}
                </div>
              ) : (
                <div className="text-sm text-faint">尚无托管进程记录</div>
              )}
              {process?.command && (
                <div className="flex items-start gap-2 rounded-lg bg-raised px-3 py-2">
                  <Terminal size={13} className="mt-0.5 shrink-0 text-faint" />
                  <code className="font-mono text-xs text-fg">{process.command}</code>
                </div>
              )}
              <div className="overflow-hidden rounded-lg border border-line-soft bg-base">
                <div className="border-b border-line-soft px-3 py-1.5 text-[11px] text-faint">
                  {logsQuery.data?.log_path ?? `state/logs/${s.id}.log`}
                </div>
                <pre className="max-h-64 overflow-auto px-3 py-2 font-mono text-[11px] leading-relaxed text-muted">
                  {logsQuery.isLoading
                    ? '加载日志…'
                    : logsQuery.isError
                      ? errorLabel(logsQuery.error)
                      : (logsQuery.data?.lines.length ?? 0) === 0
                        ? '（日志为空）'
                        : logsQuery.data!.lines.join('\n')}
                </pre>
              </div>
            </div>
          )}
        </Panel>
      )}

      <Panel>
        <PanelHeader title="元数据" />
        <div className="divide-y divide-line-soft">
          <Field label="标识">
            <span className="font-mono text-xs">
              {s.agent_type_key} / {s.agent_project_key} / {s.service_key} /{' '}
              {s.instance_key}
            </span>
          </Field>
          <Field label="代码路径">
            {s.code_path ? (
              <span className="font-mono text-xs">{s.code_path}</span>
            ) : (
              <span className="text-faint">—</span>
            )}
          </Field>
          <Field label="工作目录">
            {s.working_directory ? (
              <span className="font-mono text-xs">{s.working_directory}</span>
            ) : (
              <span className="text-faint">—</span>
            )}
          </Field>
          <Field label="启动命令">
            {s.start_command ? (
              <div className="space-y-2">
                <div className="flex items-start gap-2 rounded-lg bg-raised px-3 py-2">
                  <Terminal size={13} className="mt-0.5 shrink-0 text-faint" />
                  <code className="font-mono text-xs text-fg">
                    {renderCommand(s.start_command, portMap)}
                  </code>
                </div>
                {s.start_command.includes('{{') && (
                  <div className="text-[11px] text-faint">
                    原文：<code className="font-mono">{s.start_command}</code>
                  </div>
                )}
              </div>
            ) : (
              <span className="text-faint">—</span>
            )}
          </Field>
          <Field label="创建 / 更新">
            <span className="text-xs text-muted">
              {absoluteTime(s.created_at)} · 更新于 {relativeTime(s.updated_at)}
            </span>
          </Field>
        </div>
      </Panel>

      <Panel>
        <PanelHeader title="分配" hint={`生效 ${reserved.length} · 历史 ${released.length}`} />
        <ul className="divide-y divide-line-soft">
          {s.allocations.map((alloc) => (
            <li key={alloc.id} className="px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="chip">{alloc.id}</span>
                <span className="text-sm">{alloc.allocation_name}</span>
                <span
                  className={[
                    'rounded px-1.5 py-0.5 text-[11px]',
                    alloc.state === 'reserved'
                      ? 'bg-live/15 text-live'
                      : 'bg-raised text-faint',
                  ].join(' ')}
                >
                  {alloc.state === 'reserved' ? '生效' : '已释放'}
                </span>
                <span className="ml-auto text-[11px] text-faint">
                  {relativeTime(alloc.created_at)}
                </span>
                {alloc.state === 'reserved' && (
                  <Button
                    variant="ghost"
                    className="text-xs text-danger"
                    onClick={() => {
                      setActionError(null)
                      setReleaseTarget(alloc)
                    }}
                  >
                    释放
                  </Button>
                )}
              </div>
              <div className="mt-2 flex flex-wrap gap-1">
                {alloc.ports.map((p) => (
                  <span key={`${p.resource_name}-${p.ordinal}`} className="chip">
                    {p.port_name ?? p.resource_name}={p.port}
                  </span>
                ))}
              </div>
              {alloc.release_reason && (
                <div className="mt-2 text-[11px] text-faint">
                  释放原因：{alloc.release_reason}
                </div>
              )}
            </li>
          ))}
        </ul>
      </Panel>

      <EditServiceForm open={editOpen} onClose={() => setEditOpen(false)} service={s} />
      <EnsureForm open={ensureOpen} onClose={() => setEnsureOpen(false)} service={s} />

      <ConfirmDialog
        open={releaseTarget != null}
        onClose={() => {
          if (!releaseMut.isPending) setReleaseTarget(null)
        }}
        onConfirm={() => {
          if (releaseTarget) releaseMut.mutate(releaseTarget)
        }}
        title="释放端口分配"
        body={
          releaseTarget ? (
            <>
              将释放分配{' '}
              <span className="font-mono text-fg">{releaseTarget.allocation_name}</span>
              （{releaseTarget.id}），端口会回到池中。此操作可在之后重新 ensure，但
              已占用的端口号不一定能拿回。
            </>
          ) : null
        }
        confirmLabel="确认释放"
        danger
        loading={releaseMut.isPending}
        error={actionError}
      />

      <ConfirmDialog
        open={deleteOpen}
        onClose={() => {
          if (!deleteMut.isPending) setDeleteOpen(false)
        }}
        onConfirm={() => deleteMut.mutate()}
        title="删除服务"
        body={
          <>
            将<strong className="text-fg">永久删除</strong>服务{' '}
            <span className="font-mono text-fg">{s.name}</span> 及其全部端口分配与历史记录。
            此操作不可撤销。
          </>
        }
        confirmLabel="确认删除"
        danger
        loading={deleteMut.isPending}
        error={actionError}
      />
    </div>
  )
}
