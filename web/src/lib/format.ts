import type { Allocation, Service } from './api'

/** "3 分钟前" / "刚刚" — registry timestamps are ISO-8601 UTC. */
export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const then = Date.parse(iso)
  if (Number.isNaN(then)) return iso
  const seconds = Math.round((Date.now() - then) / 1000)
  if (seconds < 45) return '刚刚'
  const units: [number, string][] = [
    [60, '分钟'],
    [24, '小时'],
    [30, '天'],
    [12, '个月'],
  ]
  let value = seconds / 60
  let label = '分钟'
  for (let i = 0; i < units.length; i += 1) {
    if (value < units[i][0]) {
      label = units[i][1]
      break
    }
    value /= units[i][0]
    label = units[i + 1]?.[1] ?? '年'
  }
  return `${Math.round(value)} ${label}前`
}

export function absoluteTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const ms = Date.parse(iso)
  if (Number.isNaN(ms)) return iso
  return new Date(ms).toLocaleString('zh-CN', { hour12: false })
}

export function percent(value: number, digits = 2): string {
  return `${(value * 100).toFixed(digits)}%`
}

/** Compact count formatting for KPI tiles (20000 -> 20,000). */
export function count(n: number): string {
  return n.toLocaleString('en-US')
}

export function reservedAllocations(service: Service): Allocation[] {
  return service.allocations.filter((a) => a.state === 'reserved')
}

export interface PortRow {
  port: number
  label: string
  service: Service
  allocation: Allocation
}

/** Flatten every reserved port across services into one sortable list. */
export function portRows(services: Service[]): PortRow[] {
  const rows: PortRow[] = []
  for (const service of services) {
    for (const allocation of reservedAllocations(service)) {
      for (const p of allocation.ports) {
        rows.push({
          port: p.port,
          label: p.port_name ?? p.resource_name,
          service,
          allocation,
        })
      }
    }
  }
  return rows.sort((a, b) => a.port - b.port)
}

/** Ports of a service that are currently reserved, sorted. */
export function servicePorts(service: Service): { port: number; label: string }[] {
  return reservedAllocations(service)
    .flatMap((a) => a.ports.map((p) => ({ port: p.port, label: p.port_name ?? p.resource_name })))
    .sort((a, b) => a.port - b.port)
}

/** Project label across local records and SSH node snapshots. */
export function serviceProjectKey(service: Service): string {
  return service.project_key || service.agent_project_key || service.agent_project_id || '-'
}

/** Registration actor across local records and SSH node snapshots. */
export function serviceAgentLabel(service: Service): string {
  return service.registered_by_agent || service.agent_type || 'human'
}

/** Trim a long command for single-line display without hiding the tail. */
export function truncateMiddle(text: string, max = 72): string {
  if (text.length <= max) return text
  const head = Math.ceil((max - 1) / 2)
  const tail = Math.floor((max - 1) / 2)
  return `${text.slice(0, head)}…${text.slice(text.length - tail)}`
}
