import { useEffect, useRef, useState } from 'react'
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createSseParser } from './sse'
import { api, tokenStore, unwrap, type RunEvent, type Schema, type WorkflowDefinition } from '../api/client'

const TERMINAL = new Set(['completed', 'partial', 'failed', 'rejected', 'cancelled'])
export const isTerminal = (s?: string) => !!s && TERMINAL.has(s)

export const useCatalog = () => useQuery({ queryKey: ['catalog'], staleTime: Infinity, queryFn: () => unwrap(api.GET('/catalog/nodes')) })
export const useTemplates = () => useQuery({ queryKey: ['templates'], staleTime: Infinity, queryFn: () => unwrap(api.GET('/templates')) })
export const useWorkflows = () => useQuery({ queryKey: ['workflows'], queryFn: () => unwrap(api.GET('/workflows')) })
export const useWorkflow = (id?: string) => useQuery({
  queryKey: ['workflow', id], enabled: !!id,
  queryFn: () => unwrap(api.GET('/workflows/{workflow_id}', { params: { path: { workflow_id: id! } } })),
})

export const useRuns = (status?: string) => useQuery({
  queryKey: ['runs', status ?? 'all'], placeholderData: keepPreviousData, refetchInterval: 5000,
  queryFn: () => unwrap(api.GET('/runs', { params: { query: { status: status || undefined, limit: 100 } } })),
})

export const useRun = (id?: string) => useQuery({
  queryKey: ['run', id], enabled: !!id,
  queryFn: () => unwrap(api.GET('/runs/{run_id}', { params: { path: { run_id: id! } } })),
  // Live while the run is moving; slower while it waits for a human, who may be a different user.
  refetchInterval: (q) => {
    const s = q.state.data?.status
    if (!s || isTerminal(s)) return false
    return s === 'awaiting_approval' ? 3000 : 1000
  },
})

/**
 * Live execution events. Preferred transport is the backend's Server-Sent Events stream (read with fetch so
 * the bearer token can be sent); if the stream cannot be opened it falls back to cursor polling. Either way
 * every event comes from the persisted log, so a refresh or reconnect resumes exactly from the last seq seen.
 */
export function useRunEvents(runId: string | undefined) {
  const [events, setEvents] = useState<RunEvent[]>([])
  const [transport, setTransport] = useState<'stream' | 'polling' | 'idle'>('idle')
  const cursor = useRef(0)
  const qc = useQueryClient()

  useEffect(() => { setEvents([]); cursor.current = 0; setTransport('idle') }, [runId])

  useEffect(() => {
    if (!runId) return
    const ctl = new AbortController()
    let timer: ReturnType<typeof setTimeout> | undefined
    let refresh: ReturnType<typeof setTimeout> | undefined
    const refreshRun = () => { if (refresh) return; refresh = setTimeout(() => { refresh = undefined; qc.invalidateQueries({ queryKey: ['run', runId] }) }, 250) }
    const push = (batch: RunEvent[]) => {
      const fresh = batch.filter((e) => e.seq > cursor.current)
      if (!fresh.length) return
      cursor.current = fresh[fresh.length - 1].seq
      setEvents((prev) => [...prev, ...fresh])
    }
    const poll = async () => {
      setTransport('polling')
      try {
        const page = await unwrap(api.GET('/runs/{run_id}/events', { params: { path: { run_id: runId }, query: { after: cursor.current, limit: 500 } } }))
        push(page.events)
        if (page.events.length) refreshRun()
        if (page.terminal && page.events.length === 0) return
      } catch { /* retry on the next tick */ }
      if (!ctl.signal.aborted) timer = setTimeout(poll, 1500)
    }
    const stream = async () => {
      try {
        const res = await fetch(`/api/v1/runs/${runId}/stream?after=${cursor.current}`, {
          headers: { Authorization: `Bearer ${tokenStore.get() ?? ''}`, Accept: 'text/event-stream' }, signal: ctl.signal,
        })
        if (!res.ok || !res.body) throw new Error(`stream ${res.status}`)
        setTransport('stream')
        const reader = res.body.getReader()
        const dec = new TextDecoder()
        const parser = createSseParser()
        for (;;) {
          const { value, done } = await reader.read()
          if (done) break
          for (const f of parser.push(dec.decode(value, { stream: true }))) {
            if (f.event === 'run_event') { push([JSON.parse(f.data) as RunEvent]); refreshRun() }
            if (f.event === 'end') { refreshRun(); return }
          }
        }
        if (!ctl.signal.aborted) timer = setTimeout(stream, 500)   // server closes long streams; resume from the cursor
      } catch (err) {
        if (ctl.signal.aborted) return
        void err
        poll()
      }
    }
    stream()
    return () => { ctl.abort(); if (timer) clearTimeout(timer); if (refresh) clearTimeout(refresh) }
  }, [runId, qc])

  return { events, transport }
}

export const useApprovals = (status?: 'pending' | 'approved' | 'rejected' | 'cancelled') => useQuery({
  queryKey: ['approvals', status ?? 'all'], refetchInterval: 4000, placeholderData: keepPreviousData,
  queryFn: () => unwrap(api.GET('/approvals', { params: { query: { status } } })),
})

export const useOverview = () => useQuery({ queryKey: ['overview'], refetchInterval: 5000, queryFn: () => unwrap(api.GET('/overview')) })
export const useAgents = (includeArchived = false) => useQuery({
  queryKey: ['agents', includeArchived], queryFn: () => unwrap(api.GET('/agents', { params: { query: { include_archived: includeArchived } } })),
})
export const useAgent = (id?: string) => useQuery({
  queryKey: ['agent', id], enabled: !!id,
  queryFn: () => unwrap(api.GET('/agents/{agent_id}', { params: { path: { agent_id: id! } } })),
})
export const useAgentVersions = (id?: string) => useQuery({
  queryKey: ['agent-versions', id], enabled: !!id,
  queryFn: () => unwrap(api.GET('/agents/{agent_id}/versions', { params: { path: { agent_id: id! } } })),
})
export const useTools = () => useQuery({ queryKey: ['tools'], staleTime: Infinity, queryFn: () => unwrap(api.GET('/tools')) })
export const useProviders = () => useQuery({ queryKey: ['providers'], queryFn: () => unwrap(api.GET('/gateway/providers')) })

export function useSaveAgent() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { id?: string; config: Record<string, unknown>; note?: string }) => v.id
      ? unwrap(api.PUT('/agents/{agent_id}', { params: { path: { agent_id: v.id } }, body: { config: v.config, change_note: v.note || undefined } }))
      : unwrap(api.POST('/agents', { body: { config: v.config } })),
    onSuccess: () => { for (const k of ['agents', 'agent', 'agent-versions']) qc.invalidateQueries({ queryKey: [k] }) },
  })
}
export function useAgentStatus() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { id: string; status: 'active' | 'disabled' | 'archived' }) =>
      unwrap(api.POST('/agents/{agent_id}/status', { params: { path: { agent_id: v.id } }, body: { status: v.status } })),
    onSuccess: () => { for (const k of ['agents', 'agent']) qc.invalidateQueries({ queryKey: [k] }) },
  })
}
export function useCreatePlan() {
  return useMutation({
    mutationFn: (v: { objective: string; mode: 'auto' | 'deterministic' | 'llm' | 'structured'; plan?: Record<string, unknown> }) =>
      unwrap(api.POST('/plans', { body: v })),
  })
}
export function useExecutePlan() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { id: string; inputs: Record<string, unknown> }) =>
      unwrap(api.POST('/plans/{plan_id}/execute', { params: { path: { plan_id: v.id } }, body: { inputs: v.inputs } })),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['runs'] }); qc.invalidateQueries({ queryKey: ['workflows'] }); qc.invalidateQueries({ queryKey: ['overview'] }) },
  })
}
export function useCancelRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => unwrap(api.POST('/runs/{run_id}/cancel', { params: { path: { run_id: id } } })),
    onSettled: () => { for (const k of ['run', 'runs', 'approvals', 'overview']) qc.invalidateQueries({ queryKey: [k] }) },
  })
}
export const useConnectors = () => useQuery({ queryKey: ['connectors'], queryFn: () => unwrap(api.GET('/connectors')) })
export const usePolicies = () => useQuery({ queryKey: ['policies'], queryFn: () => unwrap(api.GET('/policies')) })
export const useUsage = (enabled = true) => useQuery({ queryKey: ['usage'], enabled, queryFn: () => unwrap(api.GET('/usage')) })
export const useAudit = (action: string, enabled = true) => useQuery({
  queryKey: ['audit', action], enabled, placeholderData: keepPreviousData,
  queryFn: () => unwrap(api.GET('/audit', { params: { query: { action: action || undefined, limit: 100 } } })),
})
export const useOrg = (enabled = true) => useQuery({ queryKey: ['org'], enabled, queryFn: () => unwrap(api.GET('/org')) })

export function useValidate(def: WorkflowDefinition | null) {
  return useQuery({
    queryKey: ['validate', JSON.stringify(def)], enabled: !!def, placeholderData: keepPreviousData, staleTime: 30_000,
    queryFn: () => unwrap(api.POST('/workflows/validate', { body: def! })),
  })
}

export function useSaveWorkflow() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (v: { id?: string; version?: number; name: string; description: string; definition: WorkflowDefinition; template_id?: string | null }) => {
      if (!v.id) {
        return unwrap(api.POST('/workflows', { body: { name: v.name, description: v.description, definition: v.definition, template_id: v.template_id } }))
      }
      return unwrap(api.PUT('/workflows/{workflow_id}', {
        params: { path: { workflow_id: v.id } },
        body: { expected_version: v.version!, name: v.name, description: v.description, definition: v.definition },
      }))
    },
    onSuccess: (w) => {
      qc.setQueryData(['workflow', w.id], w)
      qc.invalidateQueries({ queryKey: ['workflows'] })
      qc.invalidateQueries({ queryKey: ['overview'] })
    },
  })
}

export function useStartRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { workflowId: string; inputs: Record<string, unknown> }) =>
      unwrap(api.POST('/workflows/{workflow_id}/runs', { params: { path: { workflow_id: v.workflowId } }, body: { inputs: v.inputs } })),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['runs'] }); qc.invalidateQueries({ queryKey: ['overview'] }) },
  })
}

export function useDecide() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (v: { id: string; decision: 'approve' | 'reject'; comment?: string }) =>
      unwrap(api.POST('/approvals/{approval_id}/decision', { params: { path: { approval_id: v.id } }, body: { decision: v.decision, comment: v.comment || undefined } })),
    onSettled: () => {
      for (const k of ['approvals', 'run', 'runs', 'overview', 'audit']) qc.invalidateQueries({ queryKey: [k] })
    },
  })
}

export type { Schema }
