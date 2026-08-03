import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, ExternalLink, Play, RefreshCw, Square } from 'lucide-react'
import {
  api,
  errorLabel,
  queryKeys,
  type PortForward,
  type Service,
} from '../lib/api'
import { relativeTime, servicePorts } from '../lib/format'
import {
  Button,
  Empty,
  ErrorNote,
  Loading,
  Panel,
  PanelHeader,
} from '../components/ui'

export default function NodeDetail() {
  const { id = '' } = useParams()
  const qc = useQueryClient()
  const [actionError, setActionError] = useState<unknown>(null)
  const [busyKey, setBusyKey] = useState<string | null>(null)

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
  const activeForwards = useMemo(
    () =>
      (forwards.data ?? []).filter(
        (forward) =>
          forward.state === 'active' ||
          forward.state === 'starting' ||
          forward.state === 'reconnecting',
      ),
    [forwards.data],
  )

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
          title="本机到该节点的转发"
          hint={activeForwards.length ? `${activeForwards.length} 条` : '无'}
        />
        {activeForwards.length === 0 ? (
          <Empty title="当前没有转发" hint="在上方服务端口旁点「转发到本机」" />
        ) : (
          <ul className="divide-y divide-line-soft">
            {activeForwards.map((f) => {
              const service = serviceByRemote.get(f.remote_port)
              const detailUrl = service
                ? `/nodes/${id}/services/${service.id}`
                : null
              return (
                <li
                  key={f.id}
                  className="flex flex-wrap items-center gap-3 px-4 py-2.5 text-sm"
                >
                  <span className="font-mono text-xs">
                    {f.local_port} → {n.ssh_host}:{f.remote_port}
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
                    {f.state}
                  </span>
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
                    <Button
                      variant="ghost"
                      className="!px-2 !py-0.5 text-xs"
                      disabled={busyKey === `fwd-off:${f.id}`}
                      onClick={() => forwardOff.mutate(f.id)}
                    >
                      停止
                    </Button>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </Panel>
    </div>
  )
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="panel px-4 py-3">
      <div className="text-[11px] text-faint">{label}</div>
      <div className="mt-1 text-sm">{value}</div>
    </div>
  )
}
