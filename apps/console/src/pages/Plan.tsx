import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Background, Controls, MarkerType, ReactFlow, ReactFlowProvider } from '@xyflow/react'
import { AlertTriangle, Play, Save, Sparkles } from 'lucide-react'
import { ApiError, type Schema } from '../api/client'
import { nodeTypes, type HacNode } from '../components/FlowNode'
import { Banner, Button, Card, Chip, Field, Input, Mono, PageHeader, SectionTitle, Select, Table, Textarea } from '../components/ui'
import { agentLabel } from '../components/Glyphs'
import { useAgents, useCreatePlan, useExecutePlan, useSaveWorkflow, useTools } from '../lib/queries'

type Plan = Schema['PlanOut']
type PlanTask = { id: string; description: string; agent_id: string; depends_on: string[]; operations: { tool: string }[]; criticality: string; require_evidence: boolean; complexity: string; risk?: string | null }

const EXAMPLES = [
  'Reimburse an expense claim with the receipt',
  'Onboard a new hire joining engineering',
  'Production server outage, open an incident',
]
const CATEGORY: Record<string, string> = {
  planning_failure: 'Planning failure', policy_rejection: 'Policy rejection', budget_exceeded: 'Budget exceeded',
}

function PlanGraph({ plan }: { plan: Plan }) {
  const agents = useAgents()
  const level = new Map((agents.data ?? []).map((a) => [a.id, a.level]))
  const { nodes, edges } = useMemo(() => {
    const def = plan.definition
    if (!def) return { nodes: [] as HacNode[], edges: [] }
    return {
      nodes: def.nodes.map<HacNode>((n) => ({
        id: n.id, type: 'hac', position: n.position ?? { x: 0, y: 0 }, draggable: false, connectable: false,
        data: { nodeType: n.type, label: n.label ?? n.id, agent: (n.params as { agent_id?: string })?.agent_id, agentLevel: level.get((n.params as { agent_id?: string })?.agent_id ?? '') },
      })),
      edges: def.edges.map((e) => ({ ...e, type: 'smoothstep', markerEnd: { type: MarkerType.ArrowClosed, color: '#64748b' } })),
    }
  }, [plan.definition, level])
  return (
    <div className="h-[340px] w-full rounded-md border border-line bg-canvas" role="group" aria-label="Plan task graph">
      <ReactFlowProvider>
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.2 }} nodesDraggable={false} nodesConnectable={false}
          proOptions={{ hideAttribution: true }} minZoom={0.4}><Background gap={20} color="#cbd5e1" /><Controls showInteractive={false} /></ReactFlow>
      </ReactFlowProvider>
    </div>
  )
}

function Inputs({ fields, values, setValues, errors }: {
  fields: { name: string; type?: string; required?: boolean; default?: unknown }[]; values: Record<string, unknown>
  setValues: (v: Record<string, unknown>) => void; errors: Record<string, string>
}) {
  if (!fields.length) return <p className="text-sm text-ink-2">This plan needs no inputs.</p>
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {fields.map((f) => {
        const id = `plan-in-${f.name}`
        return (
          <Field key={f.name} label={f.name} htmlFor={id} required={f.required !== false && f.type !== 'boolean'} error={errors[f.name]}>
            {f.type === 'boolean' ? (
              <label className="flex items-center gap-2 text-sm"><input id={id} type="checkbox" className="size-4 accent-[#1E3A5F]" checked={values[f.name] === true}
                onChange={(e) => setValues({ ...values, [f.name]: e.target.checked })} />Yes</label>
            ) : (
              <Input id={id} inputMode={f.type === 'number' ? 'decimal' : undefined} value={String(values[f.name] ?? '')} onChange={(e) => setValues({ ...values, [f.name]: e.target.value })} />
            )}
          </Field>
        )
      })}
    </div>
  )
}

export default function PlanPage() {
  const nav = useNavigate()
  const create = useCreatePlan()
  const execute = useExecutePlan()
  const saveWf = useSaveWorkflow()
  const tools = useTools()
  const [objective, setObjective] = useState(EXAMPLES[0])
  const [mode, setMode] = useState<'auto' | 'deterministic' | 'llm' | 'structured'>('auto')
  const [structured, setStructured] = useState('')
  const [plan, setPlan] = useState<Plan | null>(null)
  const [values, setValues] = useState<Record<string, unknown>>({})
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [error, setError] = useState<ApiError | null>(null)
  const effect = new Map((tools.data ?? []).map((t) => [t.name, t.effect]))

  const generate = () => {
    setError(null); setPlan(null)
    let body: Record<string, unknown> | undefined
    if (mode === 'structured') { try { body = JSON.parse(structured) } catch { setError(new ApiError(0, 'The structured plan is not valid JSON.')); return } }
    create.mutate({ objective, mode, plan: body }, {
      onSuccess: (p) => { setPlan(p); setValues(Object.fromEntries((p.trigger_fields as { name: string; default?: unknown }[]).filter((f) => f.default !== undefined).map((f) => [f.name, f.default]))) },
      onError: (e) => setError(e as ApiError),
    })
  }

  const collect = (): Record<string, unknown> | null => {
    const e: Record<string, string> = {}; const out: Record<string, unknown> = {}
    for (const f of (plan?.trigger_fields ?? []) as { name: string; type?: string; required?: boolean }[]) {
      const v = values[f.name]
      if (v === undefined || v === '') { if (f.required !== false && f.type !== 'boolean') e[f.name] = 'This field is required.'; continue }
      if (f.type === 'number') { const n = Number(v); if (!Number.isFinite(n)) { e[f.name] = 'Enter a number.'; continue } out[f.name] = n } else out[f.name] = v
    }
    setErrors(e)
    return Object.keys(e).length ? null : out
  }
  const run = () => {
    const inputs = collect(); if (!plan || !inputs) return
    setError(null)
    execute.mutate({ id: plan.id, inputs }, { onSuccess: (r) => nav(`/runs/${r.id}`), onError: (e) => setError(e as ApiError) })
  }
  const saveAsWorkflow = () => {
    if (!plan?.definition) return
    saveWf.mutate({ name: `Plan: ${plan.objective.slice(0, 60)}`, description: plan.objective, definition: plan.definition, template_id: null },
      { onSuccess: (w) => nav(`/workflows/${w.id}`), onError: (e) => setError(e as ApiError) })
  }

  const tasks = ((plan?.plan as { tasks?: PlanTask[] } | undefined)?.tasks ?? [])
  const errs = plan?.issues.filter((i) => i.severity === 'error') ?? []

  return (
    <>
      <PageHeader title="Plan & run" subtitle="State an objective. The supervisor produces a structured task plan; the server validates agents, dependencies, tools, permissions and budgets before anything can run." />
      <Card className="p-4">
        <div className="grid gap-3 lg:grid-cols-[1fr_220px]">
          <Field label="Objective" htmlFor="plan-objective" required><Textarea id="plan-objective" value={objective} onChange={(e) => setObjective(e.target.value)} /></Field>
          <Field label="Planner" htmlFor="plan-mode" hint="Auto uses the supervisor's model when one is configured, else the deterministic planner.">
            <Select id="plan-mode" value={mode} onChange={(e) => setMode(e.target.value as typeof mode)}>
              <option value="auto">Auto</option><option value="deterministic">Deterministic (offline)</option><option value="llm">Model-backed</option><option value="structured">Supply a plan (JSON)</option>
            </Select>
          </Field>
        </div>
        <div className="mt-2 flex flex-wrap gap-2" role="group" aria-label="Example requests">
          {EXAMPLES.map((x) => <button key={x} type="button" className="rounded-md border border-line-strong bg-surface px-2 py-1 text-xs hover:bg-muted-tint" onClick={() => setObjective(x)}>{x}</button>)}
        </div>
        {mode === 'structured' && <div className="mt-3"><Field label="Plan JSON" htmlFor="plan-json" hint="Unknown fields such as permissions or policy overrides are rejected."><Textarea id="plan-json" className="mono min-h-[180px] text-xs" value={structured} onChange={(e) => setStructured(e.target.value)} /></Field></div>}
        <div className="mt-4"><Button variant="primary" busy={create.isPending} disabled={objective.trim().length < 3} onClick={generate}><Sparkles size={14} aria-hidden />Generate and validate plan</Button></div>
      </Card>

      {error && <div className="mt-4"><Banner tone="error"><p className="font-medium">{error.message}</p>{(error.issues ?? []).slice(0, 6).map((i, k) => <p key={k} className="mt-0.5 text-xs">{i.message}</p>)}</Banner></div>}

      {plan && (
        <div className="mt-6 space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-base">Plan</h2><Chip tone={plan.valid ? 'ok' : 'bad'}>{plan.valid ? 'valid' : 'rejected'}</Chip><Chip>planner: {plan.planner}</Chip>
            {plan.usage && plan.usage.calls > 0 && <Chip>{plan.usage.calls} model call(s) · {plan.usage.total_tokens.toLocaleString()} tokens ({plan.usage.source})</Chip>}
            <Mono className="text-ink-2">{plan.id}</Mono>
          </div>
          {plan.note && <Banner tone="info">{plan.note}</Banner>}
          {errs.length > 0 && (
            <Banner tone="error">
              <p className="flex items-center gap-1 font-medium"><AlertTriangle size={14} aria-hidden />{plan.failure_category ? CATEGORY[plan.failure_category] ?? plan.failure_category : 'Rejected'}: this plan cannot run.</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm">{errs.map((i, k) => <li key={k}>{i.node_id && <Mono>{i.node_id}</Mono>} {i.message} {i.category && <span className="text-xs text-ink-2">({CATEGORY[i.category] ?? i.category})</span>}</li>)}</ul>
            </Banner>
          )}
          {tasks.length > 0 && (
            <>
              <PlanGraph plan={plan} />
              <Table caption="Plan tasks" head={['Task', 'Agent', 'Depends on', 'Operations', 'Flags']}>
                {tasks.map((t) => (
                  <tr key={t.id} className="align-top">
                    <td className="px-3 py-2"><div className="text-sm font-medium">{t.description}</div><Mono className="text-ink-2">{t.id}</Mono></td>
                    <td className="px-3 py-2 text-sm">{agentLabel(t.agent_id)}</td>
                    <td className="px-3 py-2 text-sm">{t.depends_on.length ? t.depends_on.map((d) => <Mono key={d} className="mr-1">{d}</Mono>) : <span className="text-ink-2">trigger</span>}</td>
                    <td className="px-3 py-2"><ul className="space-y-1">{t.operations.length ? t.operations.map((o, i) => <li key={i} className="flex items-center gap-1.5"><Mono>{o.tool}</Mono>
                      <Chip tone={effect.get(o.tool) === 'write' ? 'warn' : effect.get(o.tool) === 'destructive' ? 'bad' : undefined}>{effect.get(o.tool) ?? '…'}</Chip></li>) : <li className="text-sm text-ink-2">chosen by the agent's model</li>}</ul></td>
                    <td className="px-3 py-2"><div className="flex flex-wrap gap-1">{t.criticality === 'optional' && <Chip>optional</Chip>}{t.require_evidence && <Chip>needs evidence</Chip>}{t.risk && <Chip tone={t.risk === 'high' ? 'bad' : t.risk === 'medium' ? 'warn' : undefined}>{t.risk} risk</Chip>}</div></td>
                  </tr>
                ))}
              </Table>
            </>
          )}
          {plan.valid && plan.status !== 'executed' && (
            <Card className="p-4">
              <SectionTitle>Run inputs</SectionTitle>
              <Inputs fields={plan.trigger_fields as { name: string }[]} values={values} setValues={setValues} errors={errors} />
              <p className="mt-3 text-xs text-ink-2">Execution re-validates the plan against the live registry and your role. Steps that policy marks high-risk will pause for a human approval; nothing protected runs before that.</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button variant="primary" busy={execute.isPending} onClick={run}><Play size={14} aria-hidden />Execute plan</Button>
                <Button busy={saveWf.isPending} onClick={saveAsWorkflow}><Save size={14} aria-hidden />Save as editable workflow</Button>
              </div>
            </Card>
          )}
          {plan.status === 'executed' && plan.run_id && <Banner tone="info">This plan was executed. <button type="button" className="underline" onClick={() => nav(`/runs/${plan.run_id}`)}>Open the run</button></Banner>}
        </div>
      )}
    </>
  )
}
