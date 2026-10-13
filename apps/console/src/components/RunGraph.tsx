import { useMemo } from 'react'
import { Background, Controls, ReactFlow, ReactFlowProvider, MarkerType } from '@xyflow/react'
import type { RunDetail } from '../api/client'
import { nodeTypes, type HacNode } from './FlowNode'

/** Read-only graph of the exact definition snapshot a run executed, coloured by real node state. */
export function RunGraph({ run, onSelect, selected }: { run: RunDetail; onSelect?: (id: string) => void; selected?: string | null }) {
  const states = useMemo(() => new Map(run.node_runs.map((n) => [n.node_id, n])), [run.node_runs])
  const nodes = useMemo<HacNode[]>(() => run.definition.nodes.map((n) => {
    const s = states.get(n.id)
    return {
      id: n.id, type: 'hac', position: n.position ?? { x: 0, y: 0 }, selected: selected === n.id, draggable: false, connectable: false,
      data: { nodeType: n.type, label: n.label ?? s?.label ?? n.id, agent: s?.agent, status: s?.status ?? 'pending', latencyMs: s?.latency_ms },
    }
  }), [run.definition.nodes, states, selected])
  const edges = useMemo(() => run.definition.edges.map((e) => ({
    ...e, type: 'smoothstep', animated: states.get(e.source)?.status === 'completed' && states.get(e.target)?.status === 'running',
    markerEnd: { type: MarkerType.ArrowClosed, color: '#64748b' },
  })), [run.definition.edges, states])

  return (
    <div className="h-[420px] w-full rounded-md border border-line bg-canvas" role="group" aria-label="Execution graph">
      <ReactFlowProvider>
        <ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} fitView fitViewOptions={{ padding: 0.2 }}
          nodesDraggable={false} nodesConnectable={false} proOptions={{ hideAttribution: true }}
          onNodeClick={(_, n) => onSelect?.(n.id)} minZoom={0.4}>
          <Background gap={20} color="#cbd5e1" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </ReactFlowProvider>
    </div>
  )
}
