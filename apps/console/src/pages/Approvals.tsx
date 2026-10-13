import { useState } from 'react'
import * as Tabs from '@radix-ui/react-tabs'
import { ApprovalCard } from '../components/ApprovalCard'
import { EmptyState, ErrorState, Loading, PageHeader } from '../components/ui'
import { useApprovals } from '../lib/queries'

const tabCls = 'border-b-2 border-transparent px-3 py-2 text-sm text-ink-2 hover:text-ink data-[state=active]:border-navy data-[state=active]:font-medium data-[state=active]:text-navy'

function List({ status }: { status: 'pending' | 'approved' | 'rejected' | undefined }) {
  const q = useApprovals(status)
  if (q.isLoading) return <Loading />
  if (q.error) return <ErrorState error={q.error} retry={() => q.refetch()} />
  const items = status === undefined ? q.data!.items.filter((a) => a.status !== 'pending') : q.data!.items
  if (!items.length) return <EmptyState title={status === 'pending' ? 'Nothing is waiting for approval' : 'No decided approvals yet'}>
    {status === 'pending' ? 'When a workflow reaches a step that policy marks as needing a human, it parks here until the right people decide.' : 'Approved and rejected requests will be listed here with who decided and when.'}</EmptyState>
  return <div className="space-y-3">{items.map((a) => <ApprovalCard key={a.id} a={a} />)}</div>
}

export default function Approvals() {
  const [tab, setTab] = useState('pending')
  return (
    <>
      <PageHeader title="Approvals" subtitle="Decisions are enforced on the server: your role, separation of duties, and one decision per person. Approved steps execute exactly once." />
      <Tabs.Root value={tab} onValueChange={setTab}>
        <Tabs.List className="mb-4 flex border-b border-line" aria-label="Approval views">
          <Tabs.Trigger value="pending" className={tabCls}>Pending</Tabs.Trigger>
          <Tabs.Trigger value="history" className={tabCls}>History</Tabs.Trigger>
        </Tabs.List>
        <Tabs.Content value="pending"><List status="pending" /></Tabs.Content>
        <Tabs.Content value="history"><List status={undefined} /></Tabs.Content>
      </Tabs.Root>
    </>
  )
}
