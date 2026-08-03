import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { api, queryKeys } from '../lib/api'
import { portRows, serviceProjectKey, truncateMiddle } from '../lib/format'
import { Empty, ErrorNote, Loading, Panel, PanelHeader, StatusDot } from '../components/ui'

export default function Ports() {
  const [lookup, setLookup] = useState('')

  const services = useQuery({ queryKey: queryKeys.services, queryFn: api.services })
  const pool = useQuery({ queryKey: queryKeys.pool, queryFn: api.pool })
  const listenersQuery = useQuery({
    queryKey: queryKeys.listeners,
    queryFn: () => api.listeners(),
  })

  const rows = useMemo(() => portRows(services.data ?? []), [services.data])
  const listeners = useMemo(
    () => new Map((listenersQuery.data ?? []).map((l) => [l.port, l])),
    [listenersQuery.data],
  )

  const registered = useMemo(() => new Set(rows.map((r) => r.port)), [rows])

  /** Listening inside the pool but unknown to the registry: squatters. */
  const unregistered = useMemo(() => {
    if (!pool.data) return []
    return pool.data.listening_in_pool
      .filter((port) => !registered.has(port))
      .map((port) => ({ port, listener: listeners.get(port) }))
  }, [pool.data, registered, listeners])

  const needle = lookup.trim()
  const filtered = needle
    ? rows.filter(
        (r) =>
          String(r.port).includes(needle) ||
          r.service.name.toLowerCase().includes(needle.toLowerCase()),
      )
    : rows

  if (services.isError) return <ErrorNote error={services.error} />

  return (
    <div className="space-y-5">
      <div className="relative max-w-sm">
        <Search
          size={14}
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint"
        />
        <input
          value={lookup}
          onChange={(e) => setLookup(e.target.value)}
          placeholder="反查端口号或服务名"
          inputMode="numeric"
          className="w-full rounded-lg border border-line-soft bg-panel py-2 pl-9 pr-3 text-sm outline-none transition-colors placeholder:text-faint focus:border-brand/60"
        />
      </div>

      <Panel className="overflow-hidden">
        <PanelHeader
          title="已登记端口"
          hint={`${filtered.length}${filtered.length !== rows.length ? ` / ${rows.length}` : ''}`}
        />
        {services.isLoading ? (
          <Loading />
        ) : filtered.length === 0 ? (
          <Empty title={needle ? '没有匹配的端口' : '还没有分配任何端口'} />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line-soft text-left text-xs text-faint">
                <th className="w-8 py-2 pl-4" />
                <th className="py-2 pr-3 font-normal">端口</th>
                <th className="py-2 pr-3 font-normal">服务</th>
                <th className="hidden py-2 pr-3 font-normal sm:table-cell">资源</th>
                <th className="hidden py-2 pr-4 font-normal lg:table-cell">进程</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((row) => {
                const listener = listeners.get(row.port)
                return (
                  <tr
                    key={`${row.allocation.id}-${row.port}`}
                    className="group border-b border-line-soft/60 transition-colors last:border-0 hover:bg-hover/60"
                  >
                    <td className="py-2.5 pl-4">
                      <StatusDot live={Boolean(listener)} />
                    </td>
                    <td className="py-2.5 pr-3">
                      <a
                        href={`http://127.0.0.1:${row.port}`}
                        target="_blank"
                        rel="noreferrer"
                        className="chip transition-colors hover:border-brand/50 hover:text-brand"
                      >
                        {row.port}
                      </a>
                    </td>
                    <td className="min-w-0 py-2.5 pr-3">
                      <Link
                        to={`/services/${row.service.id}`}
                        className="block truncate transition-colors group-hover:text-brand"
                      >
                        {row.service.name}
                      </Link>
                      <div className="truncate text-[11px] text-faint">
                        {serviceProjectKey(row.service)}
                      </div>
                    </td>
                    <td className="hidden py-2.5 pr-3 font-mono text-xs text-muted sm:table-cell">
                      {row.label}
                    </td>
                    <td
                      className="hidden max-w-sm truncate py-2.5 pr-4 font-mono text-[11px] text-faint lg:table-cell"
                      title={listener?.command ?? ''}
                    >
                      {listener?.command ? truncateMiddle(listener.command, 60) : '—'}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </Panel>

      <Panel className="overflow-hidden">
        <PanelHeader
          title="池内未登记监听"
          hint="有进程占用端口池，但没有在 APR 登记"
        />
        {pool.isLoading ? (
          <Loading />
        ) : unregistered.length === 0 ? (
          <Empty title="端口池内没有未登记的监听进程" />
        ) : (
          <ul className="divide-y divide-line-soft">
            {unregistered.map(({ port, listener }) => (
              <li key={port} className="flex items-center gap-3 px-4 py-2.5 text-sm">
                <span className="chip">{port}</span>
                <span
                  className="min-w-0 flex-1 truncate font-mono text-[11px] text-faint"
                  title={listener?.command ?? ''}
                >
                  {listener?.command ? truncateMiddle(listener.command, 80) : '未知进程'}
                </span>
                {listener?.pid && (
                  <span className="shrink-0 text-[11px] text-faint">
                    pid {listener.pid}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  )
}
