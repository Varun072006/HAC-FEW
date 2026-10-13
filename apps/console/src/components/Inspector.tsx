import { Plus, Trash2 } from 'lucide-react'
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

function ParamInput({ nodeId, p, value, onChange, refs, readOnly }: {
  nodeId: string; p: CatalogParam; value: unknown; onChange: (v: unknown) => void; refs: RefOption[]; readOnly: boolean
}) {
  const id = `${nodeId}-${p.name}`
  const str = value === undefined || value === null ? '' : String(value)
  const append = (r: string) => onChange(p.type === 'boolean' || p.type === 'select' ? r : `${str}${r}`)
  let control
  if (p.type === 'boolean') {
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
      {!readOnly && <RefPicker id={id} refs={refs} onPick={append} />}
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
        <ParamInput key={p.name} nodeId={nodeId} p={p} readOnly={readOnly} refs={refs}
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
