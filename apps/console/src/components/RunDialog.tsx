import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { ValidationIssue } from '../api/client'
import { ApiError } from '../api/client'
import { useStartRun } from '../lib/queries'
import { Banner, Button, Field, Input, Modal } from './ui'

interface TField { name: string; type?: string; required?: boolean; default?: unknown }

export function RunDialog({ open, onOpenChange, workflowId, workflowName, fields }: {
  open: boolean; onOpenChange: (o: boolean) => void; workflowId: string; workflowName: string; fields: TField[]
}) {
  const nav = useNavigate()
  const start = useStartRun()
  const [values, setValues] = useState<Record<string, unknown>>(() => Object.fromEntries(fields.filter((f) => f.default !== undefined).map((f) => [f.name, f.default])))
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [serverError, setServerError] = useState<string | null>(null)
  const [issues, setIssues] = useState<ValidationIssue[]>([])

  const submit = () => {
    const e: Record<string, string> = {}
    const inputs: Record<string, unknown> = {}
    for (const f of fields) {
      const v = values[f.name]
      const empty = v === undefined || v === ''
      if (empty) { if (f.required !== false && f.type !== 'boolean') e[f.name] = 'This field is required.'; continue }
      if (f.type === 'number') {
        const n = Number(v)
        if (!Number.isFinite(n)) { e[f.name] = 'Enter a number.'; continue }
        inputs[f.name] = n
      } else inputs[f.name] = v
    }
    setErrors(e); setServerError(null); setIssues([])
    if (Object.keys(e).length) return
    start.mutate({ workflowId, inputs }, {
      onSuccess: (run) => { onOpenChange(false); nav(`/runs/${run.id}`) },
      onError: (err) => {
        const a = err as ApiError
        setServerError(a.message); setIssues(a.issues ?? [])
      },
    })
  }

  return (
    <Modal open={open} onOpenChange={onOpenChange} title={`Run “${workflowName}”`}
      description="This executes the saved workflow with the real engine. Policy decisions and approvals apply."
      footer={<><Button onClick={() => onOpenChange(false)}>Cancel</Button><Button variant="primary" busy={start.isPending} onClick={submit}>Run workflow</Button></>}>
      <form className="space-y-3" onSubmit={(ev) => { ev.preventDefault(); submit() }}>
        {fields.length === 0 && <p className="text-sm text-ink-2">This workflow takes no inputs.</p>}
        {fields.map((f) => {
          const id = `run-${f.name}`
          return (
            <Field key={f.name} label={f.name} htmlFor={id} required={f.required !== false && f.type !== 'boolean'} error={errors[f.name]}>
              {f.type === 'boolean' ? (
                <label className="flex items-center gap-2 text-sm"><input id={id} type="checkbox" className="size-4 accent-[#1E3A5F]"
                  checked={values[f.name] === true} onChange={(e) => setValues({ ...values, [f.name]: e.target.checked })} />Yes</label>
              ) : (
                <Input id={id} aria-invalid={!!errors[f.name]} aria-describedby={errors[f.name] ? `${id}-err` : undefined}
                  inputMode={f.type === 'number' ? 'decimal' : undefined} value={String(values[f.name] ?? '')}
                  onChange={(e) => setValues({ ...values, [f.name]: e.target.value })} />
              )}
            </Field>
          )
        })}
        {serverError && (
          <Banner tone="error">
            <p className="font-medium">{serverError}</p>
            {issues.filter((i) => i.severity === 'error').slice(0, 5).map((i, k) => <p key={k} className="mt-0.5 text-xs">{i.message}</p>)}
          </Banner>
        )}
        <button type="submit" className="sr-only">Run</button>
      </form>
    </Modal>
  )
}
