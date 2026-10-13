import { Check, Minus } from 'lucide-react'
import { Card, Chip, ErrorState, Loading, Mono, PageHeader, RiskBadge, SectionTitle, Table } from '../components/ui'
import { usePolicies } from '../lib/queries'
import { titleCase } from '../lib/format'
import { AGENT_LABEL } from '../components/Glyphs'

const OUTCOME: Record<string, string> = { blocked: 'Blocked', approval_required: 'Needs human approval', auto_approved: 'Auto-approved', allowed: 'Allowed' }

export default function Policies() {
  const q = usePolicies()
  if (q.isLoading) return <Loading />
  if (q.error || !q.data) return <ErrorState error={q.error} retry={() => q.refetch()} />
  const p = q.data
  const roles = Object.keys(p.role_permissions)
  const perms = [...new Set(Object.values(p.role_permissions).flat())].sort()

  return (
    <>
      <PageHeader title="Policies & permissions" subtitle="Read live from the governance engine and authorization layer that enforce these rules, not a copy. Changing policy is a code-reviewed change in this build." />

      <SectionTitle>Decision rules</SectionTitle>
      <Table caption="Governance decision rules" head={['Rule', 'Applies to', 'Risk', 'Outcome', 'Description']}>
        {p.rules.map((r) => (
          <tr key={String(r.rule_id)} className="align-top">
            <td className="px-3 py-2"><Mono>{String(r.rule_id)}</Mono></td>
            <td className="px-3 py-2"><Mono className="text-ink-2">{String(r.tool)}</Mono></td>
            <td className="px-3 py-2"><RiskBadge risk={String(r.risk)} /></td>
            <td className="px-3 py-2">{OUTCOME[String(r.outcome)] ?? String(r.outcome)}</td>
            <td className="px-3 py-2 text-ink-2">{String(r.description)}</td>
          </tr>
        ))}
      </Table>

      <div className="mt-8 grid gap-6 lg:grid-cols-2">
        <section>
          <SectionTitle>Approval slots</SectionTitle>
          <Card className="divide-y divide-line/70">
            {Object.entries(p.approval_slots).map(([rule, slots]) => (
              <div key={rule} className="p-3.5">
                <Mono>{rule}</Mono>
                <ul className="mt-1.5 space-y-1 text-sm">{slots.map((roles, i) => <li key={i}>Approval {i + 1}: {roles.map((r) => <Chip key={r} tone="navy">{r}</Chip>)}</li>)}</ul>
              </div>
            ))}
            <p className="p-3.5 text-xs text-ink-2">The person who started a run can never approve it, and each person can decide once.</p>
          </Card>
        </section>
        <section>
          <SectionTitle>Agent tool allow-lists</SectionTitle>
          <Card className="divide-y divide-line/70">
            {Object.entries(p.agent_tool_permissions).map(([agent, tools]) => (
              <div key={agent} className="p-3.5"><div className="text-sm font-medium">{AGENT_LABEL[agent] ?? titleCase(agent)}</div>
                <div className="mt-1.5 flex flex-wrap gap-1">{tools.map((t) => <Chip key={t} mono>{t}</Chip>)}</div></div>
            ))}
          </Card>
        </section>
      </div>

      <section className="mt-8">
        <SectionTitle>Role permissions</SectionTitle>
        <div className="overflow-x-auto rounded-md border border-line bg-surface">
          <table className="w-full border-collapse text-sm">
            <caption className="sr-only">Permissions granted to each role</caption>
            <thead><tr className="border-b border-line bg-canvas"><th scope="col" className="px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-ink-2">Permission</th>
              {roles.map((r) => <th key={r} scope="col" className="px-2 py-2 text-center text-xs font-semibold text-ink-2">{r}</th>)}</tr></thead>
            <tbody className="divide-y divide-line/70">
              {perms.map((perm) => (
                <tr key={perm}><th scope="row" className="px-3 py-1.5 text-left font-normal"><Mono>{perm}</Mono></th>
                  {roles.map((r) => (
                    <td key={r} className="px-2 py-1.5 text-center">{p.role_permissions[r].includes(perm)
                      ? <Check size={15} className="mx-auto text-ok-ink" aria-label="Granted" /> : <Minus size={15} className="mx-auto text-line-strong" aria-label="Not granted" />}</td>
                  ))}</tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  )
}
