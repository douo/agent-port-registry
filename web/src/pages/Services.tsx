import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Search } from 'lucide-react'
import { api, queryKeys } from '../lib/api'
import { relativeTime, servicePorts } from '../lib/format'
import { Empty, ErrorNote, Loading, Panel, StatusDot } from '../components/ui'

type SortKey = 'port' | 'name' | 'project' | 'updated'

export default function Services() {
  const [query, setQuery] = useState('')
  const [project, setProject] = useState<string | null>(null)
  const [sort, setSort] = useState<SortKey>('port')

  const services = useQuery({ queryKey: queryKeys.services, queryFn: api.services })
  const pool = useQuery({ queryKey: queryKeys.pool, queryFn: api.pool })
  const listening = useMemo(
    () => new Set(pool.data?.listening_in_pool ?? []),
    [pool.data],
  )

  const projects = useMemo(() => {
    const names = new Set((services.data ?? []).map((s) => s.agent_project_key))
    return [...names].sort()
  }, [services.data])

  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return (services.data ?? [])
      .map((service) => {
        const ports = servicePorts(service)
        return { service, ports, live: ports.some((p) => listening.has(p.port)) }
      })
      .filter(({ service, ports }) => {
        if (project && service.agent_project_key !== project) return false
        if (!needle) return true
        return [
          service.name,
          service.service_key,
          service.instance_key,
          service.agent_project_key,
          service.agent_type_key,
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
              a.service.agent_project_key.localeCompare(b.service.agent_project_key) ||
              a.service.name.localeCompare(b.service.name, 'zh-CN')
            )
          case 'updated':
            return b.service.updated_at.localeCompare(a.service.updated_at)
          default:
            return (a.ports[0]?.port ?? Infinity) - (b.ports[0]?.port ?? Infinity)
        }
      })
  }, [services.data, query, project, sort, listening])

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

        <div className="flex flex-wrap items-center gap-1.5">
          <FilterChip active={project === null} onClick={() => setProject(null)}>
            全部
          </FilterChip>
          {projects.map((name) => (
            <FilterChip
              key={name}
              active={project === name}
              onClick={() => setProject(project === name ? null : name)}
            >
              {name}
            </FilterChip>
          ))}
        </div>
      </div>

      <Panel className="overflow-hidden">
        {services.isLoading ? (
          <Loading />
        ) : rows.length === 0 ? (
          <Empty
            title={query || project ? '没有匹配的服务' : '还没有登记任何服务'}
            hint={
              query || project
                ? '换个关键词，或清除项目筛选'
                : '用 svcctl ensure 申请端口后会自动出现在这里'
            }
          />
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-line-soft text-left text-xs text-faint">
                <th className="w-8 py-2.5 pl-4" />
                <SortHeader active={sort === 'name'} onClick={() => setSort('name')}>
                  服务
                </SortHeader>
                <SortHeader
                  active={sort === 'project'}
                  onClick={() => setSort('project')}
                  className="hidden md:table-cell"
                >
                  项目 / Agent
                </SortHeader>
                <SortHeader active={sort === 'port'} onClick={() => setSort('port')}>
                  端口
                </SortHeader>
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
              {rows.map(({ service, ports, live }) => (
                <tr
                  key={service.id}
                  className="group border-b border-line-soft/60 transition-colors last:border-0 hover:bg-hover/60"
                >
                  <td className="py-2.5 pl-4 align-middle">
                    <StatusDot live={live} />
                  </td>
                  <td className="py-2.5 pr-3">
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
                    <div className="truncate">{service.agent_project_key}</div>
                    <div className="truncate text-[11px] text-faint">
                      {service.agent_type_key}
                    </div>
                  </td>
                  <td className="py-2.5 pr-3">
                    <div className="flex flex-wrap gap-1">
                      {ports.length === 0 ? (
                        <span className="text-xs text-faint">无</span>
                      ) : (
                        ports.map((p) => (
                          <span
                            key={p.port}
                            className="chip"
                            title={`${p.label} = ${p.port}`}
                          >
                            {p.port}
                          </span>
                        ))
                      )}
                    </div>
                  </td>
                  <td className="hidden py-2.5 pr-4 text-right text-xs text-faint lg:table-cell">
                    {relativeTime(service.updated_at)}
                  </td>
                </tr>
              ))}
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
    </div>
  )
}

function FilterChip({
  children,
  active,
  onClick,
}: {
  children: React.ReactNode
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        'rounded-full border px-2.5 py-1 text-xs transition-colors',
        active
          ? 'border-brand/50 bg-brand/15 text-brand'
          : 'border-line-soft text-muted hover:border-line hover:text-fg',
      ].join(' ')}
    >
      {children}
    </button>
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
