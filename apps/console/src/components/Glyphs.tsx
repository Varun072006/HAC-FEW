import clsx from 'clsx'

/** Agent identity is carried by shape + label, never by colour alone:
 *  supervisor = hexagon, HR = circle, finance = square, IT = diamond, trigger = triangle. */
export type GlyphKind = 'supervisor' | 'hr' | 'finance' | 'it' | 'trigger' | 'specialist'

export function AgentGlyph({ kind, size = 16, className }: { kind: string | null | undefined; size?: number; className?: string }) {
  const common = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.8, strokeLinejoin: 'round' as const }
  let shape
  switch (kind) {
    case 'supervisor': shape = <><path d="M12 3l7.8 4.5v9L12 21l-7.8-4.5v-9z" {...common} /><circle cx="12" cy="12" r="2.2" fill="currentColor" /></>; break
    case 'hr': shape = <circle cx="12" cy="12" r="8" {...common} />; break
    case 'finance': shape = <rect x="4.5" y="4.5" width="15" height="15" rx="1.5" {...common} />; break
    case 'it': shape = <path d="M12 3l9 9-9 9-9-9z" {...common} />; break
    case 'specialist': shape = <path d="M12 3.5l8.2 6-3.1 9.5H6.9L3.8 9.5z" {...common} />; break
    default: shape = <path d="M7 4.5l12 7.5-12 7.5z" {...common} />
  }
  return <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden className={clsx('shrink-0', className)}>{shape}</svg>
}

export const AGENT_LABEL: Record<string, string> = {
  supervisor: 'Supervisor', hr: 'HR agent', finance: 'Finance agent', it: 'IT agent',
}

const KNOWN = new Set(['supervisor', 'hr', 'finance', 'it', 'trigger'])
/** Shape for any agent: the three original departments keep theirs; every other agent is
 *  identified by its hierarchy level (L0 hexagon, L1 circle, L2 pentagon) and always by its label. */
export function glyphKind(id: string | null | undefined, level?: number | null): GlyphKind {
  if (id && KNOWN.has(id)) return id as GlyphKind
  if (level === 0) return 'supervisor'
  if (level === 1) return 'hr'
  return 'specialist'
}
export const agentLabel = (id: string | null | undefined) =>
  !id ? '' : AGENT_LABEL[id] ?? id.split('_').map((w) => w[0]?.toUpperCase() + w.slice(1)).join(' ')
