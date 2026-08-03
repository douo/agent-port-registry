import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { AlertTriangle } from 'lucide-react'
import { api, queryKeys } from '../lib/api'
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
