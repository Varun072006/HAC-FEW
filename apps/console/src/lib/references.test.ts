import { describe, expect, it } from 'vitest'
import type { CatalogNode, WorkflowDefinition } from '../api/client'
import { availableReferences, uniqueNodeId } from './references'
import { duration, formatMs, parseTs, timeAgo } from './format'

const catalog = new Map<string, CatalogNode>([
  ['hr.create_employee', { type: 'hr.create_employee', outputs: ['id', 'email'] } as CatalogNode],
  ['it.create_ticket', { type: 'it.create_ticket', outputs: ['id'] } as CatalogNode],
])
const def: WorkflowDefinition = {
  nodes: [
    { id: 'trigger', type: 'trigger.manual', position: { x: 0, y: 0 }, params: { fields: [{ name: 'name' }] } },
    { id: 'hr', type: 'hr.create_employee', label: 'Register', position: { x: 0, y: 0 }, params: {} },
    { id: 'laptop', type: 'it.create_ticket', position: { x: 0, y: 0 }, params: {} },
    { id: 'other', type: 'it.create_ticket', position: { x: 0, y: 0 }, params: {} },
  ],
  edges: [
    { id: 'a', source: 'trigger', target: 'hr' },
    { id: 'b', source: 'hr', target: 'laptop' },
  ],
}

describe('availableReferences', () => {
  it('offers trigger inputs and only upstream outputs', () => {
    const refs = availableReferences(def, 'laptop', catalog).map((r) => r.value)
    expect(refs).toContain('{{trigger.name}}')
    expect(refs).toContain('{{nodes.hr.output.id}}')
    expect(refs).not.toContain('{{nodes.other.output.id}}')
  })
  it('offers no node outputs to a node with no upstream', () => {
    const refs = availableReferences(def, 'hr', catalog)
    expect(refs.every((r) => r.group === 'Trigger input')).toBe(true)
  })
})

describe('uniqueNodeId', () => {
  it('avoids collisions', () => {
    expect(uniqueNodeId(def, 'finance.setup_payroll')).toBe('setup_payroll')
    expect(uniqueNodeId(def, 'it.create_ticket')).toBe('create_ticket')
    const d2 = { ...def, nodes: [...def.nodes, { id: 'create_ticket', type: 'x', position: { x: 0, y: 0 }, params: {} }] }
    expect(uniqueNodeId(d2, 'it.create_ticket')).toBe('create_ticket_2')
  })
})

describe('format', () => {
  it('treats naive API timestamps as UTC', () => {
    expect(parseTs('2026-01-01T10:00:00').toISOString()).toBe('2026-01-01T10:00:00.000Z')
  })
  it('formats durations and relative times', () => {
    expect(formatMs(850)).toBe('850 ms')
    expect(formatMs(2500)).toBe('2.50 s')
    expect(duration('2026-01-01T10:00:00', '2026-01-01T10:00:03')).toBe('3.00 s')
    const now = Date.parse('2026-01-01T10:05:00Z')
    expect(timeAgo('2026-01-01T10:00:00', now)).toBe('5m ago')
  })
})
