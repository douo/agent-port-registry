import { useEffect, useId, useRef, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { X } from 'lucide-react'
import { errorLabel } from '../lib/api'

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

/* ---------------------------------------------------------------- buttons */

type BtnVariant = 'primary' | 'secondary' | 'danger' | 'ghost'

const BTN: Record<BtnVariant, string> = {
  primary:
    'border-brand/40 bg-brand/20 text-brand hover:bg-brand/30 disabled:opacity-50',
  secondary:
    'border-line-soft bg-panel text-fg hover:border-line hover:bg-hover disabled:opacity-50',
  danger:
    'border-danger/40 bg-danger/10 text-danger hover:bg-danger/20 disabled:opacity-50',
  ghost: 'border-transparent text-muted hover:bg-hover hover:text-fg disabled:opacity-50',
}

export function Button({
  variant = 'secondary',
  className = '',
  type = 'button',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant }) {
  return (
    <button
      type={type}
      className={[
        'inline-flex items-center justify-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm transition-colors disabled:cursor-not-allowed',
        BTN[variant],
        className,
      ].join(' ')}
      {...props}
    />
  )
}

/* ---------------------------------------------------------------- inputs */

export function FieldLabel({
  htmlFor,
  children,
  hint,
}: {
  htmlFor?: string
  children: ReactNode
  hint?: string
}) {
  return (
    <label htmlFor={htmlFor} className="mb-1.5 flex items-baseline gap-2 text-xs text-muted">
      <span>{children}</span>
      {hint && <span className="text-faint">{hint}</span>}
    </label>
  )
}

const INPUT_CLS =
  'w-full rounded-lg border border-line-soft bg-raised px-3 py-2 text-sm text-fg outline-none transition-colors placeholder:text-faint focus:border-brand/60 disabled:opacity-50'

export function TextInput({
  className = '',
  ...props
}: React.InputHTMLAttributes<HTMLInputElement>) {
  return <input className={[INPUT_CLS, className].join(' ')} {...props} />
}

export function TextSelect({
  className = '',
  children,
  ...props
}: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select className={[INPUT_CLS, className].join(' ')} {...props}>
      {children}
    </select>
  )
}

export function TextTextarea({
  className = '',
  ...props
}: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={[INPUT_CLS, 'min-h-20 resize-y font-mono text-xs', className].join(' ')}
      {...props}
    />
  )
}

/* ---------------------------------------------------------------- modal */

export function Modal({
  open,
  onClose,
  title,
  hint,
  children,
  wide = false,
}: {
  open: boolean
  onClose: () => void
  title: string
  hint?: string
  children: ReactNode
  wide?: boolean
}) {
  const titleId = useId()
  const panelRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    // Prevent body scroll while modal is open.
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [open, onClose])

  useEffect(() => {
    if (open) panelRef.current?.querySelector<HTMLElement>('input,select,textarea,button')?.focus()
  }, [open])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto px-4 py-10 sm:py-16">
      <button
        type="button"
        aria-label="关闭"
        className="fixed inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className={[
          'relative z-10 w-full rounded-xl border border-line bg-panel shadow-2xl shadow-black/60',
          wide ? 'max-w-2xl' : 'max-w-lg',
        ].join(' ')}
      >
        <div className="flex items-start gap-3 border-b border-line-soft px-5 py-4">
          <div className="min-w-0 flex-1">
            <h2 id={titleId} className="text-sm font-medium">
              {title}
            </h2>
            {hint && <p className="mt-0.5 text-xs text-faint">{hint}</p>}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-faint transition-colors hover:bg-hover hover:text-fg"
            aria-label="关闭"
          >
            <X size={16} />
          </button>
        </div>
        <div className="px-5 py-4">{children}</div>
      </div>
    </div>
  )
}

/** Confirm destructive / irreversible actions. */
export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  body,
  confirmLabel = '确认',
  danger = false,
  loading = false,
  error,
}: {
  open: boolean
  onClose: () => void
  onConfirm: () => void | Promise<void>
  title: string
  body: ReactNode
  confirmLabel?: string
  danger?: boolean
  loading?: boolean
  error?: unknown
}) {
  return (
    <Modal open={open} onClose={loading ? () => undefined : onClose} title={title}>
      <div className="space-y-4">
        <div className="text-sm text-muted">{body}</div>
        {error != null && (
          <div className="rounded-lg border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger">
            {errorLabel(error)}
          </div>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={loading}>
            取消
          </Button>
          <Button
            variant={danger ? 'danger' : 'primary'}
            onClick={() => void onConfirm()}
            disabled={loading}
          >
            {loading ? '处理中…' : confirmLabel}
          </Button>
        </div>
      </div>
    </Modal>
  )
}

export function FormError({ error }: { error: unknown }) {
  if (error == null) return null
  return (
    <div className="rounded-lg border border-danger/30 bg-danger/5 px-3 py-2 text-sm text-danger">
      {errorLabel(error)}
    </div>
  )
}

export function FormSuccess({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-live/30 bg-live/5 px-3 py-2 text-sm text-live">
      {children}
    </div>
  )
}
