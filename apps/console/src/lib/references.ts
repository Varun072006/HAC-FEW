import type { CatalogNode, WorkflowDefinition } from '../api/client'

export interface RefOption { value: string; label: string; group: string }

/** All `{{...}}` references a node may legally use: trigger inputs and outputs of upstream nodes. */
export function availableReferences(
  def: WorkflowDefinition, nodeId: string, catalog: Map<string, CatalogNode>,
): RefOption[] {
  const parents = new Map<string, string[]>()
  for (const e of def.edges) parents.set(e.target, [...(parents.get(e.target) ?? []), e.source])
  const up = new Set<string>()
  const stack = [nodeId]
  while (stack.length) {
    for (const p of parents.get(stack.pop()!) ?? []) if (!up.has(p)) { up.add(p); stack.push(p) }
  }
  const out: RefOption[] = []
  const trigger = def.nodes.find((n) => n.type === 'trigger.manual')
  const fields = ((trigger?.params as { fields?: { name: string }[] } | undefined)?.fields ?? [])
  for (const f of fields) out.push({ value: `{{trigger.${f.name}}}`, label: f.name, group: 'Trigger input' })
  for (const n of def.nodes) {
    if (!up.has(n.id) || n.type === 'trigger.manual') continue
    for (const o of catalog.get(n.type)?.outputs ?? []) {
      out.push({ value: `{{nodes.${n.id}.output.${o}}}`, label: `${n.label ?? n.id} → ${o}`, group: 'Upstream output' })
    }
  }
  return out
}

export function uniqueNodeId(def: WorkflowDefinition, type: string): string {
  const base = type.split('.').pop()!.replace(/[^A-Za-z0-9_-]/g, '_')
  const used = new Set(def.nodes.map((n) => n.id))
  if (!used.has(base)) return base
  let i = 2
  while (used.has(`${base}_${i}`)) i++
  return `${base}_${i}`
}
