import { Network } from 'lucide-react'

export const PORT_SUMMARY_THRESHOLD = 6

export interface SummaryPort {
  port: number
  label: string
}

export function shouldSummarizePorts(ports: SummaryPort[]): boolean {
  return ports.length > PORT_SUMMARY_THRESHOLD
}

export function portSummaryLabel(ports: SummaryPort[]): string {
  if (ports.length === 0) return '无端口'

  const sorted = [...ports].sort((a, b) => a.port - b.port)
  const first = sorted[0].port
  const last = sorted[sorted.length - 1].port
  const groups = new Set(sorted.map((port) => port.label)).size
  const groupLabel = groups > 1 && groups < sorted.length ? ` · ${groups} 组` : ''
  const rangeLabel = first === last ? String(first) : `${first}…${last}`
  return `${sorted.length} 个端口${groupLabel} · ${rangeLabel}`
}

export default function PortSummary({
  ports,
  className = '',
}: {
  ports: SummaryPort[]
  className?: string
}) {
  const label = portSummaryLabel(ports)
  return (
    <span
      data-testid="port-summary"
      className={`inline-flex max-w-full items-center gap-1.5 rounded border border-line-soft bg-raised px-2 py-1 font-mono text-[11px] text-muted ${className}`}
      title={label}
    >
      <Network size={12} className="shrink-0" aria-hidden="true" />
      <span className="truncate">{label}</span>
    </span>
  )
}
