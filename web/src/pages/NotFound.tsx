import { Link } from 'react-router-dom'

export default function NotFound() {
  return (
    <div className="flex min-h-[50vh] flex-col items-center justify-center gap-3 text-center">
      <div className="font-mono text-4xl text-faint">404</div>
      <p className="text-sm text-muted">这个页面不存在</p>
      <Link
        to="/"
        className="rounded-lg border border-line-soft px-3 py-1.5 text-sm text-muted transition-colors hover:border-line hover:text-fg"
      >
        回到概览
      </Link>
    </div>
  )
}
