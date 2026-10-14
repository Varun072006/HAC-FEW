import { useState } from 'react'
import { NavLink, Outlet, useMatch } from 'react-router-dom'
import clsx from 'clsx'
import {
  Activity, Bot, GitBranch, LayoutDashboard, LogOut, Menu, Play, Plug, Route, Settings, ShieldCheck, ScrollText, X,
} from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import { useOverview } from '../lib/queries'
import { Chip, IconButton } from '../components/ui'

interface Item { to: string; label: string; icon: typeof Bot; end?: boolean; perm?: string; badge?: 'approvals' }
const GROUPS: { title: string; items: Item[] }[] = [
  { title: 'Build', items: [
    { to: '/', label: 'Overview', icon: LayoutDashboard, end: true },
    { to: '/plan', label: 'Plan & run', icon: Route },
    { to: '/workflows', label: 'Workflows', icon: GitBranch },
  ] },
  { title: 'Operate', items: [
    { to: '/runs', label: 'Runs', icon: Play },
    { to: '/approvals', label: 'Approvals', icon: ShieldCheck, badge: 'approvals' },
    { to: '/agents', label: 'Agents', icon: Bot },
    { to: '/connectors', label: 'Connectors', icon: Plug },
  ] },
  { title: 'Govern', items: [
    { to: '/policies', label: 'Policies', icon: ScrollText },
    { to: '/observability', label: 'Observability', icon: Activity },
  ] },
  { title: 'Platform', items: [
    { to: '/settings', label: 'Organization', icon: Settings },
  ] },
]

function Wordmark() {
  return (
    <div className="flex items-center gap-2.5 px-4 py-4">
      <svg width="26" height="26" viewBox="0 0 32 32" aria-hidden><rect width="32" height="32" rx="6" fill="#1E3A5F" /><path d="M16 6l8 4.6v9.2L16 24.4 8 19.8v-9.2z" fill="none" stroke="#fff" strokeWidth="2" strokeLinejoin="round" /><circle cx="16" cy="15.2" r="2.4" fill="#fff" /></svg>
      <div className="leading-tight"><div className="mono text-[13px] font-medium tracking-tight text-ink">HAC-FEW</div><div className="text-[11px] text-ink-2">Agent control plane</div></div>
    </div>
  )
}

function Nav({ onNavigate }: { onNavigate?: () => void }) {
  const { data } = useOverview()
  const waiting = data?.approvals_awaiting_you ?? 0
  return (
    <nav aria-label="Primary" className="flex-1 overflow-y-auto px-2 pb-4">
      {GROUPS.map((g) => (
        <div key={g.title} className="mb-3">
          <div className="px-2 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wider text-ink-2">{g.title}</div>
          <ul className="space-y-0.5">
            {g.items.map((it) => (
              <li key={it.to}>
                <NavLink to={it.to} end={it.end} onClick={onNavigate}
                  className={({ isActive }) => clsx(
                    'flex h-9 items-center gap-2.5 rounded-md border-l-2 px-2.5 text-sm transition-colors',
                    isActive ? 'border-navy bg-navy-tint font-medium text-navy' : 'border-transparent text-ink-2 hover:bg-muted-tint hover:text-ink')}>
                  <it.icon size={16} aria-hidden />
                  <span className="flex-1">{it.label}</span>
                  {it.badge === 'approvals' && waiting > 0 && (
                    <span className="tnum rounded-sm bg-warn px-1.5 text-xs font-semibold text-white" aria-label={`${waiting} waiting for you`}>{waiting}</span>
                  )}
                </NavLink>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </nav>
  )
}

function UserBlock() {
  const { user, logout } = useAuth()
  if (!user) return null
  return (
    <div className="border-t border-line p-3">
      <div className="flex items-center gap-2.5">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-navy text-xs font-semibold text-white" aria-hidden>
          {user.display_name.split(' ').map((p) => p[0]).slice(0, 2).join('')}
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-medium text-ink">{user.display_name}</div>
          <Chip tone="navy" mono>{user.role}</Chip>
        </div>
        <IconButton label="Sign out" onClick={logout}><LogOut size={16} /></IconButton>
      </div>
    </div>
  )
}

export function AppShell() {
  const [open, setOpen] = useState(false)
  const builder = !!useMatch('/workflows/:id')  // the canvas is full-bleed
  return (
    <div className="flex min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded-md focus:bg-navy focus:px-3 focus:py-2 focus:text-white">Skip to main content</a>
      <aside className={clsx('sticky top-0 hidden h-screen w-60 shrink-0 flex-col border-r border-line bg-surface', !builder && 'md:flex')}>
        <Wordmark /><Nav /><UserBlock />
      </aside>

      {open && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <button className="absolute inset-0 bg-ink/40" aria-label="Close navigation" onClick={() => setOpen(false)} />
          <aside className="relative flex h-full w-64 flex-col bg-surface">
            <div className="flex items-center justify-between pr-2"><Wordmark /><IconButton label="Close navigation" onClick={() => setOpen(false)}><X size={18} /></IconButton></div>
            <Nav onNavigate={() => setOpen(false)} /><UserBlock />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 items-center gap-2 border-b border-line bg-surface px-3 md:hidden">
          <IconButton label="Open navigation" onClick={() => setOpen(true)}><Menu size={18} /></IconButton>
          <span className="mono text-[13px] font-medium">HAC-FEW</span>
        </header>
        <main id="main" tabIndex={-1} className={builder ? 'min-w-0 flex-1' : 'mx-auto w-full max-w-[1280px] flex-1 px-4 py-6 md:px-8'}>
          <Outlet />
        </main>
      </div>
    </div>
  )
}
