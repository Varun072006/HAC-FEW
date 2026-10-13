import { useState } from 'react'
import { Link } from 'react-router-dom'
import * as Tabs from '@radix-ui/react-tabs'
import { useMutation } from '@tanstack/react-query'
import { CheckCircle2, XCircle } from 'lucide-react'
import { api, unwrap } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Banner, Button, EmptyState, ErrorState, Field, Loading, Mono, PageHeader, Select, Table } from '../components/ui'
import { useAudit, useUsage } from '../lib/queries'
import { formatMs, formatTime } from '../lib/format'

const tabCls = 'border-b-2 border-transparent px-3 py-2 text-sm text-ink-2 hover:text-ink data-[state=active]:border-navy data-[state=active]:font-medium data-[state=active]:text-navy'

function Execution() {
  const q = useUsage()
  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={() => q.refetch()} />
  const u = q.data
  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[['Step runs', u.total_node_runs], ['Tool calls', u.tool_calls], ['Tool failures', u.tool_failures], ['Model calls', u.llm_calls]].map(([l, v]) => (
          <div key={String(l)} className="rounded-md border border-line bg-surface p-4"><div className="text-xs font-semibold uppercase tracking-wide text-ink-2">{l}</div><div className="tnum mt-1 text-2xl font-semibold">{v}</div></div>
        ))}
      </div>
      {!u.llm_backed && <Banner tone="info"><span className="font-medium">No model usage to report.</span> {u.note}</Banner>}
      {u.by_node_type.length === 0 ? <EmptyState title="No executions recorded yet">Run a workflow to see latency and failure rates per step type.</EmptyState> : (
        <Table caption="Execution statistics by step type" head={['Step type', 'Runs', 'Failures', 'Avg latency', 'Max latency']}>
          {u.by_node_type.map((n) => (
            <tr key={n.node_type}><td className="px-3 py-2"><Mono>{n.node_type}</Mono></td><td className="tnum px-3 py-2">{n.runs}</td><td className="tnum px-3 py-2">{n.failures}</td>
              <td className="mono tnum px-3 py-2 text-xs">{formatMs(n.avg_latency_ms == null ? null : Math.round(n.avg_latency_ms))}</td><td className="mono tnum px-3 py-2 text-xs">{formatMs(n.max_latency_ms)}</td></tr>
          ))}
        </Table>
      )}
    </div>
  )
}

function Audit() {
  const [action, setAction] = useState('')
  const q = useAudit(action)
  const verify = useMutation({ mutationFn: () => unwrap(api.GET('/audit/verify')) })
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-60"><Field label="Action" htmlFor="audit-action">
          <Select id="audit-action" value={action} onChange={(e) => setAction(e.target.value)}>
            <option value="">All actions</option>
            {['auth.login', 'run.started', 'policy.decision', 'approval.requested', 'approval.decided', 'approval.decision_denied', 'authz.denied', 'workflow.created', 'workflow.updated'].map((a) => <option key={a}>{a}</option>)}
          </Select></Field></div>
        <Button onClick={() => verify.mutate()} busy={verify.isPending}>Verify hash chain</Button>
        {verify.data && (verify.data.valid
          ? <span className="inline-flex items-center gap-1 text-sm text-ok-ink" role="status"><CheckCircle2 size={15} aria-hidden />Chain intact · {verify.data.checked} events checked</span>
          : <span className="inline-flex items-center gap-1 text-sm text-bad-ink" role="alert"><XCircle size={15} aria-hidden />Tampering detected at event #{verify.data.first_invalid_id}</span>)}
      </div>
      {q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} retry={() => q.refetch()} /> : q.data!.items.length === 0 ? <EmptyState title="No audit events match" /> : (
        <Table caption="Audit trail, newest first" head={['#', 'Time', 'Actor', 'Action', 'Outcome', 'Target', 'Detail']}>
          {q.data!.items.map((e) => (
            <tr key={e.id} className="align-top">
              <td className="mono tnum px-3 py-1.5 text-xs text-ink-2">{e.id}</td>
              <td className="tnum px-3 py-1.5 text-xs text-ink-2">{formatTime(e.ts)}</td>
              <td className="px-3 py-1.5"><Mono>{e.actor_id}</Mono>{e.actor_role && <span className="text-xs text-ink-2"> · {e.actor_role}</span>}</td>
              <td className="px-3 py-1.5"><Mono>{e.action}</Mono></td>
              <td className={`px-3 py-1.5 text-xs font-medium ${e.outcome === 'success' ? 'text-ok-ink' : e.outcome === 'pending' ? 'text-warn' : 'text-bad-ink'}`}>{e.outcome}</td>
              <td className="px-3 py-1.5 text-xs">{e.run_id ? <Link className="text-link underline" to={`/runs/${e.run_id}`}><Mono>{e.run_id}</Mono></Link> : <Mono className="text-ink-2">{e.resource_id ?? ''}</Mono>}</td>
              <td className="max-w-[320px] px-3 py-1.5"><details><summary className="mono cursor-pointer truncate text-xs text-ink-2">{JSON.stringify(e.detail).slice(0, 70)}</summary><pre className="mono mt-1 whitespace-pre-wrap break-words text-xs">{JSON.stringify(e.detail, null, 2)}</pre></details></td>
            </tr>
          ))}
        </Table>
      )}
    </div>
  )
}

export default function Observability() {
  const { can } = useAuth()
  const [tab, setTab] = useState(can('run:read_all') ? 'execution' : 'audit')
  return (
    <>
      <PageHeader title="Observability" subtitle="Execution statistics from persisted step runs, and the tamper-evident audit trail." />
      <Tabs.Root value={tab} onValueChange={setTab}>
        <Tabs.List className="mb-4 flex border-b border-line" aria-label="Observability views">
          {can('run:read_all') && <Tabs.Trigger value="execution" className={tabCls}>Execution</Tabs.Trigger>}
          <Tabs.Trigger value="audit" className={tabCls}>Audit trail</Tabs.Trigger>
        </Tabs.List>
        {can('run:read_all') && <Tabs.Content value="execution"><Execution /></Tabs.Content>}
        <Tabs.Content value="audit">{can('audit:read') ? <Audit /> : <EmptyState title="Audit trail is restricted">Your role does not have the audit:read permission. Controllers and administrators can view it.</EmptyState>}</Tabs.Content>
      </Tabs.Root>
    </>
  )
}
