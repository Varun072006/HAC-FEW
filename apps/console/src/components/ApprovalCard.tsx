import { useState } from 'react'
import { Link } from 'react-router-dom'
import { CheckCircle2, Circle, ShieldAlert, XCircle } from 'lucide-react'
import type { Approval } from '../api/client'
import { useDecide } from '../lib/queries'
import { formatValue, money, timeAgo } from '../lib/format'
import { Banner, Button, Card, Field, KV, Modal, Mono, RiskBadge, StatusBadge, Textarea } from './ui'

const ROLE_LABEL: Record<string, string> = { director: 'Director', controller: 'Controller', manager: 'Line manager' }
const slotLabel = (roles: string[]) => (roles.length > 1 ? 'Manager or Director' : ROLE_LABEL[roles[0]] ?? roles[0])

export function ApprovalCard({ a, compact }: { a: Approval; compact?: boolean }) {
  const decide = useDecide()
  const [mode, setMode] = useState<null | 'approve' | 'reject'>(null)
  const [comment, setComment] = useState('')
  const [err, setErr] = useState<string | null>(null)

  const amount = a.params['amount']
  const params = Object.entries(a.params).filter(([k]) => !['description'].includes(k))
  const submit = () => {
    if (mode === 'reject' && !comment.trim()) { setErr('A reason is required when rejecting.'); return }
    setErr(null)
    decide.mutate({ id: a.id, decision: mode!, comment: comment.trim() || undefined }, {
      onSuccess: () => { setMode(null); setComment('') },
      onError: (e) => setErr(e.message),
    })
  }

  return (
    <Card as="div" className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <ShieldAlert size={16} className="text-warn" aria-hidden />
            <h3 className="text-sm font-semibold">{a.node_label ?? a.node_id}</h3>
            <RiskBadge risk={a.risk_level} /><StatusBadge status={a.status} />
          </div>
          <p className="mt-1 text-xs text-ink-2">
            {a.workflow_name} · requested by {a.requested_by_name} · {timeAgo(a.requested_at)}
            {!compact && <> · <Link className="text-link underline" to={`/runs/${a.run_id}`}>View run <Mono>{a.run_id}</Mono></Link></>}
          </p>
        </div>
        {amount !== undefined && <div className="tnum text-right text-lg font-semibold">{money(amount)}</div>}
      </div>

      <div className="mt-3 rounded-md border border-line bg-canvas p-3">
        <p className="text-sm"><span className="font-medium">Why approval is needed: </span>{a.reason}</p>
        {a.rule_id && <p className="mt-1 text-xs text-ink-2">Rule <Mono>{a.rule_id}</Mono></p>}
      </div>

      <div className="mt-3 grid gap-4 md:grid-cols-2">
        <div>
          <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-ink-2">What will be executed</div>
          <KV items={[['Tool', <Mono key="t">{a.tool_name}</Mono>], ...params.map(([k, v]) => [k, formatValue(v)] as [string, string])]} />
          {typeof a.params['description'] === 'string' && <p className="mt-2 text-sm text-ink-2">“{String(a.params['description'])}”</p>}
        </div>
        <div>
          <div className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-ink-2">Required approvals</div>
          <ul className="space-y-1.5">
            {a.required_slots.map((roles, i) => {
              const d = a.decisions.find((x) => x.decision === 'approve' && a.filled_slots.includes(i) && roles.includes(x.approver_role))
              return (
                <li key={i} className="flex items-center gap-2 text-sm">
                  {a.filled_slots.includes(i) ? <CheckCircle2 size={15} className="text-ok-ink" aria-label="Approved" /> : <Circle size={15} className="text-ink-2" aria-label="Waiting" />}
                  <span>{slotLabel(roles)}</span>
                  <span className="text-ink-2">{d ? `— ${d.approver_name}` : a.status === 'pending' ? '— waiting' : ''}</span>
                </li>
              )
            })}
            {a.decisions.filter((d) => d.decision === 'reject').map((d, i) => (
              <li key={`r${i}`} className="flex items-center gap-2 text-sm text-bad-ink"><XCircle size={15} aria-label="Rejected" />Rejected by {d.approver_name}{d.comment ? `: ${d.comment}` : ''}</li>
            ))}
          </ul>
        </div>
      </div>

      {a.status === 'pending' && (
        <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-line pt-3">
          <Button variant="primary" disabled={!a.can_decide} onClick={() => setMode('approve')}>Approve…</Button>
          <Button disabled={!a.can_decide} onClick={() => setMode('reject')}>Reject…</Button>
          {!a.can_decide && <span className="text-xs text-ink-2">You cannot decide this: it needs another person or role, or you already decided.</span>}
        </div>
      )}

      <Modal open={mode !== null} onOpenChange={(o) => { if (!o) { setMode(null); setErr(null) } }}
        title={mode === 'approve' ? 'Approve this action?' : 'Reject this action?'}
        description={mode === 'approve' ? `${a.tool_name} will run with exactly the parameters shown. This is recorded in the audit trail under your name.`
          : 'The workflow will stop and nothing will be executed. Your reason is recorded in the audit trail.'}
        footer={<><Button onClick={() => setMode(null)}>Cancel</Button>
          <Button variant={mode === 'approve' ? 'primary' : 'danger'} busy={decide.isPending} onClick={submit}>{mode === 'approve' ? 'Approve' : 'Reject'}</Button></>}>
        <Field label={mode === 'reject' ? 'Reason' : 'Comment (optional)'} htmlFor={`cmt-${a.id}`} required={mode === 'reject'}>
          <Textarea id={`cmt-${a.id}`} value={comment} onChange={(e) => setComment(e.target.value)} />
        </Field>
        {err && <div className="mt-3"><Banner tone="error">{err}</Banner></div>}
      </Modal>
    </Card>
  )
}
