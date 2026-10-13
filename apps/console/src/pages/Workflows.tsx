import { Link } from 'react-router-dom'
import { FilePlus2, GitBranch } from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import { Button, Card, EmptyState, ErrorState, Loading, Mono, PageHeader, SectionTitle } from '../components/ui'
import { useTemplates, useWorkflows } from '../lib/queries'
import { timeAgo } from '../lib/format'

export default function Workflows() {
  const { can } = useAuth()
  const wf = useWorkflows()
  const tpl = useTemplates()

  return (
    <>
      <PageHeader title="Workflows" subtitle="Saved workflows run on the real execution engine. Open one to edit it on the canvas or run it."
        actions={can('workflow:write') && <Link to="/workflows/new"><Button variant="primary"><FilePlus2 size={15} aria-hidden />New workflow</Button></Link>} />

      <SectionTitle>Your workflows</SectionTitle>
      {wf.isLoading ? <Loading /> : wf.error ? <ErrorState error={wf.error} retry={() => wf.refetch()} /> : wf.data!.items.length === 0 ? (
        <EmptyState title="No saved workflows yet">{can('workflow:write') ? 'Start from a template below, adjust it on the canvas, and save it.' : 'A manager or administrator needs to create one.'}</EmptyState>
      ) : (
        <Card as="div"><ul className="divide-y divide-line/70">
          {wf.data!.items.map((w) => (
            <li key={w.id}>
              <Link to={`/workflows/${w.id}`} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 hover:bg-canvas">
                <GitBranch size={16} className="text-navy" aria-hidden />
                <span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium">{w.name}</span>
                  <span className="block truncate text-xs text-ink-2">{w.description || 'No description'}</span></span>
                <span className="mono text-xs text-ink-2">v{w.version}</span>
                <span className="text-xs text-ink-2">{w.node_count} steps · updated {timeAgo(w.updated_at)}</span>
              </Link>
            </li>
          ))}
        </ul></Card>
      )}

      {can('workflow:write') && (
        <section className="mt-8">
          <SectionTitle>Templates</SectionTitle>
          {tpl.isLoading ? <Loading /> : tpl.error ? <ErrorState error={tpl.error} /> : (
            <div className="grid gap-3 md:grid-cols-3">
              {tpl.data!.map((t) => (
                <Card key={t.id} as="div" className="flex flex-col p-4">
                  <h3 className="text-sm font-semibold">{t.name}</h3>
                  <p className="mt-1 flex-1 text-sm text-ink-2">{t.description}</p>
                  <div className="mt-3 flex items-center justify-between">
                    <Mono className="text-ink-2">{t.definition.nodes.length} steps</Mono>
                    <Link to={`/workflows/new?template=${t.id}`}><Button size="sm">Use template</Button></Link>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </section>
      )}
    </>
  )
}
