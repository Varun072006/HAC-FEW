import { Link } from 'react-router-dom'
import { ArrowRight, ShieldAlert } from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import { Button, Card, EmptyState, ErrorState, Loading, PageHeader, SectionTitle, StatusBadge, Mono } from '../components/ui'
import { useOverview } from '../lib/queries'
import { timeAgo } from '../lib/format'

const ORDER = ['completed', 'running', 'queued', 'awaiting_approval', 'failed', 'rejected']
const BAR: Record<string, string> = { completed: 'bg-ok', running: 'bg-link', queued: 'bg-line-strong', awaiting_approval: 'bg-warn', failed: 'bg-bad', rejected: 'bg-bad' }

export default function Overview() {
  const { user, can } = useAuth()
  const q = useOverview()
  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={() => q.refetch()} />
  const d = q.data
  const total = d.runs_total

  return (
    <>
      <PageHeader title={`Welcome, ${user?.display_name.split(' ')[0]}`} subtitle="Live state of workflows, runs and human approvals. Everything here is read from the platform database."
        actions={can('workflow:write') && <Link to="/workflows"><Button variant="primary">Open workflows</Button></Link>} />

      {d.approvals_awaiting_you > 0 && (
        <Link to="/approvals" className="mb-5 flex items-center gap-3 rounded-md border border-warn/40 bg-warn-tint px-4 py-3 text-warn hover:border-warn">
          <ShieldAlert size={18} aria-hidden />
          <span className="flex-1 text-sm font-medium">{d.approvals_awaiting_you} {d.approvals_awaiting_you === 1 ? 'approval is' : 'approvals are'} waiting for your decision</span>
          <ArrowRight size={16} aria-hidden />
        </Link>
      )}

      <div className="mb-6 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[['Workflows', d.workflows, '/workflows'], ['Runs', d.runs_total, '/runs'], ['Pending approvals', d.pending_approvals, '/approvals'], ['Failed runs', d.runs_by_status.failed ?? 0, '/runs']].map(([l, v, to]) => (
          <Link key={String(l)} to={String(to)} className="rounded-md border border-line bg-surface p-4 transition-colors hover:border-navy">
            <div className="text-xs font-semibold uppercase tracking-wide text-ink-2">{l}</div>
            <div className="tnum mt-1 text-2xl font-semibold">{v}</div>
          </Link>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        <section>
          <SectionTitle aside={<Link to="/runs" className="text-sm text-link underline">All runs</Link>}>Recent runs</SectionTitle>
          {d.recent_runs.length === 0 ? (
            <EmptyState title="No runs yet" action={<Link to="/workflows"><Button variant="primary">Choose a workflow</Button></Link>}>
              Open a template, save it, and run it. Real execution history appears here.
            </EmptyState>
          ) : (
            <Card as="div"><ul className="divide-y divide-line/70">
              {d.recent_runs.map((r) => (
                <li key={r.id}>
                  <Link to={`/runs/${r.id}`} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 hover:bg-canvas">
                    <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{r.workflow_name}</span>
                      <span className="text-xs text-ink-2"><Mono>{r.id}</Mono> · {r.started_by_name} · {timeAgo(r.created_at)}</span></span>
                    <StatusBadge status={r.status} />
                  </Link>
                </li>
              ))}
            </ul></Card>
          )}
        </section>

        <section>
          <SectionTitle>Runs by status</SectionTitle>
          <Card className="p-4">
            {total === 0 ? <p className="text-sm text-ink-2">Nothing to show until a workflow has run.</p> : (
              <>
                <div className="flex h-2.5 overflow-hidden rounded-sm bg-muted-tint" role="img"
                  aria-label={ORDER.filter((s) => d.runs_by_status[s]).map((s) => `${d.runs_by_status[s]} ${s.replace('_', ' ')}`).join(', ')}>
                  {ORDER.filter((s) => d.runs_by_status[s]).map((s) => <div key={s} className={BAR[s]} style={{ width: `${(d.runs_by_status[s] / total) * 100}%` }} />)}
                </div>
                <ul className="mt-3 space-y-1.5">
                  {ORDER.filter((s) => d.runs_by_status[s]).map((s) => (
                    <li key={s} className="flex items-center justify-between text-sm"><StatusBadge status={s} /><span className="tnum">{d.runs_by_status[s]}</span></li>
                  ))}
                </ul>
              </>
            )}
          </Card>
        </section>
      </div>
    </>
  )
}
