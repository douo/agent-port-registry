import type { ReactNode } from 'react'

export function Panel({
  children,
  className = '',
}: {
  children: ReactNode
  className?: string
}) {
  return <div className={`panel ${className}`}>{children}</div>
}

export function PanelHeader({
  title,
  hint,
  action,
}: {
  title: string
  hint?: string
  action?: ReactNode
}) {
  return (
    <div className="flex items-baseline gap-3 border-b border-line-soft px-4 py-3">
      <h2 className="text-sm font-medium">{title}</h2>
      {hint && <span className="text-xs text-faint">{hint}</span>}
      {action && <div className="ml-auto">{action}</div>}
    </div>
  )
}

export function StatCard({
  label,
  value,
  sub,
  tone = 'default',
}: {
  label: string
  value: ReactNode
  sub?: ReactNode
  tone?: 'default' | 'live' | 'idle' | 'brand'
}) {
  const toneClass = {
    default: 'text-fg',
    live: 'text-live',
    idle: 'text-idle',
    brand: 'text-brand',
  }[tone]

  return (
    <div className="panel px-4 py-3.5">
      <div className="text-xs text-muted">{label}</div>
      <div className={`mt-1.5 font-mono text-2xl leading-none ${toneClass}`}>{value}</div>
      {sub && <div className="mt-1.5 text-[11px] text-faint">{sub}</div>}
    </div>
  )
}

/** live = something is listening, idle = claimed but nothing bound. */
export function StatusDot({ live }: { live: boolean }) {
  return (
    <span
      title={live ? '端口有进程在监听' : '已登记但无进程监听'}
      className={[
        'inline-block h-1.5 w-1.5 shrink-0 rounded-full',
        live ? 'bg-live' : 'bg-idle/70',
      ].join(' ')}
    />
  )
}

export function Loading({ label = '加载中…' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 px-4 py-10 text-sm text-faint">
      <span className="h-3 w-3 animate-spin rounded-full border border-line border-t-brand" />
      {label}
    </div>
  )
}

export function ErrorNote({ error }: { error: unknown }) {
  const message =
    error && typeof error === 'object' && 'label' in error
      ? String((error as { label: string }).label)
      : String(error)
  return (
    <div className="panel border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
      {message}
    </div>
  )
}

export function Empty({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="px-4 py-14 text-center">
      <div className="text-sm text-muted">{title}</div>
      {hint && <div className="mt-1.5 text-xs text-faint">{hint}</div>}
    </div>
  )
}

/** Thin labelled meter used for per-project / per-agent breakdowns. */
export function Meter({
  label,
  value,
  total,
}: {
  label: string
  value: number
  total: number
}) {
  const pct = total > 0 ? (value / total) * 100 : 0
  return (
    <div className="flex items-center gap-3">
      <div className="w-32 shrink-0 truncate text-xs text-muted" title={label}>
        {label}
      </div>
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-raised">
        <div
          className="h-full rounded-full bg-brand/70 transition-all"
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="w-8 shrink-0 text-right font-mono text-xs text-muted">{value}</div>
    </div>
  )
}
