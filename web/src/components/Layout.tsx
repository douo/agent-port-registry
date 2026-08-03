import { useEffect, useState } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Boxes, LayoutDashboard, Network, Search, Server } from 'lucide-react'
import { api, queryKeys } from '../lib/api'
import CommandPalette from './CommandPalette'

const NAV = [
  { to: '/', label: '概览', icon: LayoutDashboard, end: true },
  { to: '/services', label: '服务', icon: Boxes, end: false },
  { to: '/ports', label: '端口', icon: Network, end: false },
  { to: '/nodes', label: '节点', icon: Server, end: false },
]

function NavItem({ item }: { item: (typeof NAV)[number] }) {
  const Icon = item.icon
  return (
    <NavLink
      to={item.to}
      end={item.end}
      className={({ isActive }) =>
        [
          'group relative flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors',
          isActive
            ? 'bg-raised text-fg'
            : 'text-muted hover:bg-hover hover:text-fg',
        ].join(' ')
      }
    >
      {({ isActive }) => (
        <>
          <span
            aria-hidden
            className={[
              'absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full transition-all',
              isActive ? 'bg-brand opacity-100' : 'opacity-0',
            ].join(' ')}
          />
          <Icon size={16} strokeWidth={1.75} />
          {item.label}
        </>
      )}
    </NavLink>
  )
}

/** Small heartbeat: green while the registry answers, red once it stops. */
function ConnectionDot() {
  const { data, isError } = useQuery({
    queryKey: queryKeys.overview,
    queryFn: api.overview,
  })

  const ok = !isError && data != null
  return (
    <div className="flex items-center gap-2 text-xs text-muted">
      <span className="relative flex h-1.5 w-1.5">
        {ok && (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-live opacity-60" />
        )}
        <span
          className={[
            'relative inline-flex h-1.5 w-1.5 rounded-full',
            ok ? 'bg-live' : 'bg-danger',
          ].join(' ')}
        />
      </span>
      {ok ? 'Registry 在线' : 'Registry 离线'}
    </div>
  )
}

const TITLES: Record<string, string> = {
  '/': '概览',
  '/services': '服务',
  '/ports': '端口',
  '/nodes': '节点',
}

export default function Layout() {
  const [paletteOpen, setPaletteOpen] = useState(false)
  const location = useLocation()
  const { data: overview } = useQuery({
    queryKey: queryKeys.overview,
    queryFn: api.overview,
  })

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'k' && (event.metaKey || event.ctrlKey)) {
        event.preventDefault()
        setPaletteOpen((open) => !open)
      }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [])

  const title =
    TITLES[location.pathname] ??
    (location.pathname.startsWith('/services/')
      ? '服务详情'
      : /^\/nodes\/[^/]+\/services\/[^/]+$/.test(location.pathname)
        ? '从节点服务详情'
      : location.pathname.startsWith('/nodes/')
        ? '节点详情'
        : 'APR')

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col border-r border-line-soft bg-panel px-3 py-4 md:flex">
        <div className="mb-6 flex items-center gap-2.5 px-2">
          <div className="grid h-7 w-7 place-items-center rounded-lg bg-brand/15 text-sm font-semibold text-brand">
            A
          </div>
          <div className="leading-tight">
            <div className="text-sm font-semibold">APR</div>
            <div className="text-[11px] text-faint">Agent Port Registry</div>
          </div>
        </div>

        <nav className="flex flex-col gap-0.5">
          {NAV.map((item) => (
            <NavItem key={item.to} item={item} />
          ))}
        </nav>

        <div className="mt-auto space-y-1 px-2 pt-4 text-[11px] text-faint">
          <div className="font-mono">{overview?.hostname ?? '—'}</div>
          <div>v{overview?.version ?? '—'}</div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 items-center gap-4 border-b border-line-soft bg-base/80 px-5 backdrop-blur-md">
          <h1 className="text-sm font-medium">{title}</h1>
          <button
            type="button"
            onClick={() => setPaletteOpen(true)}
            className="ml-auto flex items-center gap-2 rounded-lg border border-line-soft bg-panel px-3 py-1.5 text-xs text-muted transition-colors hover:border-line hover:text-fg"
          >
            <Search size={13} strokeWidth={1.75} />
            <span>搜索服务或端口</span>
            <kbd className="ml-2 rounded border border-line bg-raised px-1.5 py-0.5 font-mono text-[10px]">
              ⌘K
            </kbd>
          </button>
          <ConnectionDot />
        </header>

        <main className="min-w-0 flex-1 px-5 py-6">
          <Outlet />
        </main>
      </div>

      <CommandPalette open={paletteOpen} onOpenChange={setPaletteOpen} />
    </div>
  )
}
