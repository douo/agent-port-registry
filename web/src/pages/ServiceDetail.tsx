import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Terminal } from 'lucide-react'
import { api, queryKeys } from '../lib/api'
import { absoluteTime, relativeTime } from '../lib/format'
import { ErrorNote, Loading, Panel, PanelHeader, StatusDot } from '../components/ui'

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
  const service = useQuery({
    queryKey: queryKeys.service(id),
    queryFn: () => api.service(id),
    enabled: Boolean(id),
  })
  const listenersQuery = useQuery({
    queryKey: queryKeys.listeners,
    queryFn: () => api.listeners(),
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
          <StatusDot live={anyLive} />
          <h2 className="text-xl">{s.name}</h2>
          <span className="chip">{s.id}</span>
        </div>
        {s.description && <p className="mt-2 text-sm text-muted">{s.description}</p>}
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
    </div>
  )
}
