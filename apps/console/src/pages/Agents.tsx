import { useMemo, useState } from 'react'
import { Background, Handle, MarkerType, Position, ReactFlow, ReactFlowProvider, type Edge, type Node, type NodeProps } from '@xyflow/react'
import clsx from 'clsx'
import { Archive, Pencil, Plus, Power } from 'lucide-react'
import { ApiError, type Schema } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { AgentGlyph, glyphKind } from '../components/Glyphs'
import { Banner, Button, Card, Chip, ErrorState, Field, Input, KV, Loading, Modal, Mono, PageHeader, SectionTitle, Select, Table, Textarea } from '../components/ui'
import { useAgent, useAgents, useAgentStatus, useAgentVersions, useSaveAgent, useTools } from '../lib/queries'

type Agent = Schema['AgentOut']
type Config = Record<string, any> // eslint-disable-line @typescript-eslint/no-explicit-any -- server-validated, shape documented by AgentConfig
type AgentData = Agent & Record<string, unknown> & { active: boolean }

const LEVEL = ['Organization supervisor', 'Department coordinator', 'Specialist']
const STATUS_CHIP: Record<string, 'ok' | 'warn' | 'bad' | undefined> = { active: 'ok', disabled: 'warn', archived: 'bad' }

function AgentNode({ data }: NodeProps<Node<AgentData, 'agent'>>) {
  return (
    <div className={clsx('w-[190px] rounded-md border-[1.5px] bg-surface p-2.5', data.active ? 'border-navy outline outline-2 outline-offset-2 outline-link' : 'border-line-strong', data.status !== 'active' && 'opacity-60')}>
      <Handle type="target" position={Position.Top} isConnectable={false} />
      <div className="flex items-center gap-2"><AgentGlyph kind={glyphKind(data.id, data.level)} size={16} className="text-navy" /><span className="truncate text-[13px] font-semibold">{data.name}</span></div>
      <div className="mt-1.5 flex gap-3 text-xs text-ink-2">
        <span>L{data.level}</span><span><span className="tnum font-medium text-ink">{data.tools.length}</span> tools</span>
        {data.status !== 'active' && <span className="font-medium">{data.status}</span>}
      </div>
      <Handle type="source" position={Position.Bottom} isConnectable={false} />
    </div>
  )
}
const nodeTypes = { agent: AgentNode }

const blank = (level: number, parent: string | null): Config => ({
  id: '', name: '', description: '', role: '', level, parent_id: parent, capabilities: [], instructions: '',
  model: { provider: 'deterministic', model: '' }, allowed_tools: [], allowed_connectors: [],
  permissions: { read: true, write: false, destructive: false },
  budgets: { max_total_tokens: 20000, max_model_calls: 6, max_tool_calls: 10, timeout_s: 120 },
  retry: { max_retries: 2, backoff_base_s: 0.5, backoff_max_s: 8 },
})

function AgentEditor({ open, onOpenChange, initial, existing, agents }: {
  open: boolean; onOpenChange: (o: boolean) => void; initial: Config; existing: boolean; agents: Agent[]
}) {
  const save = useSaveAgent()
  const tools = useTools()
  const [cfg, setCfg] = useState<Config>(initial)
  const [raw, setRaw] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [err, setErr] = useState<ApiError | null>(null)
  const set = (patch: Config) => setCfg((c) => ({ ...c, ...patch }))
  const parents = agents.filter((a) => a.level === cfg.level - 1 && a.status === 'active')
  const parentTools = new Set(agents.find((a) => a.id === cfg.parent_id)?.tools ?? [])
  const toolList = (tools.data ?? []).filter((t) => cfg.level === 0 ? false : cfg.level === 2 ? parentTools.has(t.name) || cfg.allowed_tools.includes(t.name) : true)

  const submit = () => {
    let config = cfg
    if (raw !== null) {
      try { config = JSON.parse(raw) } catch { setErr(new ApiError(0, 'The JSON is not valid.')); return }
    }
    setErr(null)
    save.mutate({ id: existing ? config.id : undefined, config, note }, { onSuccess: () => onOpenChange(false), onError: (e) => setErr(e as ApiError) })
  }
  const toggleTool = (t: string, on: boolean) => set({ allowed_tools: on ? [...cfg.allowed_tools, t] : cfg.allowed_tools.filter((x: string) => x !== t) })
  const num = (path: 'budgets' | 'retry', key: string) => (
    <Input type="number" step="any" value={cfg[path][key]} onChange={(e) => set({ [path]: { ...cfg[path], [key]: Number(e.target.value) } })} />
  )

  return (
    <Modal open={open} onOpenChange={onOpenChange} title={existing ? `Edit ${cfg.name || cfg.id}` : 'New agent'}
      description="Saved as a new immutable version after server-side validation. Running workflows keep the version they started with."
      footer={<><Button onClick={() => onOpenChange(false)}>Cancel</Button><Button variant="primary" busy={save.isPending} onClick={submit}>{existing ? 'Save new version' : 'Create agent'}</Button></>}>
      <div className="space-y-3">
        <div className="flex justify-end">
          <Button size="sm" onClick={() => setRaw(raw === null ? JSON.stringify(cfg, null, 2) : (() => { try { setCfg(JSON.parse(raw)) } catch { /* keep form state */ } return null })())}>
            {raw === null ? 'Edit as JSON' : 'Back to form'}
          </Button>
        </div>
        {raw !== null ? (
          <Textarea aria-label="Agent configuration JSON" className="mono min-h-[360px] text-xs" value={raw} onChange={(e) => setRaw(e.target.value)} />
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Id" htmlFor="ag-id" required hint="lowercase, digits, underscores"><Input id="ag-id" disabled={existing} className="mono text-xs" value={cfg.id} onChange={(e) => set({ id: e.target.value })} /></Field>
              <Field label="Name" htmlFor="ag-name" required><Input id="ag-name" value={cfg.name} onChange={(e) => set({ name: e.target.value })} /></Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Level" htmlFor="ag-level"><Select id="ag-level" disabled={existing} value={cfg.level} onChange={(e) => set({ level: Number(e.target.value), parent_id: null, allowed_tools: [] })}>
                {LEVEL.map((l, i) => <option key={l} value={i}>{i} · {l}</option>)}</Select></Field>
              <Field label="Reports to" htmlFor="ag-parent"><Select id="ag-parent" disabled={cfg.level === 0} value={cfg.parent_id ?? ''} onChange={(e) => set({ parent_id: e.target.value || null })}>
                <option value="">{cfg.level === 0 ? '—' : 'Select…'}</option>{parents.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select></Field>
            </div>
            <Field label="Role" htmlFor="ag-role"><Input id="ag-role" value={cfg.role} onChange={(e) => set({ role: e.target.value })} /></Field>
            <Field label="Capabilities" htmlFor="ag-caps" hint="comma-separated snake_case; tasks name the capabilities they need"><Input id="ag-caps" className="mono text-xs" value={cfg.capabilities.join(', ')}
              onChange={(e) => set({ capabilities: e.target.value.split(',').map((x) => x.trim()).filter(Boolean) })} /></Field>
            <Field label="Instructions" htmlFor="ag-ins" hint="Plain text given to a model-backed agent. Cannot grant tools or permissions."><Textarea id="ag-ins" value={cfg.instructions} onChange={(e) => set({ instructions: e.target.value })} /></Field>
            <fieldset className="rounded-md border border-line p-3">
              <legend className="px-1 text-[13px] font-medium">Allowed tools</legend>
              {cfg.level === 0 ? <p className="text-sm text-ink-2">The supervisor may not hold tools: it plans and delegates.</p> : (
                <ul className="grid gap-1.5 sm:grid-cols-2">
                  {toolList.map((t) => (
                    <li key={t.name}><label className="flex items-start gap-2 text-sm">
                      <input type="checkbox" className="mt-1 size-4 accent-[#1E3A5F]" checked={cfg.allowed_tools.includes(t.name)} onChange={(e) => toggleTool(t.name, e.target.checked)} />
                      <span><Mono>{t.name}</Mono> <Chip tone={t.effect === 'read' ? undefined : t.effect === 'write' ? 'warn' : 'bad'}>{t.effect}</Chip></span></label></li>
                  ))}
                </ul>
              )}
              {cfg.level === 2 && <p className="mt-2 text-xs text-ink-2">A specialist can only hold tools its coordinator holds.</p>}
            </fieldset>
            <fieldset className="flex flex-wrap gap-4 rounded-md border border-line p-3">
              <legend className="px-1 text-[13px] font-medium">Permissions</legend>
              {(['read', 'write', 'destructive'] as const).map((k) => (
                <label key={k} className="flex items-center gap-2 text-sm capitalize"><input type="checkbox" className="size-4 accent-[#1E3A5F]" checked={!!cfg.permissions[k]}
                  disabled={cfg.level === 0 && k !== 'read'} onChange={(e) => set({ permissions: { ...cfg.permissions, [k]: e.target.checked } })} />{k}</label>
              ))}
            </fieldset>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Model provider" htmlFor="ag-prov"><Select id="ag-prov" value={cfg.model.provider} onChange={(e) => set({ model: { ...cfg.model, provider: e.target.value } })}>
                <option value="deterministic">None (scripted tasks only)</option><option value="ollama">Ollama (local)</option><option value="openai_compatible">OpenAI-compatible</option></Select></Field>
              <Field label="Model name" htmlFor="ag-model"><Input id="ag-model" className="mono text-xs" disabled={cfg.model.provider === 'deterministic'} value={cfg.model.model} onChange={(e) => set({ model: { ...cfg.model, model: e.target.value } })} /></Field>
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <Field label="Max tokens" htmlFor="ag-b1">{num('budgets', 'max_total_tokens')}</Field>
              <Field label="Max model calls" htmlFor="ag-b2">{num('budgets', 'max_model_calls')}</Field>
              <Field label="Max tool calls" htmlFor="ag-b3">{num('budgets', 'max_tool_calls')}</Field>
              <Field label="Timeout (s)" htmlFor="ag-b4">{num('budgets', 'timeout_s')}</Field>
              <Field label="Max retries" htmlFor="ag-r1">{num('retry', 'max_retries')}</Field>
              <Field label="Backoff base (s)" htmlFor="ag-r2">{num('retry', 'backoff_base_s')}</Field>
              <Field label="Backoff cap (s)" htmlFor="ag-r3">{num('retry', 'backoff_max_s')}</Field>
            </div>
          </>
        )}
        {existing && <Field label="Change note" htmlFor="ag-note"><Input id="ag-note" value={note} onChange={(e) => setNote(e.target.value)} /></Field>}
        {err && (
          <Banner tone="error">
            <p className="font-medium">{err.message}</p>
            <ul className="mt-1 list-disc pl-4 text-xs">{(err.issues ?? []).map((i, k) => <li key={k}>{(i as unknown as { field?: string }).field ? <Mono>{(i as unknown as { field?: string }).field}</Mono> : null} {i.message}</li>)}</ul>
          </Banner>
        )}
      </div>
    </Modal>
  )
}

function Detail({ id, agents, canWrite, onEdit, onNewChild }: { id: string; agents: Agent[]; canWrite: boolean; onEdit: (c: Config) => void; onNewChild: (a: Agent) => void }) {
  const q = useAgent(id)
  const versions = useAgentVersions(id)
  const status = useAgentStatus()
  const [err, setErr] = useState<string | null>(null)
  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={() => q.refetch()} />
  const a = q.data
  const c = a.config as Config
  const children = agents.filter((x) => x.parent === id)
  const change = (s: 'active' | 'disabled' | 'archived') => { setErr(null); status.mutate({ id, status: s }, { onError: (e) => setErr((e as ApiError).message) }) }
  return (
    <Card className="p-4">
      <div className="flex items-start gap-2">
        <AgentGlyph kind={glyphKind(a.id, a.level)} size={20} className="mt-0.5 text-navy" />
        <div className="min-w-0 flex-1"><h2 className="text-base">{a.name}</h2><p className="text-xs text-ink-2">{LEVEL[a.level]} · <Mono>{a.id}</Mono> · v{a.version}</p></div>
        <Chip tone={STATUS_CHIP[a.status]}>{a.status}</Chip>
      </div>
      {a.role && <p className="mt-2 text-sm text-ink-2">{a.role}</p>}
      {canWrite && a.status !== 'archived' && (
        <div className="mt-3 flex flex-wrap gap-2">
          <Button size="sm" onClick={() => onEdit(c)}><Pencil size={13} aria-hidden />Edit</Button>
          {a.level < 2 && <Button size="sm" onClick={() => onNewChild(a)}><Plus size={13} aria-hidden />Add {a.level === 0 ? 'coordinator' : 'specialist'}</Button>}
          {a.status === 'active' ? <Button size="sm" onClick={() => change('disabled')}><Power size={13} aria-hidden />Disable</Button>
            : <Button size="sm" onClick={() => change('active')}><Power size={13} aria-hidden />Enable</Button>}
          <Button size="sm" className="text-bad-ink" onClick={() => change('archived')}><Archive size={13} aria-hidden />Archive</Button>
        </div>
      )}
      {err && <div className="mt-3"><Banner tone="error">{err}</Banner></div>}
      <div className="mt-4 space-y-4">
        <KV items={[
          ['Reports to', a.parent ?? '—'], ['Model', c.model.provider === 'deterministic' ? 'None (scripted tasks)' : `${c.model.provider}: ${c.model.model || 'tiered'}`],
          ['Permissions', ['read', 'write', 'destructive'].filter((k) => c.permissions[k]).join(', ') || 'none'],
          ['Budgets', `${c.budgets.max_tool_calls} tool calls · ${c.budgets.max_model_calls} model calls · ${c.budgets.max_total_tokens.toLocaleString()} tokens · ${c.budgets.timeout_s}s`],
          ['Retries', `${c.retry.max_retries}, backoff ${c.retry.backoff_base_s}s → ${c.retry.backoff_max_s}s`],
          ['Task runs', <span key="r" className="tnum">{a.node_runs} ({a.failures} failed)</span>],
        ]} />
        {children.length > 0 && <div><div className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-2">Delegates to</div><div className="flex flex-wrap gap-1">{children.map((x) => <Chip key={x.id}>{x.name}</Chip>)}</div></div>}
        {c.capabilities.length > 0 && <div><div className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-2">Capabilities</div><div className="flex flex-wrap gap-1">{c.capabilities.map((x: string) => <Chip key={x} mono>{x}</Chip>)}</div></div>}
        {a.tools.length > 0 ? <div><div className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-2">Allowed tools</div><ul className="space-y-1">{a.tools.map((t) => <li key={t}><Mono>{t}</Mono></li>)}</ul></div>
          : <p className="text-sm text-ink-2">Holds no tools. {a.level === 0 ? 'It plans and delegates; it never touches a business system directly.' : ''}</p>}
        {c.instructions && <div><div className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-2">Instructions</div><p className="text-sm">{c.instructions}</p></div>}
        {(versions.data?.length ?? 0) > 0 && (
          <div><div className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-2">Version history</div>
            <ul className="space-y-1 text-sm">{versions.data!.map((v) => <li key={v.version}><span className="mono tnum">v{v.version}</span> · {v.change_note ?? '—'} <span className="text-xs text-ink-2">· {v.created_by}</span></li>)}</ul></div>
        )}
      </div>
    </Card>
  )
}

export default function Agents() {
  const { user } = useAuth()
  const canWrite = !!user?.permissions.includes('agent:write')
  const [archived, setArchived] = useState(false)
  const q = useAgents(archived)
  const [sel, setSel] = useState('supervisor')
  const [editor, setEditor] = useState<{ initial: Config; existing: boolean } | null>(null)

  const { nodes, edges } = useMemo(() => {
    const list = q.data ?? []
    const byLevel = [0, 1, 2].map((l) => list.filter((a) => a.level === l))
    const n: Node<AgentData, 'agent'>[] = []
    // lay out children under their parent, in order, so the tree reads left to right
    const order = (parent: string | null, level: number): Agent[] => byLevel[level].filter((a) => (a.parent ?? null) === parent)
    let col = 0
    const place = (a: Agent, depth: number): number => {
      const kids = a.level < 2 ? order(a.id, a.level + 1) : []
      let x: number
      if (!kids.length) { x = col * 215; col += 1 } else { const xs = kids.map((k) => place(k, depth + 1)); x = (xs[0] + xs[xs.length - 1]) / 2 }
      n.push({ id: a.id, type: 'agent', draggable: false, position: { x, y: depth * 130 }, data: { ...(a as Agent), active: a.id === sel } as AgentData })
      return x
    }
    byLevel[0].forEach((a) => place(a, 0))
    const e: Edge[] = list.filter((a) => a.parent).map((a) => ({ id: `s-${a.id}`, source: a.parent!, target: a.id, type: 'smoothstep', markerEnd: { type: MarkerType.ArrowClosed, color: '#64748b' } }))
    return { nodes: n, edges: e }
  }, [q.data, sel])

  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={() => q.refetch()} />
  const selected = q.data.find((a) => a.id === sel) ? sel : q.data[0]?.id

  return (
    <>
      <PageHeader title="Agents" subtitle="The configurable hierarchy the runtime enforces: the supervisor plans, coordinators delegate, specialists act, and each agent may call only the tools in its registry entry."
        actions={canWrite ? <Button variant="primary" onClick={() => setEditor({ initial: blank(1, 'supervisor'), existing: false })}><Plus size={14} aria-hidden />New agent</Button> : undefined} />
      <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
        <div className="min-w-0">
          <div className="h-[420px] rounded-md border border-line bg-canvas" role="group" aria-label="Agent hierarchy">
            <ReactFlowProvider>
              <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.2 }} nodesConnectable={false} nodesDraggable={false}
                zoomOnScroll={false} zoomOnDoubleClick={false} proOptions={{ hideAttribution: true }} onNodeClick={(_, nd) => setSel(nd.id)}>
                <Background gap={20} color="#cbd5e1" />
              </ReactFlow>
            </ReactFlowProvider>
          </div>
          <div className="mb-1 mt-4 flex items-center justify-between"><SectionTitle>All agents</SectionTitle>
            <label className="flex items-center gap-2 text-sm text-ink-2"><input type="checkbox" className="size-4 accent-[#1E3A5F]" checked={archived} onChange={(e) => setArchived(e.target.checked)} />Show archived</label></div>
          <Table caption="Agent registry" head={['Agent', 'Level', 'Status', 'Model', 'Tools', 'Runs']}>
            {q.data.map((a) => (
              <tr key={a.id} className={clsx('cursor-pointer hover:bg-muted-tint', selected === a.id && 'bg-navy-tint')} onClick={() => setSel(a.id)}>
                <td className="px-3 py-2"><button type="button" className="inline-flex items-center gap-1.5 text-left text-sm font-medium" aria-pressed={selected === a.id} onClick={() => setSel(a.id)}>
                  <AgentGlyph kind={glyphKind(a.id, a.level)} size={14} />{a.name}</button></td>
                <td className="tnum px-3 py-2 text-sm">{a.level}</td>
                <td className="px-3 py-2"><Chip tone={STATUS_CHIP[a.status]}>{a.status}</Chip></td>
                <td className="px-3 py-2 text-sm text-ink-2">{a.model_provider}</td>
                <td className="tnum px-3 py-2 text-sm">{a.tools.length}</td>
                <td className="tnum px-3 py-2 text-sm">{a.node_runs}</td>
              </tr>
            ))}
          </Table>
        </div>
        {selected && <Detail key={selected} id={selected} agents={q.data} canWrite={canWrite}
          onEdit={(c) => setEditor({ initial: c, existing: true })}
          onNewChild={(p) => setEditor({ initial: blank(p.level + 1, p.id), existing: false })} />}
      </div>
      {editor && <AgentEditor key={editor.initial.id || 'new'} open onOpenChange={(o) => { if (!o) setEditor(null) }} initial={editor.initial} existing={editor.existing} agents={q.data} />}
    </>
  )
}
