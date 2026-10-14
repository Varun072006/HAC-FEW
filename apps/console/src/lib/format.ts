// The API returns naive UTC timestamps (no zone suffix); treat them as UTC.
export function parseTs(ts: string): Date {
  return new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(ts) ? ts : `${ts}Z`)
}

export function formatTime(ts?: string | null): string {
  if (!ts) return '—'
  return parseTs(ts).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

export function timeAgo(ts?: string | null, now = Date.now()): string {
  if (!ts) return '—'
  const s = Math.max(0, Math.round((now - parseTs(ts).getTime()) / 1000))
  if (s < 5) return 'just now'
  if (s < 60) return `${s}s ago`
  if (s < 3600) return `${Math.floor(s / 60)}m ago`
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`
  return `${Math.floor(s / 86400)}d ago`
}

export function formatMs(ms?: number | null): string {
  if (ms === null || ms === undefined) return '—'
  if (ms < 1000) return `${ms} ms`
  return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)} s`
}

export function duration(start?: string | null, end?: string | null): string {
  if (!start) return '—'
  const a = parseTs(start).getTime()
  const b = end ? parseTs(end).getTime() : Date.now()
  return formatMs(Math.max(0, b - a))
}

export function formatValue(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}

export const titleCase = (s: string) => s.replace(/[_.-]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

export function money(v: unknown): string {
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n.toLocaleString(undefined, { style: 'currency', currency: 'USD', currencyDisplay: 'narrowSymbol' }) : String(v)
}
