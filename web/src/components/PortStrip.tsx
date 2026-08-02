import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import type { Pool } from '../lib/api'
import type { PortRow } from '../lib/format'

/** Detail strip renders one cell per port; cap it so the DOM stays sane. */
const MAX_DETAIL_CELLS = 320
const MIN_DETAIL_CELLS = 64
const PADDING_PORTS = 4

interface Props {
  pool: Pool
  rows: PortRow[]
  listening: Set<number>
}

function expandRanges(ranges: [number, number][], lo: number, hi: number): Set<number> {
  const out = new Set<number>()
  for (const [a, b] of ranges) {
    if (b < lo || a > hi) continue
    for (let p = Math.max(a, lo); p <= Math.min(b, hi); p += 1) out.add(p)
  }
  return out
}

/**
 * Two-level port map.
 *
 * The pool is typically 20 000 ports wide with a handful claimed at the very
 * bottom, so a single full-range strip would be 99.9% empty and tell you
 * nothing. Instead: a full-range overview bar showing *where* the action is,
 * plus a zoomed strip over the occupied window showing *what* is there.
 */
export default function PortStrip({ pool, rows, listening }: Props) {
  const byPort = useMemo(() => new Map(rows.map((r) => [r.port, r])), [rows])
  const claimedSet = useMemo(() => new Set(pool.claimed), [pool.claimed])

  const view = useMemo(() => {
    const span = Math.max(1, pool.end - pool.start + 1)
    if (pool.claimed.length === 0) {
      const hi = Math.min(pool.end, pool.start + MIN_DETAIL_CELLS - 1)
      return { lo: pool.start, hi, span, truncated: false }
    }
    const min = pool.claimed[0]
    const max = pool.claimed[pool.claimed.length - 1]
    const lo = Math.max(pool.start, min - PADDING_PORTS)
    let hi = Math.min(pool.end, max + PADDING_PORTS)
    if (hi - lo + 1 < MIN_DETAIL_CELLS) {
      hi = Math.min(pool.end, lo + MIN_DETAIL_CELLS - 1)
    }
    const truncated = hi - lo + 1 > MAX_DETAIL_CELLS
    if (truncated) hi = lo + MAX_DETAIL_CELLS - 1
    return { lo, hi, span, truncated }
  }, [pool])

  const excludedInView = useMemo(
    () => expandRanges(pool.excluded_ranges, view.lo, view.hi),
    [pool.excluded_ranges, view.lo, view.hi],
  )

  const cells: number[] = []
  for (let p = view.lo; p <= view.hi; p += 1) cells.push(p)

  const pct = (port: number) => ((port - pool.start) / view.span) * 100

  return (
    <div className="space-y-4 px-4 py-4">
      {/* ------------------------------------------------ full-range overview */}
      <div>
        <div className="mb-1.5 flex items-baseline justify-between text-[11px] text-faint">
          <span className="font-mono">{pool.start}</span>
          <span>端口池全域（{pool.usable.toLocaleString('en-US')} 个可用）</span>
          <span className="font-mono">{pool.end}</span>
        </div>
        <div className="relative h-6 overflow-hidden rounded-md bg-raised">
          {pool.excluded_ranges.map(([a, b]) => (
            <div
              key={`ex-${a}`}
              title={`排除 ${a}–${b}`}
              className="absolute inset-y-0 bg-danger/20"
              style={{ left: `${pct(a)}%`, width: `${Math.max(0.15, ((b - a + 1) / view.span) * 100)}%` }}
            />
          ))}
          {pool.claimed_ranges.map(([a, b]) => (
            <div
              key={`cl-${a}`}
              title={`已分配 ${a}–${b}`}
              className="absolute inset-y-0 min-w-[2px] bg-brand"
              style={{ left: `${pct(a)}%`, width: `${((b - a + 1) / view.span) * 100}%` }}
            />
          ))}
          {/* Where the zoomed strip below is looking. */}
          <div
            className="absolute inset-y-0 min-w-[3px] border-x border-fg/60 bg-fg/10"
            style={{
              left: `${pct(view.lo)}%`,
              width: `${((view.hi - view.lo + 1) / view.span) * 100}%`,
            }}
          />
        </div>
      </div>

      {/* ------------------------------------------------------- zoomed strip */}
      <div>
        <div className="mb-1.5 flex items-baseline justify-between text-[11px] text-faint">
          <span className="font-mono">{view.lo}</span>
          <span>
            聚焦窗口
            {view.truncated && ' · 已截断'}
          </span>
          <span className="font-mono">{view.hi}</span>
        </div>
        <div
          className="grid gap-[3px]"
          style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(10px, 1fr))' }}
        >
          {cells.map((port) => {
            const row = byPort.get(port)
            const claimed = claimedSet.has(port)
            const live = listening.has(port)
            const excluded = excludedInView.has(port)

            const tone = excluded
              ? 'bg-danger/25'
              : claimed && live
                ? 'bg-live'
                : claimed
                  ? 'bg-idle/80'
                  : 'bg-raised'

            const title = excluded
              ? `${port} · 已排除`
              : row
                ? `${port} · ${row.service.name} (${row.label}) · ${live ? '监听中' : '无监听'}`
                : claimed
                  ? `${port} · 已分配`
                  : `${port} · 空闲`

            const cell = (
              <div
                title={title}
                className={`h-3.5 rounded-[2px] ${tone} ${
                  claimed ? 'ring-1 ring-inset ring-black/30' : ''
                }`}
              />
            )

            return row ? (
              <Link key={port} to={`/services/${row.service.id}`} aria-label={title}>
                {cell}
              </Link>
            ) : (
              <div key={port}>{cell}</div>
            )
          })}
        </div>
      </div>

      <Legend />
    </div>
  )
}

function Legend() {
  const items: [string, string][] = [
    ['bg-live', '监听中'],
    ['bg-idle/80', '已分配未监听'],
    ['bg-raised', '空闲'],
    ['bg-danger/25', '已排除'],
  ]
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-[11px] text-faint">
      {items.map(([tone, label]) => (
        <span key={label} className="flex items-center gap-1.5">
          <span className={`h-2.5 w-2.5 rounded-[2px] ${tone}`} />
          {label}
        </span>
      ))}
    </div>
  )
}
