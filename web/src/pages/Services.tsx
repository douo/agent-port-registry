import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ExternalLink, Eye, LoaderCircle, Play, Plus, Search, Square } from 'lucide-react'
import { api, errorLabel, invalidateServiceViews, queryKeys } from '../lib/api'
import { relativeTime, serviceAgentLabel, servicePorts, serviceProjectKey } from '../lib/format'
import EnsureForm from '../components/EnsureForm'
import PortSummary, { shouldSummarizePorts } from '../components/PortSummary'
import { Button, Empty, ErrorNote, Loading, Panel, StatusBadge } from '../components/ui'

type SortKey = 'port' | 'name' | 'project' | 'updated'

export default function Services() {
  const qc = useQueryClient()
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<SortKey>('port')
  const [ensureOpen, setEnsureOpen] = useState(false)
  const [actionError, setActionError] = useState<{ serviceId: string; message: string } | null>(
    null,
  )

  const services = useQuery({
    queryKey: queryKeys.services,
    queryFn: api.services,
    refetchInterval: 5000,
  })
  const listenersQuery = useQuery({
    queryKey: queryKeys.listeners,
    queryFn: () => api.listeners(),
    refetchInterval: 5000,
  })
  const overview = useQuery({ queryKey: queryKeys.overview, queryFn: api.overview })
  const pmEnabled = overview.data?.features?.process_management === true
  const listeners = useMemo(
    () => new Map((listenersQuery.data ?? []).map((listener) => [listener.port, listener])),
    [listenersQuery.data],
  )

  const startMut = useMutation({
    mutationFn: (serviceId: string) => api.startService(serviceId),
    onMutate: () => setActionError(null),
    onError: (error, serviceId) => setActionError({ serviceId, message: errorLabel(error) }),
    onSuccess: async (_process, serviceId) => {
      await invalidateServiceViews(qc, serviceId)
    },
  })

  const stopMut = useMutation({
    mutationFn: (serviceId: string) => api.stopService(serviceId),
    onMutate: () => setActionError(null),
    onError: (error, serviceId) => setActionError({ serviceId, message: errorLabel(error) }),
    onSuccess: async (_process, serviceId) => {
      await invalidateServiceViews(qc, serviceId)
    },
  })

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return (services.data ?? [])
      .map((service) => {
        const ports = servicePorts(service)
        const process = service.process ?? null
        const managed =
          process != null &&
          (process.state === 'starting' || process.state === 'running') &&
          process.alive === true
        const fallbackExternalListeners =
          service.runtime == null && !managed
            ? ports.flatMap(({ port }) => {
                const listener = listeners.get(port)
                return listener ? [listener] : []
              })
            : []
        const runtimeActive = service.runtime
          ? service.runtime.state === 'running'
          : managed || fallbackExternalListeners.length > 0
        const external =
          runtimeActive &&
          !managed &&
          (service.runtime?.source === 'external' || fallbackExternalListeners.length > 0)
        const externalListeners =
          service.runtime?.source === 'external'
            ? service.runtime.listeners
            : fallbackExternalListeners
        const pid = external
          ? externalListeners.find((listener) => listener.pid != null)?.pid
          : process?.pid
        return {
          service,
          ports,
          runtimeActive,
          runtimeUnknown: service.runtime?.state === 'unknown',
          managed,
          external,
          pid,
        }
      })
      .filter(({ service, ports }) => {
        if (!needle) return true
        return [
          service.name,
          service.service_key,
          service.instance_key,
          serviceProjectKey(service),
          serviceAgentLabel(service),
          service.description ?? '',
          ...ports.map((p) => String(p.port)),
        ]
          .join(' ')
          .toLowerCase()
          .includes(needle)
      })
      .sort((a, b) => {
        switch (sort) {
          case 'name':
            return a.service.name.localeCompare(b.service.name, 'zh-CN')
          case 'project':
            return (
              serviceProjectKey(a.service).localeCompare(serviceProjectKey(b.service)) ||
              a.service.name.localeCompare(b.service.name, 'zh-CN')
            )
          case 'updated':
            return b.service.updated_at.localeCompare(a.service.updated_at)
          default:
            return (a.ports[0]?.port ?? Infinity) - (b.ports[0]?.port ?? Infinity)
        }
      })
  }, [services.data, query, sort, listeners])

  if (services.isError) return <ErrorNote error={services.error} />

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-56 flex-1">
          <Search
            size={14}
            className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint"
          />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="按名称、标识、项目或端口过滤"
            className="w-full rounded-lg border border-line-soft bg-panel py-2 pl-9 pr-3 text-sm outline-none transition-colors placeholder:text-faint focus:border-brand/60"
          />
        </div>

        <Button variant="primary" onClick={() => setEnsureOpen(true)} className="shrink-0">
          <Plus size={14} />
          首次配置服务
        </Button>
      </div>

      <Panel className="overflow-hidden">
        {services.isLoading ? (
          <Loading />
        ) : rows.length === 0 ? (
          <Empty
            title={query ? '没有匹配的服务' : '还没有登记任何服务'}
            hint={
              query
                ? '换个关键词'
                : '由 Agent 首次配置服务时分配端口，并写入服务的默认启动配置'
            }
          />
        ) : (
          <table className="w-full table-fixed text-sm sm:table-auto">
            <thead>
              <tr className="border-b border-line-soft text-left text-xs text-faint">
                <th className="w-28 py-2.5 pl-4 font-normal">状态</th>
                <SortHeader active={sort === 'name'} onClick={() => setSort('name')}>
                  服务
                </SortHeader>
                <SortHeader
                  active={sort === 'project'}
                  onClick={() => setSort('project')}
                  className="hidden md:table-cell"
                >
                  设备 / 项目 / Agent
                </SortHeader>
                <SortHeader
                  active={sort === 'port'}
                  onClick={() => setSort('port')}
                  className="hidden sm:table-cell"
                >
                  端口
                </SortHeader>
                <th className="w-24 py-2.5 pr-3 text-right font-normal">操作</th>
                <SortHeader
                  active={sort === 'updated'}
                  onClick={() => setSort('updated')}
                  className="hidden pr-4 text-right lg:table-cell"
                >
                  更新
                </SortHeader>
              </tr>
            </thead>
            <tbody>
              {rows.map(
                ({ service, ports, runtimeActive, runtimeUnknown, managed, external, pid }) => {
                  const startPending =
                    startMut.isPending && startMut.variables === service.id
                  const stopPending = stopMut.isPending && stopMut.variables === service.id
                  const processBusy = startPending || stopPending
                  const hasStartCommand = Boolean(service.start_command?.trim())
                  const rowError =
                    actionError?.serviceId === service.id ? actionError.message : null

                  return (
                    <tr
                      key={service.id}
                      className="group border-b border-line-soft/60 transition-colors last:border-0 hover:bg-hover/60"
                    >
                      <td className="py-2.5 pl-4 pr-3 align-middle">
                        <StatusBadge
                          live={runtimeActive}
                          liveLabel={managed ? 'APR 托管' : external ? '外部运行' : '运行中'}
                          idleLabel={runtimeUnknown ? '状态未知' : '未运行'}
                        />
                        {external && (
                          <div className="mt-1 flex items-center gap-1 whitespace-nowrap text-[10px] text-idle">
                            <Eye size={10} />
                            APR 仅监测{pid ? ` · ${pid}` : ''}
                          </div>
                        )}
                        {managed && pid && (
                          <div className="mt-1 whitespace-nowrap font-mono text-[10px] text-faint">
                            pid {pid}
                          </div>
                        )}
                      </td>
                      <td className="min-w-0 py-2.5 pr-3">
                        <Link to={`/services/${service.id}`} className="block min-w-0">
                          <div className="truncate transition-colors group-hover:text-brand">
                            {service.name}
                          </div>
                          <div className="truncate font-mono text-[11px] text-faint">
                            {service.service_key}
                            {service.instance_key !== 'default' && `:${service.instance_key}`}
                          </div>
                        </Link>
                      </td>
                      <td className="hidden py-2.5 pr-3 text-xs text-muted md:table-cell">
                        <div className="truncate">{serviceProjectKey(service)}</div>
                        <div className="truncate text-[11px] text-faint">
                          {serviceAgentLabel(service)}
                        </div>
                      </td>
                      <td className="hidden py-2.5 pr-3 sm:table-cell">
                        <div className="flex flex-wrap gap-1">
                          {ports.length === 0 ? (
                            <span className="text-xs text-faint">无</span>
                          ) : shouldSummarizePorts(ports) ? (
                            <PortSummary ports={ports} />
                          ) : (
                            ports.map((p) => {
                              const portLive = listeners.has(p.port)
                              return portLive ? (
                                <a
                                  key={p.port}
                                  href={`http://127.0.0.1:${p.port}`}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="chip inline-flex items-center gap-1 border-live/30 text-live transition-colors hover:border-live/60 hover:bg-live/10"
                                  title={`打开 http://127.0.0.1:${p.port} · ${p.label}`}
                                >
                                  {p.port}
                                  <ExternalLink size={11} aria-hidden="true" />
                                </a>
                              ) : (
                                <span
                                  key={p.port}
                                  className="chip"
                                  title={`${p.label} = ${p.port}`}
                                >
                                  {p.port}
                                </span>
                              )
                            })
                          )}
                        </div>
                      </td>
                      <td className="py-2.5 pr-3 text-right align-middle">
                        {managed ? (
                          <Button
                            variant="danger"
                            className="min-w-[72px] px-2"
                            onClick={() => stopMut.mutate(service.id)}
                            disabled={!pmEnabled || processBusy}
                            title={pmEnabled ? '停止 APR 托管进程' : '进程管理未开启'}
                          >
                            {stopPending ? (
                              <LoaderCircle size={14} className="animate-spin" />
                            ) : (
                              <Square size={14} />
                            )}
                            {stopPending ? '停止中' : '停止'}
                          </Button>
                        ) : external ? (
                          <Button
                            variant="secondary"
                            className="min-w-[72px] px-2"
                            disabled
                            title="该进程不是由 APR 启动，APR 不能停止它"
                          >
                            <Square size={14} />
                            停止
                          </Button>
                        ) : (
                          <Button
                            variant="primary"
                            className="min-w-[72px] px-2"
                            onClick={() => startMut.mutate(service.id)}
                            disabled={!pmEnabled || !hasStartCommand || processBusy}
                            title={
                              !pmEnabled
                                ? '进程管理未开启'
                                : !hasStartCommand
                                  ? '未配置启动命令'
                                  : '通过 APR 启动服务'
                            }
                          >
                            {startPending ? (
                              <LoaderCircle size={14} className="animate-spin" />
                            ) : (
                              <Play size={14} />
                            )}
                            {startPending ? '启动中' : '启动'}
                          </Button>
                        )}
                        {rowError && (
                          <div className="mt-1 max-w-36 text-right text-[10px] leading-tight text-danger">
                            {rowError}
                          </div>
                        )}
                      </td>
                      <td className="hidden py-2.5 pr-4 text-right text-xs text-faint lg:table-cell">
                        {relativeTime(service.updated_at)}
                      </td>
                    </tr>
                  )
                },
              )}
            </tbody>
          </table>
        )}
      </Panel>

      {rows.length > 0 && (
        <div className="px-1 text-xs text-faint">
          共 {rows.length} 个服务
          {services.data && rows.length !== services.data.length
            ? ` · 已从 ${services.data.length} 个中筛选`
            : ''}
        </div>
      )}

      <EnsureForm open={ensureOpen} onClose={() => setEnsureOpen(false)} />
    </div>
  )
}

function SortHeader({
  children,
  active,
  onClick,
  className = '',
}: {
  children: React.ReactNode
  active: boolean
  onClick: () => void
  className?: string
}) {
  return (
    <th className={`py-2.5 pr-3 font-normal ${className}`}>
      <button
        type="button"
        onClick={onClick}
        className={`transition-colors hover:text-fg ${active ? 'text-brand' : ''}`}
      >
        {children}
      </button>
    </th>
  )
}
