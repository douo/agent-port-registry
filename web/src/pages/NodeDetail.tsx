import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowLeft,
  ExternalLink,
  Play,
  Plus,
  RefreshCw,
  Square,
  Trash2,
} from 'lucide-react'
import {
  api,
  errorLabel,
  queryKeys,
  type PortForward,
  type Service,
} from '../lib/api'
import { relativeTime, servicePorts } from '../lib/format'
import PortSummary, { shouldSummarizePorts } from '../components/PortSummary'
import {
  Button,
  ConfirmDialog,
  Empty,
  ErrorNote,
  FieldLabel,
  Loading,
  Modal,
  Panel,
  PanelHeader,
  TextInput,
} from '../components/ui'

const EMPTY_FORWARD = {
  remotePort: '',
  localPort: '',
  remoteHost: '127.0.0.1',
  label: '',
  autoStart: true,
}

export default function NodeDetail() {
  const { id = '' } = useParams()
  const qc = useQueryClient()
  const [actionError, setActionError] = useState<unknown>(null)
  const [busyKey, setBusyKey] = useState<string | null>(null)
  const [forwardFormOpen, setForwardFormOpen] = useState(false)
  const [forwardDraft, setForwardDraft] = useState(EMPTY_FORWARD)
  const [removeForward, setRemoveForward] = useState<PortForward | null>(null)

  const node = useQuery({
    queryKey: queryKeys.node(id),
    queryFn: () => api.node(id),
    enabled: Boolean(id),
    refetchInterval: 15000,
  })
  const services = useQuery({
    queryKey: queryKeys.nodeServices(id),
    queryFn: () => api.nodeServices(id),
    enabled: Boolean(id),
    refetchInterval: 15000,
  })
  const forwards = useQuery({
    queryKey: queryKeys.forwards(id),
    queryFn: () => api.forwards(id),
    enabled: Boolean(id),
    refetchInterval: 5000,
  })

  const list: Service[] = services.data?.services ?? []
  const currentByRemote = useMemo(() => {
    const map = new Map<number, PortForward>()
    const newestFirst = [...(forwards.data ?? [])].sort((a, b) =>
      b.created_at.localeCompare(a.created_at),
    )
    for (const f of newestFirst) {
      if (!map.has(f.remote_port)) {
        map.set(f.remote_port, f)
      }
    }
    return map
  }, [forwards.data])
  const serviceByRemote = useMemo(() => {
    const map = new Map<number, Service>()
    for (const service of list) {
      for (const port of servicePorts(service)) {
        map.set(port.port, service)
      }
    }
    return map
  }, [list])
  const forwardRules = forwards.data ?? []

  const refreshMut = useMutation({
    mutationFn: () => api.refreshNode(id),
    onSuccess: async () => {
      setActionError(null)
      await qc.invalidateQueries({ queryKey: queryKeys.node(id) })
      await qc.invalidateQueries({ queryKey: queryKeys.nodeServices(id) })
      await qc.invalidateQueries({ queryKey: queryKeys.nodes })
    },
    onError: (err) => setActionError(err),
  })

  const startMut = useMutation({
    mutationFn: (serviceId: string) => api.startNodeService(id, serviceId),
    onMutate: (serviceId) => setBusyKey(`start:${serviceId}`),
    onSettled: () => setBusyKey(null),
    onSuccess: async () => {
      setActionError(null)
      await qc.invalidateQueries({ queryKey: queryKeys.nodeServices(id) })
    },
    onError: (err) => setActionError(err),
  })

  const stopMut = useMutation({
    mutationFn: (serviceId: string) => api.stopNodeService(id, serviceId),
    onMutate: (serviceId) => setBusyKey(`stop:${serviceId}`),
    onSettled: () => setBusyKey(null),
    onSuccess: async () => {
      setActionError(null)
      await qc.invalidateQueries({ queryKey: queryKeys.nodeServices(id) })
    },
    onError: (err) => setActionError(err),
  })

  const forwardOn = useMutation({
    mutationFn: (args: { port: number; label?: string; forwardId?: string }) =>
      args.forwardId
        ? api.startForward(args.forwardId)
        : api.createForward(id, { remote_port: args.port, label: args.label }),
    onMutate: (args) => setBusyKey(`fwd:${args.port}`),
    onSettled: () => setBusyKey(null),
    onSuccess: async () => {
      setActionError(null)
      await qc.invalidateQueries({ queryKey: queryKeys.forwards(id) })
      await qc.invalidateQueries({ queryKey: queryKeys.overview })
    },
    onError: (err) => setActionError(err),
  })

  const forwardOff = useMutation({
    mutationFn: (fwdId: string) => api.stopForward(fwdId),
    onMutate: (fwdId) => setBusyKey(`fwd-off:${fwdId}`),
    onSettled: () => setBusyKey(null),
    onSuccess: async () => {
      setActionError(null)
      await qc.invalidateQueries({ queryKey: queryKeys.forwards(id) })
      await qc.invalidateQueries({ queryKey: queryKeys.overview })
    },
    onError: (err) => setActionError(err),
  })

  const createForward = useMutation({
    mutationFn: () =>
      api.createForward(id, {
        remote_port: Number(forwardDraft.remotePort),
        local_port: forwardDraft.localPort ? Number(forwardDraft.localPort) : undefined,
        remote_host: forwardDraft.remoteHost.trim() || '127.0.0.1',
        label: forwardDraft.label.trim() || undefined,
        auto_start: forwardDraft.autoStart,
      }),
    onMutate: () => setBusyKey('fwd-create'),
    onSettled: () => setBusyKey(null),
    onSuccess: async () => {
      setActionError(null)
      setForwardFormOpen(false)
      setForwardDraft(EMPTY_FORWARD)
      await qc.invalidateQueries({ queryKey: queryKeys.forwards(id) })
      await qc.invalidateQueries({ queryKey: queryKeys.overview })
    },
    onError: (err) => setActionError(err),
  })

  const updateForwardAutoStart = useMutation({
    mutationFn: ({ fwdId, autoStart }: { fwdId: string; autoStart: boolean }) =>
      api.patchForward(fwdId, { auto_start: autoStart }),
    onMutate: ({ fwdId }) => setBusyKey(`fwd-auto-start:${fwdId}`),
    onSettled: () => setBusyKey(null),
    onSuccess: async () => {
      setActionError(null)
      await qc.invalidateQueries({ queryKey: queryKeys.forwards(id) })
    },
    onError: (err) => setActionError(err),
  })

  const deleteForward = useMutation({
    mutationFn: (fwdId: string) => api.deleteForward(fwdId),
    onMutate: (fwdId) => setBusyKey(`fwd-delete:${fwdId}`),
    onSettled: () => setBusyKey(null),
    onSuccess: async () => {
      setActionError(null)
      setRemoveForward(null)
      await qc.invalidateQueries({ queryKey: queryKeys.forwards(id) })
      await qc.invalidateQueries({ queryKey: queryKeys.overview })
    },
    onError: (err) => setActionError(err),
  })

  if (node.isError) return <ErrorNote error={node.error} />
  if (!node.data) return <Loading />

  const n = node.data

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start gap-3">
        <Link
          to="/nodes"
          className="mt-0.5 inline-flex items-center gap-1 text-xs text-muted hover:text-fg"
        >
          <ArrowLeft size={14} />
          节点
        </Link>
        <div className="min-w-0 flex-1">
          <h2 className="text-lg font-medium">{n.name}</h2>
          <div className="font-mono text-xs text-faint">
            {n.ssh_user ? `${n.ssh_user}@` : ''}
            {n.ssh_host}
            {n.ssh_port ? `:${n.ssh_port}` : ''}
            {' · '}
            {n.kind === 'forward-only' ? '仅管理 SSH 转发' : n.apr_command}
          </div>
        </div>
        {n.kind !== 'forward-only' && (
          <Button
            variant="secondary"
            disabled={refreshMut.isPending}
            onClick={() => refreshMut.mutate()}
          >
            <RefreshCw size={14} className={refreshMut.isPending ? 'animate-spin' : ''} />
            同步
          </Button>
        )}
      </div>

      {actionError != null && (
        <div className="panel border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
          {errorLabel(actionError)}
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-3">
        <Meta
          label="同步状态"
          value={
            n.snapshot?.status === 'ok'
              ? '在线'
                : n.snapshot?.status === 'error'
                  ? '错误'
                  : n.kind === 'forward-only'
                    ? '仅转发'
                    : '未同步'
          }
        />
        <Meta label="上次同步" value={relativeTime(n.snapshot?.fetched_at ?? n.last_seen_at)} />
        <Meta
          label="耗时"
          value={
            n.snapshot?.duration_ms != null ? `${n.snapshot.duration_ms} ms` : '—'
          }
        />
      </div>
      {n.snapshot?.error && (
        <div className="rounded-lg border border-danger/30 bg-danger/5 px-3 py-2 text-xs text-danger">
          {n.snapshot.error}
        </div>
      )}

      <Panel className="overflow-hidden">
        <PanelHeader
          title={n.kind === 'forward-only' ? '从节点服务（不适用）' : '从节点服务'}
          hint={list.length ? `${list.length} 个` : undefined}
        />
        {services.isLoading ? (
          <Loading />
        ) : services.isError ? (
          <ErrorNote error={services.error} />
        ) : list.length === 0 ? (
          <Empty
            title={n.kind === 'forward-only' ? '该节点仅用于 SSH 转发' : '快照中没有服务'}
            hint={n.kind === 'forward-only' ? '转发记录仍可在下方直接管理' : '确认从节点 APR 在运行，然后点同步'}
          />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line-soft text-left text-xs text-faint">
                <th className="py-2.5 pl-4">服务</th>
                <th className="py-2.5">端口 / 转发</th>
                <th className="py-2.5 pr-4 text-right">进程</th>
              </tr>
            </thead>
            <tbody>
              {list.map((svc) => {
                const ports = servicePorts(svc)
                const proc = svc.process
                const running =
                  proc?.state === 'running' || proc?.state === 'starting' || proc?.alive
                const forwardedCount = ports.filter((p) => {
                  const state = currentByRemote.get(p.port)?.state
                  return (
                    state === 'active' || state === 'starting' || state === 'reconnecting'
                  )
                }).length
                return (
                  <tr
                    key={svc.id}
                    className="group border-b border-line-soft/60 transition-colors last:border-0 hover:bg-hover/60"
                  >
                    <td className="py-3 pl-4 align-top">
                      <Link
                        to={`/nodes/${id}/services/${svc.id}`}
                        className="block min-w-0"
                      >
                        <div className="font-medium transition-colors group-hover:text-brand">
                          {svc.name}
                        </div>
                        <div className="font-mono text-[11px] text-faint">
                          {svc.service_key}
                          {svc.instance_key ? `:${svc.instance_key}` : ''}
                          <span className="text-faint/80"> · {svc.id.slice(0, 16)}</span>
                        </div>
                        {svc.start_command && (
                          <div className="mt-1 max-w-md truncate font-mono text-[10px] text-faint">
                            {svc.start_command}
                          </div>
                        )}
                      </Link>
                      <Link
                        to={`/nodes/${id}/services/${svc.id}`}
                        className="mt-1.5 inline-flex items-center gap-1 text-[11px] text-brand hover:underline"
                      >
                        查看详情
                      </Link>
                    </td>
                    <td className="py-3 align-top">
                      <div className="flex flex-col gap-1.5">
                        {ports.length === 0 ? (
                          <span className="text-xs text-faint">无端口</span>
                        ) : shouldSummarizePorts(ports) ? (
                          <div className="flex flex-col items-start gap-1.5">
                            <Link to={`/nodes/${id}/services/${svc.id}`}>
                              <PortSummary ports={ports} />
                            </Link>
                            {forwardedCount > 0 && (
                              <span className="text-[11px] text-live">
                                {forwardedCount} 个已转发
                              </span>
                            )}
                          </div>
                        ) : (
                          ports.map((p) => {
                            const fwd = currentByRemote.get(p.port)
                            const on =
                              fwd?.state === 'active' ||
                              fwd?.state === 'starting' ||
                              fwd?.state === 'reconnecting'
                            return (
                              <div
                                key={p.port}
                                className="flex flex-wrap items-center gap-2 text-xs"
                              >
                                <span className="chip font-mono">
                                  {p.label}={p.port}
                                </span>
                                {on && fwd ? (
                                  <>
                                    {fwd.state === 'active' ? (
                                      <a
                                        href={fwd.local_url}
                                        className="inline-flex items-center gap-1 font-mono text-brand hover:underline"
                                        target="_blank"
                                        rel="noreferrer"
                                      >
                                        localhost:{fwd.local_port}
                                        <ExternalLink size={10} />
                                      </a>
                                    ) : (
                                      <span className="font-mono text-idle">
                                        localhost:{fwd.local_port} ·{' '}
                                        {fwd.state === 'reconnecting' ? '等待网络恢复' : '启动中'}
                                      </span>
                                    )}
                                    <Button
                                      variant="ghost"
                                      className="!px-2 !py-0.5 text-[11px]"
                                      disabled={busyKey === `fwd-off:${fwd.id}`}
                                      onClick={() => forwardOff.mutate(fwd.id)}
                                    >
                                      停止转发
                                    </Button>
                                  </>
                                ) : (
                                  <>
                                    {fwd?.state === 'failed' && (
                                      <span
                                        className="text-danger"
                                        title={fwd.last_error ?? '转发启动失败'}
                                      >
                                        上次转发失败
                                      </span>
                                    )}
                                    {fwd?.state === 'stopped' && (
                                      <span className="text-faint">转发已停止</span>
                                    )}
                                    <Button
                                      variant="secondary"
                                      className="!px-2 !py-0.5 text-[11px]"
                                      disabled={busyKey === `fwd:${p.port}`}
                                      onClick={() =>
                                        forwardOn.mutate({
                                          port: p.port,
                                          label: `${svc.name} ${p.label}`,
                                          forwardId: fwd?.id,
                                        })
                                      }
                                    >
                                      {fwd ? '恢复原端口' : '转发到本机'}
                                    </Button>
                                  </>
                                )}
                              </div>
                            )
                          })
                        )}
                      </div>
                    </td>
                    <td className="py-3 pr-4 align-top text-right">
                      <div className="mb-1.5 text-[11px] text-faint">
                        {proc
                          ? `${proc.state}${proc.pid ? ` · pid ${proc.pid}` : ''}`
                          : '未知'}
                      </div>
                      <div className="flex justify-end gap-1">
                        <Button
                          variant="secondary"
                          className="!px-2 !py-1"
                          disabled={busyKey === `start:${svc.id}` || Boolean(running)}
                          title="远程启动（需从节点开启 process_management）"
                          onClick={() => startMut.mutate(svc.id)}
                        >
                          <Play size={12} />
                        </Button>
                        <Button
                          variant="ghost"
                          className="!px-2 !py-1"
                          disabled={busyKey === `stop:${svc.id}` || !running}
                          onClick={() => stopMut.mutate(svc.id)}
                        >
                          <Square size={12} />
                        </Button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel>
        <PanelHeader
          title="本机转发规则"
          hint={forwardRules.length ? `${forwardRules.length} 条` : '无'}
          action={
            <Button
              variant="primary"
              className="!px-2.5 !py-1 text-xs"
              onClick={() => setForwardFormOpen(true)}
            >
              <Plus size={13} />
              添加
            </Button>
          }
        />
        {forwardRules.length === 0 ? (
          <Empty title="还没有转发规则" />
        ) : (
          <ul className="divide-y divide-line-soft">
            {forwardRules.map((f) => {
              const service = serviceByRemote.get(f.remote_port)
              const detailUrl = service
                ? `/nodes/${id}/services/${service.id}`
                : null
              const running =
                f.state === 'active' || f.state === 'starting' || f.state === 'reconnecting'
              return (
                <li
                  key={f.id}
                  className="flex flex-wrap items-center gap-3 px-4 py-2.5 text-sm"
                >
                  <span className="font-mono text-xs">
                    {f.local_port} → {n.ssh_host} → {f.remote_host}:{f.remote_port}
                  </span>
                  {service && detailUrl ? (
                    <Link
                      to={detailUrl}
                      className="text-xs font-medium text-brand hover:underline"
                    >
                      {service.name}
                    </Link>
                  ) : (
                    <span className="text-xs text-faint">
                      {f.label ?? f.id.slice(0, 12)}
                    </span>
                  )}
                  {f.state === 'active' && (
                    <a
                      href={f.local_url}
                      className="inline-flex items-center gap-1 font-mono text-xs text-brand hover:underline"
                      target="_blank"
                      rel="noreferrer"
                    >
                      打开 localhost:{f.local_port}
                      <ExternalLink size={10} />
                    </a>
                  )}
                  <span
                    className={
                      f.state === 'active'
                        ? 'text-xs text-live'
                        : 'text-xs text-idle'
                    }
                  >
                    {forwardStateLabel(f.state)}
                  </span>
                  {f.last_error && f.state !== 'active' && (
                    <span
                      className="max-w-72 truncate text-[11px] text-danger"
                      title={f.last_error}
                    >
                      {f.last_error}
                    </span>
                  )}
                  <label className="inline-flex items-center gap-1.5 text-xs text-muted">
                    <input
                      type="checkbox"
                      checked={f.auto_start}
                      disabled={busyKey === `fwd-auto-start:${f.id}`}
                      onChange={(event) =>
                        updateForwardAutoStart.mutate({
                          fwdId: f.id,
                          autoStart: event.target.checked,
                        })
                      }
                      className="h-3.5 w-3.5 accent-brand"
                    />
                    自启动
                  </label>
                  <span className="text-[11px] text-faint">主节点本机 APR 托管</span>
                  <div className="ml-auto flex items-center gap-1.5">
                    {detailUrl && (
                      <Link
                        to={detailUrl}
                        className="inline-flex items-center rounded-lg px-2 py-1 text-xs text-muted hover:bg-hover hover:text-fg"
                      >
                        服务详情
                      </Link>
                    )}
                    {running ? (
                      <Button
                        variant="ghost"
                        className="!px-2 !py-0.5 text-xs"
                        disabled={busyKey === `fwd-off:${f.id}`}
                        onClick={() => forwardOff.mutate(f.id)}
                      >
                        <Square size={12} />
                        停止
                      </Button>
                    ) : (
                      <Button
                        variant="secondary"
                        className="!px-2 !py-0.5 text-xs"
                        disabled={busyKey === `fwd:${f.remote_port}`}
                        onClick={() =>
                          forwardOn.mutate({ port: f.remote_port, forwardId: f.id })
                        }
                      >
                        <Play size={12} />
                        启动
                      </Button>
                    )}
                    <Button
                      variant="ghost"
                      className="!px-2 !py-0.5 text-xs"
                      title="移除规则"
                      disabled={busyKey === `fwd-delete:${f.id}`}
                      onClick={() => setRemoveForward(f)}
                    >
                      <Trash2 size={12} />
                    </Button>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </Panel>

      <Modal
        open={forwardFormOpen}
        onClose={() => setForwardFormOpen(false)}
        title="添加本机转发"
      >
        <form
          className="space-y-3 px-1 pb-1"
          onSubmit={(event) => {
            event.preventDefault()
            createForward.mutate()
          }}
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <FieldLabel htmlFor="forward-local-port" hint="留空自动选择">
                本机端口
              </FieldLabel>
              <TextInput
                id="forward-local-port"
                type="number"
                min={1}
                max={65535}
                value={forwardDraft.localPort}
                onChange={(event) =>
                  setForwardDraft((value) => ({ ...value, localPort: event.target.value }))
                }
              />
            </div>
            <div>
              <FieldLabel htmlFor="forward-remote-port">目标端口</FieldLabel>
              <TextInput
                id="forward-remote-port"
                type="number"
                min={1}
                max={65535}
                required
                value={forwardDraft.remotePort}
                onChange={(event) =>
                  setForwardDraft((value) => ({ ...value, remotePort: event.target.value }))
                }
              />
            </div>
          </div>
          <div>
            <FieldLabel htmlFor="forward-remote-host">目标主机</FieldLabel>
            <TextInput
              id="forward-remote-host"
              value={forwardDraft.remoteHost}
              onChange={(event) =>
                setForwardDraft((value) => ({ ...value, remoteHost: event.target.value }))
              }
            />
          </div>
          <div>
            <FieldLabel htmlFor="forward-label" hint="可选">
              名称
            </FieldLabel>
            <TextInput
              id="forward-label"
              value={forwardDraft.label}
              onChange={(event) =>
                setForwardDraft((value) => ({ ...value, label: event.target.value }))
              }
            />
          </div>
          <label className="flex items-center gap-3 rounded-lg border border-line-soft bg-raised px-3 py-2 text-sm">
            <input
              type="checkbox"
              checked={forwardDraft.autoStart}
              onChange={(event) =>
                setForwardDraft((value) => ({ ...value, autoStart: event.target.checked }))
              }
              disabled={createForward.isPending}
              className="h-4 w-4 accent-brand"
            />
            <span>随 APR 自启动</span>
          </label>
          <div className="flex justify-end gap-2 pt-1">
            <Button variant="ghost" onClick={() => setForwardFormOpen(false)}>
              取消
            </Button>
            <Button variant="primary" type="submit" disabled={createForward.isPending}>
              <Plus size={14} />
              {createForward.isPending ? '添加中…' : '添加并启动'}
            </Button>
          </div>
        </form>
      </Modal>

      <ConfirmDialog
        open={removeForward != null}
        title="移除转发规则？"
        body={
          removeForward
            ? `${removeForward.local_port} → ${n.ssh_host} → ${removeForward.remote_host}:${removeForward.remote_port}`
            : ''
        }
        confirmLabel="移除"
        danger
        loading={deleteForward.isPending}
        onConfirm={() => {
          if (removeForward) deleteForward.mutate(removeForward.id)
        }}
        onClose={() => setRemoveForward(null)}
      />
    </div>
  )
}

function forwardStateLabel(state: PortForward['state']) {
  if (state === 'active') return '运行中'
  if (state === 'starting') return '启动中'
  if (state === 'reconnecting') return '等待主机恢复'
  if (state === 'failed') return '恢复失败'
  return '已停止'
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="panel px-4 py-3">
      <div className="text-[11px] text-faint">{label}</div>
      <div className="mt-1 text-sm">{value}</div>
    </div>
  )
}
