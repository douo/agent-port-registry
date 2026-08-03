import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { AlertTriangle, ExternalLink } from 'lucide-react'
import { api, queryKeys, type OverviewForward } from '../lib/api'
import { count, percent, portRows, serviceProjectKey } from '../lib/format'
import PortStrip from '../components/PortStrip'
import {
  Empty,
  ErrorNote,
  Loading,
  Meter,
  Panel,
  PanelHeader,
  StatCard,
  StatusDot,
} from '../components/ui'

export default function Dashboard() {
  const overview = useQuery({ queryKey: queryKeys.overview, queryFn: api.overview })
  const pool = useQuery({ queryKey: queryKeys.pool, queryFn: api.pool })
  const services = useQuery({ queryKey: queryKeys.services, queryFn: api.services })

  if (overview.isError) return <ErrorNote error={overview.error} />
  if (!overview.data) return <Loading />

  const o = overview.data
  const rows = services.data ? portRows(services.data) : []
  const listening = new Set(pool.data?.listening_in_pool ?? [])

  const projects = Object.entries(o.services.by_project).sort((a, b) => b[1] - a[1])
  const agents = Object.entries(o.services.by_agent).sort((a, b) => b[1] - a[1])
  const forwardedServices = o.forwards.items.filter((f) => f.service)
  // Forwards matched to a slave snapshot service belong to the slave-node
  // panel below; this panel only shows the remaining raw tunnel rules.
  const plainForwards = o.forwards.items.filter((f) => !f.service)

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <StatCard
          label="服务"
          value={count(o.services.total)}
          sub={`${projects.length} 个项目 · ${agents.length} 类 Agent`}
        />
        <StatCard
          label="已分配端口"
          value={count(o.ports.claimed)}
          tone="brand"
          sub={`${o.allocations.reserved} 个生效分配`}
        />
        <StatCard
          label="监听中"
          value={count(o.ports.live)}
          tone={o.ports.live > 0 ? 'live' : 'default'}
          sub={`${o.ports.idle} 个已登记但未运行`}
        />
        <StatCard
          label="池利用率"
          value={percent(o.pool.utilization, 3)}
          sub={`剩余 ${count(o.pool.free)} / ${count(o.pool.usable)}`}
        />
      </div>

      <Panel className="overflow-hidden">
        <PanelHeader
          title="当前监听的服务"
          hint={o.listening.length ? `${o.listening.length} 个端口` : undefined}
        />
        {o.listening.length === 0 ? (
          <Empty title="还没有服务在监听" hint="登记的服务启动后会自动出现在这里" />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line-soft text-left text-xs text-faint">
                <th className="w-8 py-2 pl-4" />
                <th className="py-2 pr-3 font-normal">端口</th>
                <th className="py-2 pr-3 font-normal">服务</th>
                <th className="hidden py-2 pr-4 font-normal sm:table-cell">项目</th>
              </tr>
            </thead>
            <tbody>
              {o.listening.map((item) => (
                <tr
                  key={item.port}
                  className="group border-b border-line-soft/60 transition-colors last:border-0 hover:bg-hover/60"
                >
                  <td className="py-2.5 pl-4">
                    <StatusDot live />
                  </td>
                  <td className="py-2.5 pr-3">
                    <a
                      href={`http://127.0.0.1:${item.port}`}
                      target="_blank"
                      rel="noreferrer"
                      className="chip inline-flex items-center gap-1 transition-colors hover:border-brand/50 hover:text-brand"
                    >
                      {item.port}
                      <ExternalLink size={10} />
                    </a>
                  </td>
                  <td className="min-w-0 py-2.5 pr-3">
                    {item.service_id ? (
                      <Link
                        to={`/services/${item.service_id}`}
                        className="block truncate transition-colors group-hover:text-brand"
                      >
                        {item.service_name}
                      </Link>
                    ) : (
                      <span className="text-faint">
                        {item.service_name ?? '未知服务'}
                      </span>
                    )}
                    {item.label && (
                      <div className="truncate text-[11px] text-faint">{item.label}</div>
                    )}
                  </td>
                  <td className="hidden py-2.5 pr-4 text-xs text-faint sm:table-cell">
                    {item.project_key ?? '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel>
          <PanelHeader
            title="转发的端口"
            hint={plainForwards.length ? `${plainForwards.length} 条` : undefined}
            action={
              <Link
                to="/nodes"
                className="text-xs text-brand transition-colors hover:underline"
              >
                管理
              </Link>
            }
          />
          {plainForwards.length === 0 ? (
            <Empty
              title="没有独立的转发端口"
              hint="关联到从节点服务的转发在右侧「子节点转发的服务」里"
            />
          ) : (
            <ul className="divide-y divide-line-soft">
              {plainForwards.map((f) => (
                <ForwardRow key={f.id} fwd={f} />
              ))}
            </ul>
          )}
        </Panel>

        <Panel>
          <PanelHeader
            title="子节点转发的服务"
            hint={forwardedServices.length ? `${forwardedServices.length} 个` : undefined}
          />
          {forwardedServices.length === 0 ? (
            <Empty
              title="还没有关联到从节点服务的转发"
              hint="转发目标出现在从节点快照后会自动显示服务名"
            />
          ) : (
            <ul className="divide-y divide-line-soft">
              {forwardedServices.map((f) => {
                const service = f.service
                return (
                  <li
                    key={f.id}
                    className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-sm"
                  >
                    <ForwardPortChip fwd={f} />
                    <div className="min-w-0 flex-1">
                      {service?.id ? (
                        <Link
                          to={`/nodes/${f.node_id}/services/${service.id}`}
                          className="block truncate font-medium transition-colors hover:text-brand"
                        >
                          {service.name}
                        </Link>
                      ) : (
                        <span className="text-faint">{service?.name ?? '未知服务'}</span>
                      )}
                      <div className="truncate text-[11px] text-faint">
                        <Link
                          to={`/nodes/${f.node_id}`}
                          className="transition-colors hover:text-brand"
                        >
                          {f.node_name ?? f.node_id}
                        </Link>
                        {' · 远端 '}
                        {f.remote_host}:{f.remote_port}
                      </div>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </Panel>
      </div>

      <Panel>
        <PanelHeader
          title="端口分布"
          hint={pool.data ? `${pool.data.start}–${pool.data.end}` : undefined}
        />
        {pool.isError ? (
          <ErrorNote error={pool.error} />
        ) : pool.data ? (
          <PortStrip pool={pool.data} rows={rows} listening={listening} />
        ) : (
          <Loading />
        )}
      </Panel>

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel>
          <PanelHeader title="按项目分布" />
          <div className="space-y-2.5 px-4 py-4">
            {projects.length === 0 ? (
              <Empty title="还没有登记任何服务" />
            ) : (
              projects.map(([name, n]) => (
                <Meter key={name} label={name} value={n} total={o.services.total} />
              ))
            )}
          </div>
        </Panel>

        <Panel>
          <PanelHeader
            title="已分配但无监听"
            hint="登记了端口，进程却没在跑"
            action={
              o.ports.idle > 0 ? (
                <span className="flex items-center gap-1.5 text-xs text-idle">
                  <AlertTriangle size={13} />
                  {o.ports.idle}
                </span>
              ) : undefined
            }
          />
          {o.ports.idle_ports.length === 0 ? (
            <Empty title="所有已分配端口都有进程在监听" />
          ) : (
            <ul className="divide-y divide-line-soft">
              {o.ports.idle_ports.map((port) => {
                const row = rows.find((r) => r.port === port)
                return (
                  <li key={port} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                    <span className="chip">{port}</span>
                    {row ? (
                      <Link
                        to={`/services/${row.service.id}`}
                        className="truncate text-muted transition-colors hover:text-fg"
                      >
                        {row.service.name}
                      </Link>
                    ) : (
                      <span className="text-faint">未知服务</span>
                    )}
                    {row && (
                      <span className="ml-auto shrink-0 text-[11px] text-faint">
                        {serviceProjectKey(row.service)}
                      </span>
                    )}
                  </li>
                )
              })}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  )
}

function ForwardRow({ fwd }: { fwd: OverviewForward }) {
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2.5 text-sm">
      <ForwardPortChip fwd={fwd} />
      <div className="min-w-0 flex-1">
        <Link
          to={`/nodes/${fwd.node_id}`}
          className="block truncate font-medium transition-colors hover:text-brand"
        >
          {fwd.node_name ?? fwd.node_id}
        </Link>
        <div className="truncate font-mono text-[11px] text-faint">
          localhost:{fwd.local_port} → {fwd.remote_host}:{fwd.remote_port}
          {fwd.ssh_host ? ` via ${fwd.ssh_host}` : ''}
        </div>
      </div>
      <span
        className={
          fwd.state === 'active' ? 'text-xs text-live' : 'text-xs text-idle'
        }
      >
        {forwardStateLabel(fwd.state)}
      </span>
    </li>
  )
}

function ForwardPortChip({ fwd }: { fwd: OverviewForward }) {
  const className =
    'chip inline-flex items-center gap-1 transition-colors hover:border-brand/50 hover:text-brand'
  if (fwd.state === 'active') {
    return (
      <a
        href={fwd.local_url}
        target="_blank"
        rel="noreferrer"
        title={`打开 localhost:${fwd.local_port}`}
        className={className}
      >
        {fwd.local_port}
        <ExternalLink size={10} />
      </a>
    )
  }
  return <span className="chip">{fwd.local_port}</span>
}

function forwardStateLabel(state: OverviewForward['state']) {
  if (state === 'active') return '运行中'
  if (state === 'starting') return '启动中'
  if (state === 'reconnecting') return '等待主机恢复'
  if (state === 'failed') return '恢复失败'
  return '已停止'
}
