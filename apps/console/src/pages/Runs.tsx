import { useState } from 'react'
import { Link } from 'react-router-dom'
import { EmptyState, ErrorState, Field, Loading, Mono, PageHeader, Select, StatusBadge, Table } from '../components/ui'
import { useRuns } from '../lib/queries'
import { duration, formatTime } from '../lib/format'

const STATUSES = ['queued', 'running', 'awaiting_approval', 'completed', 'failed', 'rejected']

export default function Runs() {
  const [status, setStatus] = useState('')
  const q = useRuns(status)
  return (
    <>
      <PageHeader title="Runs" subtitle="Every execution, persisted. Open a run to inspect each step, its policy decision, tool activity and timing." />
      <div className="mb-3 max-w-[220px]">
        <Field label="Status" htmlFor="status-filter">
          <Select id="status-filter" value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>
            {STATUSES.map((s) => <option key={s} value={s}>{s.replace('_', ' ')}</option>)}
          </Select>
        </Field>
      </div>
      {q.isLoading ? <Loading /> : q.error ? <ErrorState error={q.error} retry={() => q.refetch()} /> : q.data!.items.length === 0 ? (
        <EmptyState title={status ? 'No runs with this status' : 'No runs yet'}>Run a saved workflow and it will be listed here.</EmptyState>
      ) : (
        <>
          <Table caption="Workflow runs" head={['Run', 'Workflow', 'Status', 'Started by', 'Started', 'Duration']}>
            {q.data!.items.map((r) => (
              <tr key={r.id} className="hover:bg-canvas">
                <td className="px-3 py-2"><Link to={`/runs/${r.id}`} className="text-link underline"><Mono>{r.id}</Mono></Link></td>
                <td className="px-3 py-2">{r.workflow_name} <span className="mono text-xs text-ink-2">v{r.workflow_version}</span></td>
                <td className="px-3 py-2"><StatusBadge status={r.status} /></td>
                <td className="px-3 py-2">{r.started_by_name}</td>
                <td className="tnum px-3 py-2 text-ink-2">{formatTime(r.created_at)}</td>
                <td className="mono tnum px-3 py-2 text-xs">{r.finished_at ? duration(r.created_at, r.finished_at) : '—'}</td>
              </tr>
            ))}
          </Table>
          <p className="mt-2 text-xs text-ink-2">{q.data!.total} total</p>
        </>
      )}
    </>
  )
}
