import { forwardRef, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes } from 'react'
import * as Dialog from '@radix-ui/react-dialog'
import clsx from 'clsx'
import {
  AlertTriangle, Ban, CheckCircle2, CircleDashed, Circle, Clock, Loader2, MinusCircle, ShieldAlert, ShieldCheck, X, XCircle,
} from 'lucide-react'

/* ---------------------------------------------------------------- buttons */
type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
interface BtnProps extends ButtonHTMLAttributes<HTMLButtonElement> { variant?: Variant; busy?: boolean; size?: 'sm' | 'md' }

const variants: Record<Variant, string> = {
  primary: 'bg-navy text-white border-navy hover:bg-[#16304f] disabled:bg-ink-2 disabled:border-ink-2',
  secondary: 'bg-surface text-ink border-line-strong hover:bg-muted-tint disabled:text-ink-2',
  ghost: 'bg-transparent text-ink-2 border-transparent hover:bg-muted-tint hover:text-ink',
  danger: 'bg-bad-ink text-white border-bad-ink hover:bg-[#991b1b] disabled:opacity-60',
}

export const Button = forwardRef<HTMLButtonElement, BtnProps>(function Button(
  { variant = 'secondary', busy, size = 'md', className, children, disabled, ...rest }, ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={clsx(
        'inline-flex items-center justify-center gap-1.5 rounded-md border font-medium transition-colors duration-150',
        'disabled:opacity-70',
        size === 'sm' ? 'h-8 px-2.5 text-[13px]' : 'h-9 px-3.5 text-sm',
        variants[variant], className,
      )}
      {...rest}
    >
      {busy && <Loader2 size={14} className="spin" aria-hidden />}
      {children}
    </button>
  )
})

export function IconButton({ label, children, className, ...rest }: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button aria-label={label} title={label} {...rest}
      className={clsx('inline-flex size-8 items-center justify-center rounded-md border border-transparent text-ink-2 transition-colors hover:bg-muted-tint hover:text-ink', className)}>
      {children}
    </button>
  )
}

/* ---------------------------------------------------------------- status vocabulary */
type StatusKey = 'queued' | 'running' | 'awaiting_approval' | 'completed' | 'partial' | 'failed' | 'rejected' | 'skipped' | 'pending' | 'approved' | 'cancelled'
const STATUS: Record<StatusKey, { label: string; cls: string; icon: ReactNode }> = {
  queued: { label: 'Queued', cls: 'text-ink-2 bg-muted-tint', icon: <Clock size={13} /> },
  pending: { label: 'Pending', cls: 'text-ink-2 bg-muted-tint', icon: <Circle size={13} /> },
  running: { label: 'Running', cls: 'text-link bg-link-tint', icon: <Loader2 size={13} className="spin" /> },
  awaiting_approval: { label: 'Awaiting approval', cls: 'text-warn bg-warn-tint', icon: <ShieldAlert size={13} /> },
  completed: { label: 'Completed', cls: 'text-ok-ink bg-ok-tint', icon: <CheckCircle2 size={13} /> },
  approved: { label: 'Approved', cls: 'text-ok-ink bg-ok-tint', icon: <CheckCircle2 size={13} /> },
  failed: { label: 'Failed', cls: 'text-bad-ink bg-bad-tint', icon: <XCircle size={13} /> },
  rejected: { label: 'Rejected', cls: 'text-bad-ink bg-bad-tint', icon: <Ban size={13} /> },
  skipped: { label: 'Skipped', cls: 'text-ink-2 bg-muted-tint', icon: <MinusCircle size={13} /> },
  partial: { label: 'Partial', cls: 'text-warn bg-warn-tint', icon: <AlertTriangle size={13} /> },
  cancelled: { label: 'Cancelled', cls: 'text-ink-2 bg-muted-tint', icon: <CircleDashed size={13} /> },
}

export function statusMeta(s: string) { return STATUS[s as StatusKey] ?? STATUS.pending }

/** Colour is never the only signal: every status carries an icon and a text label. */
export function StatusBadge({ status }: { status: string }) {
  const m = statusMeta(status)
  return (
    <span className={clsx('inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-xs font-medium', m.cls)}>
      <span aria-hidden>{m.icon}</span>{m.label}
    </span>
  )
}

const RISK = {
  low: { label: 'Low risk', cls: 'text-ok-ink bg-ok-tint', icon: <ShieldCheck size={13} /> },
  medium: { label: 'Medium risk', cls: 'text-warn bg-warn-tint', icon: <ShieldAlert size={13} /> },
  high: { label: 'High risk', cls: 'text-bad-ink bg-bad-tint', icon: <AlertTriangle size={13} /> },
} as const

export function RiskBadge({ risk }: { risk: string }) {
  const m = RISK[risk as keyof typeof RISK] ?? RISK.low
  return (
    <span className={clsx('inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-xs font-medium', m.cls)}>
      <span aria-hidden>{m.icon}</span>{m.label}
    </span>
  )
}

export function Chip({ children, tone = 'neutral', mono }: { children: ReactNode; tone?: 'neutral' | 'navy' | 'warn' | 'ok' | 'bad'; mono?: boolean }) {
  return (
    <span className={clsx('inline-flex items-center rounded-sm px-1.5 py-0.5 text-xs',
      tone === 'navy' ? 'bg-navy-tint text-navy' : tone === 'warn' ? 'bg-warn-tint text-warn'
        : tone === 'ok' ? 'bg-ok-tint text-ok-ink' : tone === 'bad' ? 'bg-bad-tint text-bad-ink' : 'bg-muted-tint text-ink-2',
      mono && 'mono')}>
      {children}
    </span>
  )
}

/* ---------------------------------------------------------------- layout atoms */
export function Card({ children, className, as: Tag = 'section' }: { children: ReactNode; className?: string; as?: 'section' | 'div' | 'li' }) {
  return <Tag className={clsx('rounded-md border border-line bg-surface', className)}>{children}</Tag>
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-xl text-ink">{title}</h1>
        {subtitle && <p className="mt-0.5 max-w-2xl text-sm text-ink-2">{subtitle}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

export function SectionTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return (
    <div className="mb-2 flex items-center justify-between gap-2">
      <h2 className="text-[13px] font-semibold uppercase tracking-wide text-ink-2">{children}</h2>
      {aside}
    </div>
  )
}

export function Loading({ label = 'Loading' }: { label?: string }) {
  return (
    <div role="status" className="flex items-center gap-2 p-6 text-sm text-ink-2">
      <Loader2 size={16} className="spin" aria-hidden />{label}…
    </div>
  )
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const msg = error instanceof Error ? error.message : 'Something went wrong.'
  return (
    <div role="alert" className="flex items-start gap-3 rounded-md border border-bad-ink/30 bg-bad-tint p-4 text-sm text-bad-ink">
      <AlertTriangle size={18} className="mt-0.5 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1"><p className="font-medium">Could not load this data</p><p className="mt-0.5 break-words">{msg}</p></div>
      {retry && <Button size="sm" onClick={retry}>Retry</Button>}
    </div>
  )
}

export function EmptyState({ title, children, action }: { title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="rounded-md border border-dashed border-line-strong bg-surface px-6 py-10 text-center">
      <p className="font-medium text-ink">{title}</p>
      {children && <p className="mx-auto mt-1 max-w-md text-sm text-ink-2">{children}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  )
}

export function Banner({ tone, children, onClose }: { tone: 'info' | 'warn' | 'error' | 'ok'; children: ReactNode; onClose?: () => void }) {
  const cls = { info: 'bg-link-tint text-navy border-link/30', warn: 'bg-warn-tint text-warn border-warn/30', error: 'bg-bad-tint text-bad-ink border-bad-ink/30', ok: 'bg-ok-tint text-ok-ink border-ok-ink/30' }[tone]
  return (
    <div role={tone === 'error' ? 'alert' : 'status'} className={clsx('flex items-start gap-2 rounded-md border px-3 py-2 text-sm', cls)}>
      <div className="min-w-0 flex-1">{children}</div>
      {onClose && <IconButton label="Dismiss" onClick={onClose} className="-my-1 -mr-1 size-6"><X size={14} /></IconButton>}
    </div>
  )
}

/* ---------------------------------------------------------------- forms */
const control = 'w-full rounded-md border border-line-strong bg-surface px-2.5 text-sm text-ink placeholder:text-ink-2/70 disabled:bg-muted-tint disabled:text-ink-2'

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...p }, ref) {
  return <input ref={ref} className={clsx(control, 'h-9', className)} {...p} />
})
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...p }, ref) {
  return <textarea ref={ref} className={clsx(control, 'min-h-[72px] py-1.5', className)} {...p} />
})
export function Select({ className, children, ...p }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select className={clsx(control, 'h-9 pr-7', className)} {...p}>{children}</select>
}

export function Field({ label, htmlFor, hint, error, children, required }: {
  label: string; htmlFor: string; hint?: ReactNode; error?: string; children: ReactNode; required?: boolean
}) {
  return (
    <div className="space-y-1">
      <label htmlFor={htmlFor} className="block text-[13px] font-medium text-ink">
        {label}{required && <span className="text-bad-ink" aria-hidden> *</span>}
      </label>
      {children}
      {hint && !error && <p id={`${htmlFor}-hint`} className="text-xs text-ink-2">{hint}</p>}
      {error && <p id={`${htmlFor}-err`} role="alert" className="text-xs text-bad-ink">{error}</p>}
    </div>
  )
}

/* ---------------------------------------------------------------- dialog */
export function Modal({ open, onOpenChange, title, description, children, footer, width = 'max-w-md' }: {
  open: boolean; onOpenChange: (o: boolean) => void; title: string; description?: ReactNode
  children?: ReactNode; footer?: ReactNode; width?: string
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-40 bg-ink/40" />
        <Dialog.Content className={clsx('fixed left-1/2 top-1/2 z-50 max-h-[88vh] w-[calc(100vw-32px)] -translate-x-1/2 -translate-y-1/2 overflow-auto rounded-md border border-line bg-surface p-5', width)}>
          <div className="mb-3 flex items-start justify-between gap-3">
            <div>
              <Dialog.Title className="text-base font-semibold text-ink">{title}</Dialog.Title>
              {description ? <Dialog.Description className="mt-0.5 text-sm text-ink-2">{description}</Dialog.Description>
                : <Dialog.Description className="sr-only">{title}</Dialog.Description>}
            </div>
            <Dialog.Close asChild><IconButton label="Close"><X size={16} /></IconButton></Dialog.Close>
          </div>
          {children}
          {footer && <div className="mt-5 flex justify-end gap-2">{footer}</div>}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  )
}

/* ---------------------------------------------------------------- data display */
export function Mono({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={clsx('mono text-[12.5px]', className)}>{children}</span>
}

export function JsonView({ value, className }: { value: unknown; className?: string }) {
  return (
    <pre tabIndex={0} className={clsx('mono max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-sm border border-line bg-canvas p-2.5 text-xs leading-relaxed text-ink', className)}>
      {JSON.stringify(value, null, 2)}
    </pre>
  )
}

export function KV({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
      {items.map(([k, v]) => (<div key={k} className="contents"><dt className="text-ink-2">{k}</dt><dd className="min-w-0 break-words text-ink">{v}</dd></div>))}
    </dl>
  )
}

export function Table({ head, children, caption }: { head: string[]; children: ReactNode; caption: string }) {
  return (
    <div className="overflow-x-auto rounded-md border border-line bg-surface">
      <table className="w-full border-collapse text-left text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead><tr className="border-b border-line bg-canvas">
          {head.map((h) => <th key={h} scope="col" className="px-3 py-2 text-xs font-semibold uppercase tracking-wide text-ink-2">{h}</th>)}
        </tr></thead>
        <tbody className="divide-y divide-line/70">{children}</tbody>
      </table>
    </div>
  )
}
