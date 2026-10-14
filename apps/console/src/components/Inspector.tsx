import { useState } from 'react'
import { Plus, Trash2 } from 'lucide-react'
import { useAgents, useTools } from '../lib/queries'
import type { CatalogNode, CatalogParam } from '../api/client'
import type { RefOption } from '../lib/references'
import { Button, Field, IconButton, Input, Select, Textarea, Chip } from './ui'

interface TriggerField { name: string; type: string; required?: boolean; default?: unknown }

function RefPicker({ refs, onPick, id }: { refs: RefOption[]; onPick: (v: string) => void; id: string }) {
  if (!refs.length) return null
  const groups = [...new Set(refs.map((r) => r.group))]
  return (
    <Select aria-label="Insert a reference to an earlier value" id={`${id}-ref`} value="" className="mt-1 h-8 text-xs"
      onChange={(e) => { if (e.target.value) onPick(e.target.value) }}>
      <option value="">Insert reference…</option>
      {groups.map((g) => (
        <optgroup key={g} label={g}>
          {refs.filter((r) => r.group === g).map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
        </optgroup>
      ))}
    </Select>
  )
}

/** Structured (JSON) parameter. Keeps the raw text while it is invalid so typing is never lost. */
function JsonParam({ id, value, onChange, readOnly }: { id: string; value: unknown; onChange: (v: unknown) => void; readOnly: boolean }) {
  const [text, setText] = useState(() => JSON.stringify(value ?? null, null, 2))
  const [err, setErr] = useState<string | null>(null)
  const [last, setLast] = useState(value)
  if (value !== last && JSON.stringify(value) !== JSON.stringify(safeParse(text))) { setLast(value); setText(JSON.stringify(value ?? null, null, 2)); setErr(null) }
  return (
    <>
      <Textarea id={id} disabled={readOnly} className="mono min-h-[110px] text-xs" aria-invalid={!!err} value={text}
        onChange={(e) => { setText(e.target.value); try { const v = JSON.parse(e.target.value); setErr(null); setLast(v); onChange(v) } catch (x) { setErr((x as Error).message) } }} />
      {err && <p className="mt-1 text-xs text-bad-ink" role="alert">Not valid JSON yet: {err}</p>}
    </>
  )
}
const safeParse = (t: string): unknown => { try { return JSON.parse(t) } catch { return undefined } }

/** Appends a scaffolded call for one of the chosen agent's own tools; the server still validates it. */
function ToolAdder({ agentId, ops, onChange }: { agentId: string; ops: unknown; onChange: (v: unknown) => void }) {
  const agents = useAgents()
  const tools = useTools()
  const allowed = agents.data?.find((a) => a.id === agentId)?.tools ?? []
  if (!agentId || !allowed.length) return <p className="mt-1 text-xs text-ink-2">Choose an agent to add tool calls from its allowed tools.</p>
  return (
    <Select aria-label="Add a tool call for this agent" value="" className="mt-1 h-8 text-xs"
      onChange={(e) => {
        const t = tools.data?.find((x) => x.name === e.target.value); if (!t) return
        const props = ((t.input_schema as { properties?: Record<string, { default?: unknown; type?: string }> }).properties) ?? {}
        const args = Object.fromEntries(Object.entries(props).map(([k, v]) => [k, v.default ?? (v.type === 'number' ? 0 : v.type === 'boolean' ? true : '')]))
        onChange([...(Array.isArray(ops) ? ops : []), { tool: t.name, arguments: args }])
      }}>
      <option value="">Add tool call…</option>
      {allowed.map((n) => <option key={n} value={n}>{n} ({tools.data?.find((x) => x.name === n)?.effect ?? '…'})</option>)}
    </Select>
  )
}

function ParamInput({ nodeId, p, value, onChange, refs, readOnly, siblings }: {
  nodeId: string; p: CatalogParam; value: unknown; onChange: (v: unknown) => void; refs: RefOption[]; readOnly: boolean; siblings: Record<string, unknown>
}) {
  const agents = useAgents()
  const id = `${nodeId}-${p.name}`
  const str = value === undefined || value === null ? '' : String(value)
  const append = (r: string) => onChange(p.type === 'boolean' || p.type === 'select' ? r : `${str}${r}`)
  let control
  if (p.name === 'agent_id' && p.type === 'string') {
    const list = (agents.data ?? []).filter((a) => a.level >= 1 && (a.status === 'active' || a.id === value))
    control = (
      <Select id={id} disabled={readOnly} value={str} onChange={(e) => onChange(e.target.value)}>
        <option value="">Select an agent…</option>
        {list.map((a) => <option key={a.id} value={a.id}>{a.name} · L{a.level}{a.status !== 'active' ? ` (${a.status})` : ''}</option>)}
      </Select>
    )
  } else if (p.type === 'json') {
    control = <><JsonParam id={id} value={value} onChange={onChange} readOnly={readOnly} />
      {p.name === 'operations' && !readOnly && <ToolAdder agentId={String(siblings.agent_id ?? '')} ops={value} onChange={onChange} />}</>
  } else if (p.type === 'boolean') {
    const isRef = typeof value === 'string' && value.includes('{{')
    control = (
      <Select id={id} disabled={readOnly} value={isRef ? String(value) : String(value ?? true)}
        onChange={(e) => onChange(e.target.value === 'true' ? true : e.target.value === 'false' ? false : e.target.value)}>
        <option value="true">Yes</option><option value="false">No</option>
        {isRef && <option value={String(value)}>{String(value)}</option>}
      </Select>
    )
  } else if (p.type === 'select') {
    const isRef = typeof value === 'string' && value.includes('{{')
    control = (
      <Select id={id} disabled={readOnly} value={str} onChange={(e) => onChange(e.target.value)}>
        {(p.options ?? []).map((o) => <option key={o} value={o}>{o}</option>)}
        {isRef && <option value={str}>{str}</option>}
      </Select>
    )
  } else if (p.type === 'text') {
    control = <Textarea id={id} disabled={readOnly} value={str} onChange={(e) => onChange(e.target.value)} />
  } else {
    control = <Input id={id} disabled={readOnly} value={str} inputMode={p.type === 'number' ? 'decimal' : undefined}
      className={str.includes('{{') ? 'mono text-xs' : undefined} onChange={(e) => onChange(e.target.value)} />
  }
  return (
    <Field label={p.label} htmlFor={id} required={p.required} hint={p.help || undefined}>
      {control}
      {!readOnly && p.type !== 'json' && p.name !== 'agent_id' && <RefPicker id={id} refs={refs} onPick={append} />}
    </Field>
  )
}

function TriggerFields({ nodeId, fields, onChange, readOnly }: { nodeId: string; fields: TriggerField[]; onChange: (f: TriggerField[]) => void; readOnly: boolean }) {
  const set = (i: number, patch: Partial<TriggerField>) => onChange(fields.map((f, j) => (j === i ? { ...f, ...patch } : f)))
  return (
    <div className="space-y-3">
      <p className="text-xs text-ink-2">Each field is asked for when the workflow is run. Use it elsewhere as <span className="mono">{'{{trigger.<name>}}'}</span>.</p>
      {fields.map((f, i) => (
        <fieldset key={i} className="space-y-2 rounded-md border border-line p-2.5">
          <legend className="sr-only">Input field {i + 1}</legend>
          <div className="flex items-end gap-2">
            <div className="flex-1"><Field label="Name" htmlFor={`${nodeId}-f${i}-n`}>
              <Input id={`${nodeId}-f${i}-n`} className="mono text-xs" disabled={readOnly} value={f.name} onChange={(e) => set(i, { name: e.target.value })} />
            </Field></div>
            {!readOnly && <IconButton label={`Remove field ${f.name || i + 1}`} onClick={() => onChange(fields.filter((_, j) => j !== i))}><Trash2 size={15} /></IconButton>}
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Field label="Type" htmlFor={`${nodeId}-f${i}-t`}>
              <Select id={`${nodeId}-f${i}-t`} disabled={readOnly} value={f.type} onChange={(e) => set(i, { type: e.target.value })}>
                <option value="string">Text</option><option value="number">Number</option><option value="boolean">Yes / No</option>
              </Select>
            </Field>
            <Field label="Default" htmlFor={`${nodeId}-f${i}-d`}>
              <Input id={`${nodeId}-f${i}-d`} disabled={readOnly} value={f.default === undefined ? '' : String(f.default)}
                onChange={(e) => set(i, { default: e.target.value === '' ? undefined : f.type === 'boolean' ? e.target.value === 'true' : f.type === 'number' && !Number.isNaN(Number(e.target.value)) ? Number(e.target.value) : e.target.value })} />
            </Field>
          </div>
          <label className="flex items-center gap-2 text-[13px]">
            <input type="checkbox" className="size-4 accent-[#1E3A5F]" disabled={readOnly} checked={f.required !== false} onChange={(e) => set(i, { required: e.target.checked })} />
            Required
          </label>
        </fieldset>
      ))}
      {!readOnly && <Button size="sm" onClick={() => onChange([...fields, { name: `field_${fields.length + 1}`, type: 'string', required: true }])}><Plus size={14} aria-hidden />Add input</Button>}
    </div>
  )
}

export function NodeInspector({ nodeId, spec, label, params, refs, readOnly, onLabel, onParam, onDelete, issues }: {
  nodeId: string; spec: CatalogNode; label: string; params: Record<string, unknown>; refs: RefOption[]
  readOnly: boolean; onLabel: (v: string) => void; onParam: (name: string, v: unknown) => void; onDelete?: () => void
  issues: { message: string }[]
}) {
  return (
    <div className="space-y-4">
      <div>
        <div className="flex flex-wrap items-center gap-1.5"><Chip tone="navy">{spec.category}</Chip>{spec.side_effect && <Chip tone="warn">Writes to a system</Chip>}</div>
        <p className="mt-2 text-sm text-ink-2">{spec.description}</p>
      </div>
      {issues.length > 0 && (
        <ul className="space-y-1 rounded-md border border-bad-ink/30 bg-bad-tint p-2.5 text-xs text-bad-ink" aria-label="Issues on this node">
          {issues.map((i, k) => <li key={k}>{i.message}</li>)}
        </ul>
      )}
      <Field label="Label" htmlFor={`${nodeId}-label`}>
        <Input id={`${nodeId}-label`} disabled={readOnly} value={label} onChange={(e) => onLabel(e.target.value)} />
      </Field>
      {spec.kind === 'trigger' ? (
        <TriggerFields nodeId={nodeId} readOnly={readOnly} fields={(params.fields as TriggerField[]) ?? []} onChange={(f) => onParam('fields', f)} />
      ) : spec.params.map((p) => (
        <ParamInput key={p.name} nodeId={nodeId} p={p} readOnly={readOnly} refs={refs} siblings={params}
          value={params[p.name] ?? p.default} onChange={(v) => onParam(p.name, v)} />
      ))}
      {spec.outputs.length > 0 && (
        <div><div className="text-[13px] font-medium">Provides to later steps</div>
          <div className="mt-1 flex flex-wrap gap-1">{spec.outputs.map((o) => <Chip key={o} mono>{o}</Chip>)}</div></div>
      )}
      {!readOnly && onDelete && <Button variant="secondary" size="sm" onClick={onDelete} className="text-bad-ink"><Trash2 size={14} aria-hidden />Delete step</Button>}
    </div>
  )
}
