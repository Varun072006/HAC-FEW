import { useCallback, useEffect, useMemo, useState, type DragEvent } from 'react'
import { Link, useBlocker, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import {
  Background, Controls, MarkerType, MiniMap, ReactFlow, ReactFlowProvider, addEdge, applyEdgeChanges, applyNodeChanges,
  useReactFlow, type Connection, type Edge, type EdgeChange, type NodeChange,
} from '@xyflow/react'
import { AlertTriangle, ArrowLeft, CheckCircle2, ChevronDown, ChevronUp, Play, Plus, Save } from 'lucide-react'
import clsx from 'clsx'
import type { CatalogNode, ValidationIssue, WorkflowDefinition } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { AgentGlyph, glyphKind } from '../components/Glyphs'
import { nodeTypes, type HacNode } from '../components/FlowNode'
import { NodeInspector } from '../components/Inspector'
import { RunDialog } from '../components/RunDialog'
import { Banner, Button, ErrorState, Field, Input, Loading, Modal, Textarea } from '../components/ui'
import { useCatalog, useSaveWorkflow, useTemplates, useValidate, useWorkflow } from '../lib/queries'
import { availableReferences, uniqueNodeId } from '../lib/references'

interface Initial { id?: string; version?: number; name: string; description: string; definition: WorkflowDefinition; templateId?: string | null }

const CATEGORY_ORDER = ['trigger', 'knowledge', 'hr', 'finance', 'it', 'notify', 'agent']
const CATEGORY_LABEL: Record<string, string> = { trigger: 'Start', knowledge: 'Knowledge', hr: 'HR', finance: 'Finance', it: 'IT', notify: 'Notify', agent: 'Agents' }
const DRAG_TYPE = 'application/x-hacfew-node'

const blank = (): WorkflowDefinition => ({
  nodes: [{ id: 'trigger', type: 'trigger.manual', label: 'Start', position: { x: 0, y: 120 }, params: { fields: [] } }],
  edges: [],
})

function toRF(def: WorkflowDefinition, catalog: Map<string, CatalogNode>): HacNode[] {
  return def.nodes.map((n) => ({
    id: n.id, type: 'hac', position: n.position ?? { x: 0, y: 0 }, deletable: n.type !== 'trigger.manual',
    data: { nodeType: n.type, label: n.label ?? catalog.get(n.type)?.label ?? n.id, params: (n.params ?? {}) as Record<string, unknown> },
  }))
}

const edgeStyle = { type: 'smoothstep' as const, markerEnd: { type: MarkerType.ArrowClosed, color: '#64748b' } }
const toRFEdges = (def: WorkflowDefinition): Edge[] => def.edges.map((e) => ({ ...e, ...edgeStyle }))

function fromRF(nodes: HacNode[], edges: Edge[]): WorkflowDefinition {
  return {
    nodes: nodes.map((n) => ({
      id: n.id, type: n.data.nodeType, label: n.data.label,
      position: { x: Math.round(n.position.x), y: Math.round(n.position.y) }, params: n.data.params ?? {},
    })),
    edges: edges.map((e) => ({ id: e.id, source: e.source, target: e.target })),
  }
}

export default function WorkflowBuilderPage() {
  const { id } = useParams()
  const [search] = useSearchParams()
  const isNew = id === 'new'
  const catalog = useCatalog()
  const templates = useTemplates()
  const wf = useWorkflow(isNew ? undefined : id)

  if (catalog.error || templates.error || wf.error) return <div className="p-6"><ErrorState error={catalog.error ?? templates.error ?? wf.error} /></div>
  if (catalog.isLoading || templates.isLoading || (!isNew && wf.isLoading) || !catalog.data || !templates.data) return <Loading label="Loading workflow" />

  let initial: Initial
  if (isNew) {
    const t = templates.data.find((x) => x.id === search.get('template'))
    initial = t ? { name: t.name, description: t.description, definition: t.definition, templateId: t.id }
      : { name: 'Untitled workflow', description: '', definition: blank() }
  } else if (wf.data) {
    initial = { id: wf.data.id, version: wf.data.version, name: wf.data.name, description: wf.data.description, definition: wf.data.definition, templateId: wf.data.template_id }
  } else return <Loading />

  return (
    <ReactFlowProvider>
      <Builder key={id} initial={initial} catalog={catalog.data} />
    </ReactFlowProvider>
  )
}

function Builder({ initial, catalog }: { initial: Initial; catalog: CatalogNode[] }) {
  const { can } = useAuth()
  const nav = useNavigate()
  const rf = useReactFlow()
  const save = useSaveWorkflow()
  const spec = useMemo(() => new Map(catalog.map((c) => [c.type, c])), [catalog])
  const canWrite = can('workflow:write')

  const [name, setName] = useState(initial.name)
  const [description, setDescription] = useState(initial.description)
  const [nodes, setNodes] = useState<HacNode[]>(() => toRF(initial.definition, spec))
  const [edges, setEdges] = useState<Edge[]>(() => toRFEdges(initial.definition))
  const [saved, setSaved] = useState({ id: initial.id, version: initial.version })
  const [baseline, setBaseline] = useState(() => JSON.stringify({ name: initial.name, description: initial.description, d: fromRF(toRF(initial.definition, spec), toRFEdges(initial.definition)) }))
  const [saveError, setSaveError] = useState<string | null>(null)
  const [justSaved, setJustSaved] = useState(false)
  const [runOpen, setRunOpen] = useState(false)
  const [panelOpen, setPanelOpen] = useState(true)

  const def = useMemo(() => fromRF(nodes, edges), [nodes, edges])
  const dirty = JSON.stringify({ name, description, d: def }) !== baseline

  // Debounced server-side validation: the same validator the engine uses before every run.
  const [debounced, setDebounced] = useState<WorkflowDefinition | null>(null)
  useEffect(() => { const t = setTimeout(() => setDebounced(def), 350); return () => clearTimeout(t) }, [def])
  const validation = useValidate(debounced)
  const issues: ValidationIssue[] = validation.data?.issues ?? []
  const errors = issues.filter((i) => i.severity === 'error')
  const byNode = useMemo(() => {
    const m = new Map<string, ValidationIssue[]>()
    for (const i of errors) if (i.node_id) m.set(i.node_id, [...(m.get(i.node_id) ?? []), i])
    return m
  }, [errors])

  const selected = nodes.find((n) => n.selected)
  const blocker = useBlocker(dirty && canWrite)
  useEffect(() => {
    const h = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault() } }
    window.addEventListener('beforeunload', h)
    return () => window.removeEventListener('beforeunload', h)
  }, [dirty])

  const display = useMemo<HacNode[]>(() => nodes.map((n) => {
    const s = spec.get(n.data.nodeType)
    return { ...n, data: { ...n.data, agent: s?.kind === 'agent' ? ((n.data.params as { agent_id?: string } | undefined)?.agent_id ?? null) : s?.agent, risk: s?.default_risk, issues: byNode.get(n.id)?.length ?? 0 } }
  }), [nodes, spec, byNode])

  const onNodesChange = useCallback((c: NodeChange<HacNode>[]) => canWrite || c.every((x) => x.type === 'select' || x.type === 'dimensions')
    ? setNodes((ns) => applyNodeChanges(c, ns)) : undefined, [canWrite])
  const onEdgesChange = useCallback((c: EdgeChange[]) => setEdges((es) => applyEdgeChanges(c, es)), [])
  const isValidConnection = useCallback((c: Connection | Edge) =>
    c.source !== c.target && !edges.some((e) => e.source === c.source && e.target === c.target) &&
    nodes.find((n) => n.id === c.target)?.data.nodeType !== 'trigger.manual', [edges, nodes])
  const onConnect = useCallback((c: Connection) => setEdges((es) => addEdge({ ...c, id: `${c.source}->${c.target}`, ...edgeStyle }, es)), [])

  const addNode = useCallback((type: string, at?: { x: number; y: number }) => {
    const s = spec.get(type)!
    const nid = uniqueNodeId(def, type)
    const params: Record<string, unknown> = {}
    for (const p of s.params) if (p.default !== null && p.default !== undefined) params[p.name] = p.default
    const anchor = selected ?? nodes[nodes.length - 1]
    const position = at ?? (anchor ? { x: anchor.position.x + 310, y: anchor.position.y } : { x: 0, y: 120 })
    setNodes((ns) => [...ns.map((n) => ({ ...n, selected: false })), { id: nid, type: 'hac', position, selected: true, data: { nodeType: type, label: s.label, params } } as HacNode])
    setTimeout(() => rf.fitView({ padding: 0.25, duration: 200, maxZoom: 1 }), 30)
  }, [spec, def, nodes, selected, rf])

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    const type = e.dataTransfer.getData(DRAG_TYPE)
    if (type && spec.has(type) && canWrite) addNode(type, rf.screenToFlowPosition({ x: e.clientX - 110, y: e.clientY - 30 }))
  }

  const setParam = (nid: string, key: string, value: unknown) =>
    setNodes((ns) => ns.map((n) => (n.id === nid ? { ...n, data: { ...n.data, params: { ...n.data.params, [key]: value } } } : n)))
  const setLabel = (nid: string, label: string) => setNodes((ns) => ns.map((n) => (n.id === nid ? { ...n, data: { ...n.data, label } } : n)))
  const deleteNode = (nid: string) => { setNodes((ns) => ns.filter((n) => n.id !== nid)); setEdges((es) => es.filter((e) => e.source !== nid && e.target !== nid)) }
  const focusNode = (nid?: string | null) => {
    if (!nid) return
    setNodes((ns) => ns.map((n) => ({ ...n, selected: n.id === nid })))
    const n = nodes.find((x) => x.id === nid)
    if (n) rf.setCenter(n.position.x + 112, n.position.y + 40, { zoom: 1, duration: 250 })
  }

  const doSave = () => {
    setSaveError(null)
    save.mutate({ id: saved.id, version: saved.version, name: name.trim() || 'Untitled workflow', description, definition: def, template_id: initial.templateId }, {
      onSuccess: (w) => {
        setBaseline(JSON.stringify({ name: name.trim() || 'Untitled workflow', description, d: def }))
        setSaved({ id: w.id, version: w.version })
        setJustSaved(true); setTimeout(() => setJustSaved(false), 2500)
        if (!saved.id) nav(`/workflows/${w.id}`, { replace: true })
      },
      onError: (e) => setSaveError(e.message),
    })
  }

  const triggerFields = ((nodes.find((n) => n.data.nodeType === 'trigger.manual')?.data.params?.fields ?? []) as { name: string }[])
  const valid = validation.data?.valid === true && !validation.isFetching
  const runDisabledWhy = !saved.id ? 'Save the workflow before running it.' : dirty ? 'Save your changes before running.'
    : !valid ? 'Fix the validation errors before running.' : null

  const grouped = useMemo(() => CATEGORY_ORDER.map((c) => ({ c, items: catalog.filter((n) => n.category === c && n.kind !== 'trigger') })).filter((g) => g.items.length), [catalog])
  const selSpec = selected ? spec.get(selected.data.nodeType) : undefined

  return (
    <div className="flex h-screen flex-col">
      {/* toolbar */}
      <div className="flex flex-wrap items-center gap-3 border-b border-line bg-surface px-4 py-2">
        <Link to="/workflows" className="inline-flex items-center gap-1 text-sm text-ink-2 hover:text-ink"><ArrowLeft size={15} aria-hidden />Workflows</Link>
        <label className="sr-only" htmlFor="wf-name">Workflow name</label>
        <Input id="wf-name" className="h-8 max-w-xs font-semibold" value={name} disabled={!canWrite} onChange={(e) => setName(e.target.value)} />
        {saved.version && <span className="mono text-xs text-ink-2">v{saved.version}</span>}
        <span className={clsx('text-xs', dirty ? 'text-warn' : 'text-ink-2')} role="status">
          {dirty ? 'Unsaved changes' : justSaved ? 'Saved' : saved.id ? 'All changes saved' : 'Not saved yet'}
        </span>
        <div className="ml-auto flex items-center gap-2">
          <span className={clsx('inline-flex items-center gap-1 text-xs', errors.length ? 'text-bad-ink' : 'text-ok-ink')} role="status">
            {validation.isFetching ? 'Validating…' : errors.length ? <><AlertTriangle size={13} aria-hidden />{errors.length} validation {errors.length === 1 ? 'error' : 'errors'}</> : <><CheckCircle2 size={13} aria-hidden />Valid</>}
          </span>
          {canWrite && <Button onClick={doSave} busy={save.isPending} disabled={!dirty && !!saved.id}><Save size={15} aria-hidden />Save</Button>}
          {can('workflow:run') && (
            <Button variant="primary" disabled={!!runDisabledWhy} onClick={() => setRunOpen(true)} title={runDisabledWhy ?? 'Run this workflow'}><Play size={15} aria-hidden />Run</Button>
          )}
        </div>
      </div>
      {(saveError || (runDisabledWhy && can('workflow:run') && dirty)) && (
        <div className="px-4 pt-2">
          {saveError ? <Banner tone="error" onClose={() => setSaveError(null)}>{saveError}{saveError.includes('changed by someone else') && <> <Link className="underline" reloadDocument to={`/workflows/${saved.id}`}>Reload the latest version</Link>.</>}</Banner>
            : <Banner tone="info">{runDisabledWhy}</Banner>}
        </div>
      )}

      <div className="flex min-h-0 flex-1">
        {/* palette */}
        <aside className="hidden w-60 shrink-0 overflow-y-auto border-r border-line bg-surface p-3 lg:block" aria-label="Step palette">
          <h2 className="mb-2 text-[13px] font-semibold uppercase tracking-wide text-ink-2">Steps</h2>
          {!canWrite && <p className="mb-2 text-xs text-ink-2">You can view this workflow. Editing needs the workflow:write permission.</p>}
          {grouped.map((g) => (
            <div key={g.c} className="mb-3">
              <div className="mb-1 text-xs font-medium text-ink-2">{CATEGORY_LABEL[g.c]}</div>
              <ul className="space-y-1">
                {g.items.map((n) => (
                  <li key={n.type}>
                    <button type="button" disabled={!canWrite} draggable={canWrite}
                      onDragStart={(e: DragEvent) => { e.dataTransfer.setData(DRAG_TYPE, n.type); e.dataTransfer.effectAllowed = 'move' }}
                      onClick={() => addNode(n.type)}
                      aria-label={`Add step: ${n.label}`}
                      className="flex w-full items-start gap-2 rounded-md border border-line bg-surface p-2 text-left transition-colors hover:border-navy hover:bg-navy-tint disabled:opacity-60">
                      <AgentGlyph kind={glyphKind(n.agent, n.kind === 'agent' ? 2 : undefined)} size={15} className="mt-0.5 text-navy" />
                      <span className="min-w-0 flex-1"><span className="block text-[13px] font-medium text-ink">{n.label}</span>
                        <span className="line-clamp-2 text-xs text-ink-2">{n.description}</span></span>
                      {canWrite && <Plus size={14} className="mt-0.5 shrink-0 text-ink-2" aria-hidden />}
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
          <p className="text-xs text-ink-2">Click a step to add it, or drag it onto the canvas. Connect steps by dragging from one dot to another.</p>
        </aside>

        {/* canvas */}
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="relative min-h-0 flex-1" onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = 'move' }} onDrop={onDrop}>
            <ReactFlow nodes={display} edges={edges} nodeTypes={nodeTypes} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange}
              onConnect={onConnect} isValidConnection={isValidConnection} fitView fitViewOptions={{ padding: 0.25, maxZoom: 1 }}
              nodesDraggable={canWrite} nodesConnectable={canWrite} edgesFocusable={canWrite} deleteKeyCode={canWrite ? ['Backspace', 'Delete'] : null}
              minZoom={0.3} proOptions={{ hideAttribution: true }} aria-label="Workflow canvas">
              <Background gap={20} color="#cbd5e1" />
              <Controls showInteractive={false} />
              <MiniMap pannable zoomable nodeColor="#1e3a5f" maskColor="rgba(248,250,252,0.7)" className="!hidden xl:!block" />
            </ReactFlow>
          </div>

          <div className="border-t border-line bg-surface">
            <button type="button" className="flex w-full items-center justify-between px-4 py-2 text-left text-[13px] font-medium" aria-expanded={panelOpen} onClick={() => setPanelOpen((o) => !o)}>
              <span>Validation {issues.length > 0 ? `· ${issues.length}` : ''}</span>{panelOpen ? <ChevronDown size={15} aria-hidden /> : <ChevronUp size={15} aria-hidden />}
            </button>
            {panelOpen && (
              <div className="max-h-36 overflow-y-auto px-4 pb-3">
                {issues.length === 0 ? <p className="text-sm text-ink-2">No issues. This workflow can be run.</p> : (
                  <ul className="space-y-1">
                    {issues.map((i, k) => (
                      <li key={k} className="flex items-start gap-2 text-sm">
                        <span className={clsx('mt-0.5 shrink-0', i.severity === 'error' ? 'text-bad-ink' : 'text-warn')}><AlertTriangle size={14} aria-label={i.severity} /></span>
                        <span className="min-w-0 flex-1">{i.message}{i.node_id && <button type="button" className="ml-2 text-link underline" onClick={() => focusNode(i.node_id)}>Go to step</button>}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}
          </div>
        </div>

        {/* inspector */}
        <aside className="hidden w-80 shrink-0 overflow-y-auto border-l border-line bg-surface p-4 md:block" aria-label="Inspector">
          {selected && selSpec ? (
            <>
              <h2 className="mb-3 text-[13px] font-semibold uppercase tracking-wide text-ink-2">Step settings</h2>
              <NodeInspector key={selected.id} nodeId={selected.id} spec={selSpec} label={selected.data.label} params={selected.data.params ?? {}}
                refs={availableReferences(def, selected.id, spec)} readOnly={!canWrite} issues={byNode.get(selected.id) ?? []}
                onLabel={(v) => setLabel(selected.id, v)} onParam={(k, v) => setParam(selected.id, k, v)}
                onDelete={selSpec.kind === 'trigger' ? undefined : () => deleteNode(selected.id)} />
            </>
          ) : (
            <>
              <h2 className="mb-3 text-[13px] font-semibold uppercase tracking-wide text-ink-2">Workflow</h2>
              <div className="space-y-3">
                <Field label="Description" htmlFor="wf-desc"><Textarea id="wf-desc" disabled={!canWrite} value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
                <p className="text-xs text-ink-2">Select a step to edit it. Steps run in dependency order; a step may only reference values from steps upstream of it.</p>
              </div>
            </>
          )}
        </aside>
      </div>

      {runOpen && saved.id && <RunDialog open onOpenChange={setRunOpen} workflowId={saved.id} workflowName={name} fields={triggerFields as never} />}

      <Modal open={blocker.state === 'blocked'} onOpenChange={() => blocker.reset?.()} title="Leave without saving?"
        description="Your unsaved changes to this workflow will be lost."
        footer={<><Button onClick={() => blocker.reset?.()}>Keep editing</Button><Button variant="danger" onClick={() => blocker.proceed?.()}>Discard changes</Button></>} />
    </div>
  )
}
