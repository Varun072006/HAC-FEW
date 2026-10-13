import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import * as Tabs from '@radix-ui/react-tabs'
import clsx from 'clsx'
import { ArrowLeft } from 'lucide-react'
import type { NodeRun, RunEvent } from '../api/client'
import { ApprovalCard } from '../components/ApprovalCard'
import { AgentGlyph, AGENT_LABEL } from '../components/Glyphs'
import { RunGraph } from '../components/RunGraph'
import { Banner, Card, ErrorState, JsonView, KV, Loading, Mono, RiskBadge, StatusBadge, Table } from '../components/ui'
import { duration, formatMs, formatTime, parseTs } from '../lib/format'
import { isTerminal, useRun, useRunEvents } from '../lib/queries'

const tabCls = 'border-b-2 border-transparent px-3 py-2 text-sm text-ink-2 hover:text-ink data-[state=active]:border-navy data-[state=active]:font-medium data-[state=active]:text-navy'

function StepCard({ n, selected }: { n: NodeRun; selected: boolean }) {
  const open = selected || ['failed', 'rejected', 'awaiting_approval', 'running'].includes(n.status)
  const isTrigger = n.node_type === 'trigger.manual'
  return (
    <li id={`step-${n.node_id}`}>
      <Card as="div" className={clsx('overflow-hidden', selected && 'border-link')}>
        <details open={open} className="group">
          <summary className="flex cursor-pointer flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 marker:content-none [&::-webkit-details-marker]:hidden">
            <AgentGlyph kind={isTrigger ? 'trigger' : n.agent} className="text-navy" />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-semibold">{n.label ?? n.node_id}</span>
              <span className="text-xs text-ink-2">{isTrigger ? 'Trigger' : AGENT_LABEL[n.agent ?? ''] ?? n.agent} · <Mono>{n.node_type}</Mono></span>
            </span>
            {n.policy && <RiskBadge risk={n.policy.risk_level} />}
            <StatusBadge status={n.status} />
            <span className="mono tnum w-16 text-right text-xs text-ink-2">{formatMs(n.latency_ms)}</span>
          </summary>

          <div className="space-y-3 border-t border-line/80 px-4 py-3">
            {n.summary && <p className="text-sm"><span className="font-medium">Decision summary: </span>{n.summary}</p>}
            {n.error && <Banner tone="error">{n.error}</Banner>}

            {n.policy && (
              <div>
                <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-2">Policy decision</div>
                <KV items={[
                  ['Outcome', n.policy.allowed ? (n.policy.requires_human_approval ? 'Allowed after human approval' : 'Allowed') : 'Blocked'],
                  ['Rule', <Mono key="r">{n.policy.rule_id ?? '—'}</Mono>],
                  ['Reason', n.policy.reason],
                  ...(n.policy.suggested_approver ? [['Approver', n.policy.suggested_approver] as [string, string]] : []),
                ]} />
              </div>
            )}

            {(n.tool_calls?.length ?? 0) > 0 && (
              <div>
                <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-2">Tool activity</div>
                <ul className="space-y-1">
                  {(n.tool_calls ?? []).map((c, i) => (
                    <li key={i} className="flex flex-wrap items-center gap-2 text-sm">
                      <Mono>{c.tool}</Mono><StatusBadge status={c.success ? 'completed' : 'failed'} />
                      <span className="mono tnum text-xs text-ink-2">{formatMs(c.latency_ms)}</span>{c.error && <span className="text-xs text-bad-ink">{c.error}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="grid gap-3 md:grid-cols-2">
              {n.input && <div><div className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-2">Input</div><JsonView value={n.input} /></div>}
              {n.output && <div><div className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-2">Output</div><JsonView value={n.output} /></div>}
            </div>
            <p className="text-xs text-ink-2">Attempts {n.attempts} · started {formatTime(n.started_at)} · finished {formatTime(n.finished_at)}</p>
          </div>
        </details>
      </Card>
    </li>
  )
}

function EventsTable({ events, startedAt }: { events: RunEvent[]; startedAt: string }) {
  if (!events.length) return <p className="text-sm text-ink-2">No events yet.</p>
  const t0 = parseTs(startedAt).getTime()
  return (
    <Table caption="Execution events" head={['#', '+ms', 'Event', 'Step', 'Data']}>
      {events.map((e) => (
        <tr key={e.seq} className="align-top">
          <td className="mono tnum px-3 py-1.5 text-xs text-ink-2">{e.seq}</td>
          <td className="mono tnum px-3 py-1.5 text-xs text-ink-2">{Math.max(0, parseTs(e.ts).getTime() - t0)}</td>
          <td className="px-3 py-1.5"><Mono>{e.type}</Mono></td>
          <td className="px-3 py-1.5"><Mono className="text-ink-2">{e.node_id ?? ''}</Mono></td>
          <td className="max-w-[420px] px-3 py-1.5">
            {Object.keys(e.data).length > 0 && <details><summary className="mono cursor-pointer truncate text-xs text-ink-2">{JSON.stringify(e.data).slice(0, 90)}</summary><JsonView value={e.data} className="mt-1" /></details>}
          </td>
        </tr>
      ))}
    </Table>
  )
}

export default function RunDetail() {
  const { id } = useParams()
  const run = useRun(id)
  const { events } = useRunEvents(id, run.data?.status)
  const [selected, setSelected] = useState<string | null>(null)
  const [tab, setTab] = useState('steps')

  if (run.isLoading) return <Loading label="Loading run" />
  if (run.error || !run.data) return <ErrorState error={run.error} retry={() => run.refetch()} />
  const r = run.data
  const pending = r.approvals.filter((a) => a.status === 'pending')
  const live = !isTerminal(r.status)

  return (
    <>
      <Link to="/runs" className="mb-3 inline-flex items-center gap-1 text-sm text-ink-2 hover:text-ink"><ArrowLeft size={15} aria-hidden />Runs</Link>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-xl">{r.workflow_name} <span className="mono text-sm font-normal text-ink-2">v{r.workflow_version}</span></h1>
          <p className="mt-0.5 text-sm text-ink-2"><Mono>{r.id}</Mono> · started by {r.started_by_name} · {formatTime(r.created_at)} · <span className="tnum">{duration(r.created_at, r.finished_at)}</span>{live && ' so far'}</p>
        </div>
        <div className="flex items-center gap-2" role="status" aria-live="polite">{live && <span className="text-xs text-ink-2">Live</span>}<StatusBadge status={r.status} /></div>
      </div>

      {r.status === 'awaiting_approval' && (
        <div className="mb-4 space-y-3">
          <Banner tone="warn"><span className="font-medium">Paused at a human approval gate.</span> The step below has not been executed. It will run only with the exact parameters shown, after the required approvers decide.</Banner>
          {pending.map((a) => <ApprovalCard key={a.id} a={a} compact />)}
        </div>
      )}
      {r.status === 'failed' && r.error && <div className="mb-4"><Banner tone="error">{r.error}</Banner></div>}
      {r.status === 'rejected' && <div className="mb-4"><Banner tone="error">{r.error ?? 'An approver rejected this run.'} Nothing was executed for the rejected step.</Banner></div>}

      <Tabs.Root value={tab} onValueChange={setTab}>
        <Tabs.List className="mb-4 flex border-b border-line" aria-label="Run views">
          <Tabs.Trigger value="steps" className={tabCls}>Steps</Tabs.Trigger>
          <Tabs.Trigger value="graph" className={tabCls}>Graph</Tabs.Trigger>
          <Tabs.Trigger value="events" className={tabCls}>Events <span className="tnum text-xs text-ink-2">{events.length}</span></Tabs.Trigger>
          <Tabs.Trigger value="inputs" className={tabCls}>Inputs</Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content value="steps"><ol className="space-y-3">{r.node_runs.map((n) => <StepCard key={n.node_id} n={n} selected={selected === n.node_id} />)}</ol></Tabs.Content>
        <Tabs.Content value="graph" className="space-y-3">
          <RunGraph run={r} selected={selected} onSelect={setSelected} />
          {selected && r.node_runs.filter((n) => n.node_id === selected).map((n) => <ol key={n.node_id}><StepCard n={n} selected /></ol>)}
        </Tabs.Content>
        <Tabs.Content value="events"><EventsTable events={events} startedAt={r.created_at} /></Tabs.Content>
        <Tabs.Content value="inputs"><Card className="p-4"><JsonView value={r.inputs} /><p className="mt-3 text-xs text-ink-2">Values restricted to your role are masked. The run executed an immutable snapshot of the workflow as saved at v{r.workflow_version}.</p></Card></Tabs.Content>
      </Tabs.Root>
    </>
  )
}
