import { useAuth } from '../auth/AuthContext'
import { Card, Chip, EmptyState, ErrorState, KV, Loading, PageHeader, SectionTitle, Table } from '../components/ui'
import { useOrg } from '../lib/queries'

export default function Settings() {
  const { user, can } = useAuth()
  const admin = can('org:admin')
  const q = useOrg(admin)
  return (
    <>
      <PageHeader title="Organization" subtitle="Your session and, for administrators, the environment and accounts." />
      <SectionTitle>Your session</SectionTitle>
      <Card className="mb-8 max-w-xl p-4">
        <KV items={[['Name', user?.display_name], ['Username', user?.username], ['Role', <Chip key="r" tone="navy" mono>{user?.role}</Chip>],
          ['Employee record', user?.employee_id ?? 'Not linked'], ['Permissions', <span key="p" className="mono text-xs">{user?.permissions.join(', ')}</span>]]} />
        <p className="mt-3 text-xs text-ink-2">The console hides actions you cannot perform, but every request is authorized again on the server using your stored role.</p>
      </Card>

      {!admin ? <EmptyState title="Organization administration is restricted">Environment details and user accounts need the org:admin permission.</EmptyState>
        : q.isLoading ? <Loading /> : q.error || !q.data ? <ErrorState error={q.error} retry={() => q.refetch()} /> : (
          <>
            <SectionTitle>Environment</SectionTitle>
            <Card className="mb-8 max-w-xl p-4"><KV items={[['Environment', q.data.environment], ['Platform database', <span key="d" className="mono text-xs">{q.data.database}</span>]]} /></Card>
            <SectionTitle>Accounts</SectionTitle>
            <Table caption="User accounts" head={['Name', 'Username', 'Role', 'Employee record']}>
              {q.data.users.map((u) => (
                <tr key={u.id}><td className="px-3 py-2">{u.display_name}</td><td className="mono px-3 py-2 text-xs">{u.username}</td>
                  <td className="px-3 py-2"><Chip tone="navy" mono>{u.role}</Chip></td><td className="mono px-3 py-2 text-xs text-ink-2">{u.employee_id ?? '—'}</td></tr>
              ))}
            </Table>
            <p className="mt-2 text-xs text-ink-2">Account creation and role changes are not exposed in the UI yet; they are an open gap tracked in the README.</p>
          </>
        )}
    </>
  )
}
