import { CheckCircle2, XCircle } from 'lucide-react'
import { Banner, Card, Chip, ErrorState, Loading, PageHeader } from '../components/ui'
import { useConnectors } from '../lib/queries'
import { formatValue } from '../lib/format'

export default function Connectors() {
  const q = useConnectors()
  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={() => q.refetch()} />
  return (
    <>
      <PageHeader title="Connectors" subtitle="The systems of record agents act on. Health is probed live; call counts come from persisted step runs." />
      <div className="mb-4"><Banner tone="info">These connectors point at the bundled mock enterprise systems. Their settings are read-only here: editing a connection safely needs an encrypted credential store, which this build does not include yet.</Banner></div>
      <div className="grid gap-3 md:grid-cols-2">
        {q.data.map((c) => (
          <Card key={c.id} as="div" className="p-4">
            <div className="flex items-start justify-between gap-2">
              <div><h2 className="text-base">{c.name}</h2><p className="text-sm text-ink-2">{c.system}</p></div>
              <span className={`inline-flex items-center gap-1 text-xs font-medium ${c.status === 'healthy' ? 'text-ok-ink' : 'text-bad-ink'}`}>
                {c.status === 'healthy' ? <CheckCircle2 size={14} aria-hidden /> : <XCircle size={14} aria-hidden />}{c.status === 'healthy' ? 'Healthy' : 'Unreachable'}
              </span>
            </div>
            <dl className="mt-3 grid grid-cols-3 gap-3 text-sm">
              <div><dt className="text-xs text-ink-2">Mode</dt><dd>{c.mode}</dd></div>
              <div><dt className="text-xs text-ink-2">Step runs</dt><dd className="tnum">{c.calls}</dd></div>
              <div><dt className="text-xs text-ink-2">Failed</dt><dd className="tnum">{c.failures}</dd></div>
            </dl>
            {Object.keys(c.detail).length > 0 && (
              <p className="mt-3 text-xs text-ink-2">Records: {Object.entries(c.detail).map(([k, v]) => `${v} ${k}`).join(' · ')}</p>
            )}
            <div className="mt-3 flex flex-wrap gap-1">{c.tools.map((t) => <Chip key={t} mono>{t}</Chip>)}</div>
            {Object.entries(c.detail).length === 0 && c.status !== 'healthy' && <p className="mt-2 text-xs text-bad-ink">{formatValue(c.detail)}</p>}
            <p className="mt-3 text-xs text-ink-2">{c.note}</p>
          </Card>
        ))}
      </div>
    </>
  )
}
