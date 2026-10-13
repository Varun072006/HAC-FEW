import { useMemo, useState } from 'react'
import { Background, Handle, MarkerType, Position, ReactFlow, ReactFlowProvider, type Edge, type Node, type NodeProps } from '@xyflow/react'
import clsx from 'clsx'
import type { Schema } from '../api/client'
import { AgentGlyph } from '../components/Glyphs'
import { Card, Chip, ErrorState, KV, Loading, Mono, PageHeader, SectionTitle } from '../components/ui'
import { useAgents } from '../lib/queries'

type Agent = Schema['AgentOut']
type AgentData = Agent & Record<string, unknown> & { active: boolean }

function AgentNode({ data }: NodeProps<Node<AgentData, 'agent'>>) {
  return (
    <div className={clsx('w-[210px] rounded-md border-[1.5px] bg-surface p-3', data.active ? 'border-navy outline outline-2 outline-offset-2 outline-link' : 'border-line-strong')}>
      <Handle type="target" position={Position.Top} isConnectable={false} />
      <div className="flex items-center gap-2"><AgentGlyph kind={data.id} size={18} className="text-navy" /><span className="text-sm font-semibold">{data.name}</span></div>
      <div className="mt-2 flex gap-3 text-xs text-ink-2">
        {data.id === 'supervisor' ? <span>Plans and gates</span> : <><span><span className="tnum font-medium text-ink">{data.node_runs}</span> step runs</span><span><span className="tnum font-medium text-ink">{data.failures}</span> failed</span></>}
      </div>
      <Handle type="source" position={Position.Bottom} isConnectable={false} />
    </div>
  )
}
const nodeTypes = { agent: AgentNode }

export default function Agents() {
  const q = useAgents()
  const [sel, setSel] = useState('supervisor')
  const { nodes, edges } = useMemo(() => {
    const list = q.data ?? []
    const kids = list.filter((a) => a.parent)
    const n: Node<AgentData, 'agent'>[] = list.map((a) => {
      const i = kids.findIndex((k) => k.id === a.id)
      return { id: a.id, type: 'agent', draggable: false, position: a.parent ? { x: (i - (kids.length - 1) / 2) * 260, y: 150 } : { x: 0, y: 0 }, data: { ...(a as Agent), active: a.id === sel } as AgentData }
    })
    const e: Edge[] = kids.map((k) => ({ id: `s-${k.id}`, source: 'supervisor', target: k.id, type: 'smoothstep', markerEnd: { type: MarkerType.ArrowClosed, color: '#64748b' } }))
    return { nodes: n, edges: e }
  }, [q.data, sel])

  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={() => q.refetch()} />
  const agent = q.data.find((a) => a.id === sel)!
  const children = q.data.filter((a) => a.parent === sel)

  return (
    <>
      <PageHeader title="Agents" subtitle="The hierarchy the engine actually enforces: the supervisor delegates to department agents, and each agent may call only its allow-listed tools." />
      <div className="grid gap-6 lg:grid-cols-[1fr_340px]">
        <div>
          <div className="h-[360px] rounded-md border border-line bg-canvas" role="group" aria-label="Agent hierarchy">
            <ReactFlowProvider>
              <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.25 }} nodesConnectable={false} nodesDraggable={false}
                zoomOnScroll={false} panOnDrag={false} zoomOnDoubleClick={false} proOptions={{ hideAttribution: true }} onNodeClick={(_, nd) => setSel(nd.id)}>
                <Background gap={20} color="#cbd5e1" />
              </ReactFlow>
            </ReactFlowProvider>
          </div>
          <SectionTitle>Choose an agent</SectionTitle>
          <div className="flex flex-wrap gap-2" role="group" aria-label="Select an agent">
            {q.data.map((a) => (
              <button key={a.id} type="button" aria-pressed={sel === a.id} onClick={() => setSel(a.id)}
                className={clsx('inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-sm', sel === a.id ? 'border-navy bg-navy-tint text-navy' : 'border-line-strong bg-surface hover:bg-muted-tint')}>
                <AgentGlyph kind={a.id} size={14} />{a.name}
              </button>
            ))}
          </div>
        </div>

        <Card className="p-4">
          <div className="flex items-center gap-2"><AgentGlyph kind={agent.id} size={20} className="text-navy" /><h2 className="text-base">{agent.name}</h2></div>
          <p className="mt-1 text-sm text-ink-2">{agent.role}</p>
          <div className="mt-4 space-y-4">
            {agent.parent && <KV items={[['Reports to', agent.parent], ['Step runs', <span key="r" className="tnum">{agent.node_runs}</span>], ['Failed', <span key="f" className="tnum">{agent.failures}</span>]]} />}
            {children.length > 0 && <div><div className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-2">Delegates to</div><div className="flex flex-wrap gap-1">{children.map((c) => <Chip key={c.id}>{c.name}</Chip>)}</div></div>}
            {agent.tools.length > 0 && <div><div className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-2">Allowed tools</div><ul className="space-y-1">{agent.tools.map((t) => <li key={t}><Mono>{t}</Mono></li>)}</ul></div>}
            {agent.node_types.length > 0 && <div><div className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-2">Step types it executes</div><ul className="space-y-1">{agent.node_types.map((t) => <li key={t}><Mono>{t}</Mono></li>)}</ul></div>}
            {agent.id === 'supervisor' && <p className="text-sm text-ink-2">The supervisor owns no tools. It orders the graph, evaluates every step against policy, and parks steps that need a human.</p>}
          </div>
        </Card>
      </div>
    </>
  )
}
