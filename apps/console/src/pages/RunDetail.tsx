import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import * as Tabs from '@radix-ui/react-tabs'
import clsx from 'clsx'
import { ArrowLeft, Ban } from 'lucide-react'
import type { NodeRun, RunDetail as RunDetailT, RunEvent } from '../api/client'
import { ApprovalCard } from '../components/ApprovalCard'
import { AgentGlyph, agentLabel, glyphKind } from '../components/Glyphs'
import { RunGraph } from '../components/RunGraph'
import { Banner, Button, Card, Chip, ErrorState, JsonView, KV, Loading, Mono, RiskBadge, StatusBadge, Table } from '../components/ui'
import { duration, formatMs, formatTime, parseTs } from '../lib/format'
import { isTerminal, useAgents, useCancelRun, useRun, useRunEvents } from '../lib/queries'

const tabCls = 'border-b-2 border-transparent px-3 py-2 text-sm text-ink-2 hover:text-ink data-[state=active]:border-navy data-[state=active]:font-medium data-[state=active]:text-navy'

function StepCard({ n, selected }: { n: NodeRun; selected: boolean }) {
  const open = selected || ['failed', 'rejected', 'awaiting_approval', 'running'].includes(n.status)
  const isTrigger = n.node_type === 'trigger.manual'
  return (
    <li id={`step-${n.node_id}`}>
      <Card as="div" className={clsx('overflow-hidden', selected && 'border-link')}>
        <details open={open} className="group">
          <summary className="flex cursor-pointer flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 marker:content-none [&::-webkit-details-marker]:hidden">
            <AgentGlyph kind={isTrigger ? 'trigger' : glyphKind(n.agent, n.delegation?.length ? n.delegation.length - 1 : undefined)} className="text-navy" />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-sm font-semibold">{n.label ?? n.node_id}</span>
              <span className="text-xs text-ink-2">{isTrigger ? 'Trigger' : agentLabel(n.agent)}{n.agent_version ? ` v${n.agent_version}` : ''} · <Mono>{n.node_type}</Mono></span>
            </span>
            {n.criticality === 'optional' && <Chip>optional</Chip>}
            {n.failure_class && <Chip tone="bad" mono>{n.failure_class}</Chip>}
            {n.policy && <RiskBadge risk={n.policy.risk_level} />}
            <StatusBadge status={n.status} />
            <span className="mono tnum w-16 text-right text-xs text-ink-2">{formatMs(n.latency_ms)}</span>
          </summary>

          <div className="space-y-3 border-t border-line/80 px-4 py-3">
            {n.summary && <p className="text-sm"><span className="font-medium">Decision summary: </span>{n.summary}</p>}
            {n.error && <Banner tone="error">{n.error}</Banner>}
            {(n.delegation?.length ?? 0) > 1 && (
              <p className="text-sm"><span className="font-medium">Delegation: </span>
                {n.delegation!.map((a, i) => <span key={a}>{i > 0 && ' → '}<Mono>{a}</Mono></span>)}</p>
            )}

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

            {(n.operations?.length ?? 0) > 0 && (
              <div>
                <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-2">Operations</div>
                <ul className="space-y-1">
                  {n.operations!.map((o) => (
                    <li key={o.index} className="flex flex-wrap items-center gap-2 text-sm">
                      <span className="mono tnum text-xs text-ink-2">{o.index + 1}.</span><Mono>{o.tool}</Mono>
                      <Chip tone={o.effect === 'read' ? undefined : o.effect === 'write' ? 'warn' : 'bad'}>{o.effect}</Chip>
                      {o.replayed && <Chip>replayed from record</Chip>}
                      {o.approved_by && <span className="text-xs text-ink-2">approved by {o.approved_by}</span>}
                      {o.abstained && <Chip tone="warn">retrieval abstained</Chip>}
                      {o.evidence_count > 0 && <span className="text-xs text-ink-2">{o.evidence_count} evidence item(s)</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {(n.evidence?.length ?? 0) > 0 && (
              <div>
                <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-2">Evidence</div>
                <ul className="flex flex-wrap gap-1">{n.evidence!.map((e, i) => <li key={i}><Chip mono>{e}</Chip></li>)}</ul>
              </div>
            )}
            {n.usage && n.usage.calls > 0 && (
              <p className="text-sm"><span className="font-medium">Model usage: </span>{n.usage.calls} call(s), <span className="tnum">{n.usage.input_tokens.toLocaleString()}</span> in / <span className="tnum">{n.usage.output_tokens.toLocaleString()}</span> out tokens
                <Chip tone={n.usage.source === 'provider' ? 'ok' : 'warn'}>{n.usage.source === 'provider' ? 'reported by provider' : n.usage.source === 'estimated' ? 'estimated from text length' : 'partly estimated'}</Chip></p>
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
            <p className="text-xs text-ink-2">Attempts {n.attempts}{n.attempts > 1 ? ' (includes resumes after approval)' : ''} · started {formatTime(n.started_at)} · finished {formatTime(n.finished_at)}</p>
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

type TreeNode = { agent: string; children: Map<string, TreeNode>; tasks: NodeRun[] }

/** The delegation hierarchy as it actually happened: each task sits under the agent that executed it. */
function DelegationTree({ run }: { run: RunDetailT }) {
  const agents = useAgents(true)
  const names = new Map((agents.data ?? []).map((a) => [a.id, a.name]))
  const root: TreeNode = { agent: 'supervisor', children: new Map(), tasks: [] }
  for (const n of run.node_runs) {
    if (!n.delegation?.length) continue
    let cur = root
    for (const a of n.delegation.slice(1)) {
      if (!cur.children.has(a)) cur.children.set(a, { agent: a, children: new Map(), tasks: [] })
      cur = cur.children.get(a)!
    }
    cur.tasks.push(n)
  }
  if (!root.children.size && !root.tasks.length) return <p className="text-sm text-ink-2">This run has no agent tasks, so there is no delegation to show.</p>
  const render = (t: TreeNode, depth: number) => (
    <li key={t.agent}>
      <div className="flex items-center gap-2 py-1"><AgentGlyph kind={glyphKind(t.agent, depth)} size={15} className="text-navy" /><span className="text-sm font-semibold">{names.get(t.agent) ?? agentLabel(t.agent)}</span><Mono className="text-ink-2">{t.agent}</Mono></div>
      {(t.tasks.length > 0 || t.children.size > 0) && (
        <ul className="ml-3 space-y-0.5 border-l border-line pl-4">
          {t.tasks.map((n) => <li key={n.node_id} className="flex flex-wrap items-center gap-2 py-0.5 text-sm"><StatusBadge status={n.status} /><span>{n.label ?? n.node_id}</span>
            {n.failure_class && <Chip tone="bad" mono>{n.failure_class}</Chip>}</li>)}
          {[...t.children.values()].map((c) => render(c, depth + 1))}
        </ul>
      )}
    </li>
  )
  return <Card className="p-4"><ul>{render(root, 0)}</ul></Card>
}

function BudgetPanel({ r }: { r: RunDetailT }) {
  const b = (r.budget ?? {}) as Record<string, number>
  const u = r.usage ?? { calls: 0, input_tokens: 0, output_tokens: 0, total_tokens: 0, source: 'none' }
  const items: [string, React.ReactNode][] = [
    ['Tool calls', <span key="t" className="tnum">{r.tool_calls_used ?? 0} / {b.max_tool_calls ?? '—'}</span>],
    ['Model calls', <span key="m" className="tnum">{u.calls}</span>],
    ['Tokens', u.calls > 0 ? <span key="k" className="tnum">{u.input_tokens.toLocaleString()} in · {u.output_tokens.toLocaleString()} out of {(b.max_total_tokens ?? 0).toLocaleString()}
      <Chip tone={u.source === 'provider' ? 'ok' : 'warn'}>{u.source}</Chip></span> : <span key="k" className="text-ink-2">none used (scripted tasks make no model calls)</span>],
    ['Parallelism', <span key="c" className="tnum">up to {b.max_concurrency ?? '—'} tasks at once</span>],
    ['Wall-clock limit', <span key="w" className="tnum">{b.max_wall_seconds ?? '—'}s</span>],
  ]
  return <Card className="mb-4 p-4"><div className="mb-2 text-xs font-semibold uppercase tracking-wide text-ink-2">Resource use against limits</div><KV items={items} /></Card>
}

export default function RunDetail() {
  const { id } = useParams()
  const run = useRun(id)
  const { events, transport } = useRunEvents(id)
  const [selected, setSelected] = useState<string | null>(null)
  const [tab, setTab] = useState('steps')
  const cancel = useCancelRun()

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
        <div className="flex items-center gap-2" role="status" aria-live="polite">
          {live && <span className="text-xs text-ink-2">Live{transport === 'stream' ? ' · streaming' : transport === 'polling' ? ' · polling' : ''}</span>}
          <StatusBadge status={r.status} />
          {live && !r.cancel_requested && <Button size="sm" busy={cancel.isPending} onClick={() => cancel.mutate(r.id)}><Ban size={13} aria-hidden />Cancel run</Button>}
          {r.cancel_requested && live && <Chip tone="warn">cancelling…</Chip>}
        </div>
      </div>
      {r.objective && <p className="-mt-2 mb-4 text-sm"><span className="font-medium">Objective: </span>{r.objective}{r.plan_id && <> · <Mono className="text-ink-2">{r.plan_id}</Mono></>}</p>}
      {cancel.error && <div className="mb-3"><Banner tone="error">{(cancel.error as Error).message}</Banner></div>}

      {r.status === 'awaiting_approval' && (
        <div className="mb-4 space-y-3">
          <Banner tone="warn"><span className="font-medium">Paused at a human approval gate.</span> The step below has not been executed. It will run only with the exact parameters shown, after the required approvers decide.</Banner>
          {pending.map((a) => <ApprovalCard key={a.id} a={a} compact />)}
        </div>
      )}
      {r.status === 'failed' && r.error && <div className="mb-4"><Banner tone="error">{r.error}</Banner></div>}
      {r.status === 'partial' && <div className="mb-4"><Banner tone="warn"><span className="font-medium">Completed with optional steps that did not succeed.</span> {r.error}</Banner></div>}
      {r.status === 'cancelled' && <div className="mb-4"><Banner tone="info">Cancelled. Steps that had not started were never run; an operation already in flight was allowed to finish and is recorded below.</Banner></div>}
      <BudgetPanel r={r} />
      {r.status === 'rejected' && <div className="mb-4"><Banner tone="error">{r.error ?? 'An approver rejected this run.'} Nothing was executed for the rejected step.</Banner></div>}

      <Tabs.Root value={tab} onValueChange={setTab}>
        <Tabs.List className="mb-4 flex border-b border-line" aria-label="Run views">
          <Tabs.Trigger value="steps" className={tabCls}>Steps</Tabs.Trigger>
          <Tabs.Trigger value="delegation" className={tabCls}>Delegation</Tabs.Trigger>
          <Tabs.Trigger value="graph" className={tabCls}>Graph</Tabs.Trigger>
          <Tabs.Trigger value="events" className={tabCls}>Events <span className="tnum text-xs text-ink-2">{events.length}</span></Tabs.Trigger>
          <Tabs.Trigger value="inputs" className={tabCls}>Inputs</Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content value="steps"><ol className="space-y-3">{r.node_runs.map((n) => <StepCard key={n.node_id} n={n} selected={selected === n.node_id} />)}</ol></Tabs.Content>
        <Tabs.Content value="delegation"><DelegationTree run={r} /></Tabs.Content>
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
