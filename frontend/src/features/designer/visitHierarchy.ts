import type { VisitDefinitionResponse } from '@/api/model'

export interface VisitHierarchyNode {
  visit: VisitDefinitionResponse
  children: VisitHierarchyNode[]
}

export interface FlattenedVisit {
  visit: VisitDefinitionResponse
  depth: number
  parentName?: string
}

export const visitKind = (visit: VisitDefinitionResponse) =>
  visit.definition_kind ?? (visit.visit_type === 'cycle' ? 'cycle' : 'visit')

const compareAtLevel = (a: VisitDefinitionResponse, b: VisitDefinitionResponse) =>
  a.display_order - b.display_order
  || a.visit_number - b.visit_number
  || a.id.localeCompare(b.id)

const isSelectableVisit = (visit: VisitDefinitionResponse) =>
  ['visit', 'cycle_visit'].includes(visitKind(visit))

/** Build the folder/cycle tree while sorting independently at every level. */
export function buildVisitHierarchy(visits: VisitDefinitionResponse[]): VisitHierarchyNode[] {
  const byId = new Map(visits.map((visit) => [visit.id, visit]))
  const ownedIds = new Set<string>()
  const childrenByParent = new Map<string, VisitDefinitionResponse[]>()

  for (const visit of visits) {
    if (visit.parent_folder_id && byId.has(visit.parent_folder_id)) {
      const children = childrenByParent.get(visit.parent_folder_id) ?? []
      children.push(visit)
      childrenByParent.set(visit.parent_folder_id, children)
      ownedIds.add(visit.id)
    }
  }
  for (const cycle of visits.filter((visit) => visitKind(visit) === 'cycle')) {
    const children = childrenByParent.get(cycle.id) ?? []
    for (const childId of cycle.member_visit_ids ?? []) {
      const child = byId.get(childId)
      if (child && !children.some((item) => item.id === child.id)) children.push(child)
      if (child) ownedIds.add(child.id)
    }
    childrenByParent.set(cycle.id, children)
  }

  const makeNode = (visit: VisitDefinitionResponse): VisitHierarchyNode => ({
    visit,
    children: [...(childrenByParent.get(visit.id) ?? [])]
      .sort(compareAtLevel)
      .map(makeNode),
  })

  return visits
    .filter((visit) => !ownedIds.has(visit.id))
    .sort(compareAtLevel)
    .map(makeNode)
}

/** Return real visit leaves in the hierarchy's visual order. */
export function flattenSelectableVisits(nodes: VisitHierarchyNode[]): FlattenedVisit[] {
  const flattened: FlattenedVisit[] = []
  const walk = (node: VisitHierarchyNode, depth: number, parentName?: string) => {
    if (isSelectableVisit(node.visit)) {
      flattened.push({ visit: node.visit, depth, parentName })
      return
    }
    for (const child of node.children) walk(child, depth + 1, node.visit.name)
  }
  for (const node of nodes) walk(node, 0)
  return flattened
}

export function selectableVisitIds(node: VisitHierarchyNode): string[] {
  if (isSelectableVisit(node.visit)) return [node.visit.id]
  return node.children.flatMap(selectableVisitIds)
}

/** Expand legacy folder/cycle member IDs to the real visit leaves beneath them. */
export function expandToSelectableVisitIds(nodes: VisitHierarchyNode[], ids: string[]): string[] {
  const nodeById = new Map<string, VisitHierarchyNode>()
  const index = (node: VisitHierarchyNode) => {
    nodeById.set(node.visit.id, node)
    node.children.forEach(index)
  }
  nodes.forEach(index)

  const expanded = ids.flatMap((id) => {
    const node = nodeById.get(id)
    return node ? selectableVisitIds(node) : []
  })
  return [...new Set(expanded)]
}
