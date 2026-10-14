import { memo } from 'react'
import { Handle, Position, type NodeProps, type Node } from '@xyflow/react'
import clsx from 'clsx'
import { AlertTriangle } from 'lucide-react'
import { AgentGlyph, glyphKind } from './Glyphs'
import { RiskBadge, StatusBadge, statusMeta } from './ui'
import { formatMs } from '../lib/format'

export interface HacNodeData extends Record<string, unknown> {
  nodeType: string
  label: string
  agent?: string | null
  agentLevel?: number | null
  risk?: string
  issues?: number
  /** Present only in run views. */
  status?: string
  latencyMs?: number | null
  summary?: string | null
  params?: Record<string, unknown>
}
export type HacNode = Node<HacNodeData, 'hac'>

const ring: Record<string, string> = {
  running: 'border-link pulse-ring',
  awaiting_approval: 'border-warn',
  completed: 'border-ok',
  failed: 'border-bad',
  rejected: 'border-bad',
  cancelled: 'border-line border-dashed',
  partial: 'border-warn',
  skipped: 'border-line border-dashed',
  pending: 'border-line',
}

function FlowNodeImpl({ data, selected }: NodeProps<HacNode>) {
  const isTrigger = data.nodeType === 'trigger.manual'
  const inRun = data.status !== undefined
  return (
    <div
      className={clsx(
        'w-[224px] rounded-md border-[1.5px] bg-surface text-left',
        inRun ? (ring[data.status!] ?? 'border-line') : 'border-line-strong',
        selected && 'outline outline-2 outline-offset-2 outline-link',
        data.status === 'skipped' && 'opacity-75',
      )}
      aria-label={`${data.label}${inRun ? `, ${statusMeta(data.status!).label}` : ''}`}
    >
      {!isTrigger && <Handle type="target" position={Position.Left} aria-label="Input connector" />}
      <div className="flex items-center gap-2 border-b border-line/80 px-2.5 py-2">
        <AgentGlyph kind={isTrigger ? 'trigger' : glyphKind(data.agent, data.agentLevel ?? (data.nodeType === 'agent.task' ? 2 : undefined))} size={16} className="text-navy" />
        <div className="min-w-0 flex-1">
          <div className="truncate text-[13px] font-semibold text-ink">{data.label}</div>
          <div className="mono truncate text-[11px] text-ink-2">{data.nodeType}</div>
        </div>
      </div>
      <div className="flex min-h-[34px] flex-wrap items-center gap-1.5 px-2.5 py-1.5">
        {inRun ? (
          <>
            <StatusBadge status={data.status!} />
            {data.latencyMs != null && <span className="mono tnum text-[11px] text-ink-2">{formatMs(data.latencyMs)}</span>}
          </>
        ) : (
          <>
            {!isTrigger && data.risk && <RiskBadge risk={data.risk} />}
            {isTrigger && <span className="text-xs text-ink-2">Workflow inputs</span>}
            {!!data.issues && (
              <span className="inline-flex items-center gap-1 rounded-sm bg-bad-tint px-1.5 py-0.5 text-xs font-medium text-bad-ink">
                <AlertTriangle size={12} aria-hidden />{data.issues} {data.issues === 1 ? 'issue' : 'issues'}
              </span>
            )}
          </>
        )}
      </div>
      <Handle type="source" position={Position.Right} aria-label="Output connector" />
    </div>
  )
}

export const FlowNode = memo(FlowNodeImpl)
export const nodeTypes = { hac: FlowNode }
