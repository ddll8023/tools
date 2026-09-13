import type { MindMapData } from '../types'

export interface MindMapTagFilterState {
  availableTags: string[]
  tagMatches: Set<string>
  tagContext: Set<string>
  dimmedNodes: Set<string>
}

function normalize(value: string): string {
  return value.trim().toLocaleLowerCase()
}

function walk(
  nodes: MindMapData[],
  visit: (node: MindMapData, ancestors: string[]) => void,
  ancestors: string[] = [],
) {
  for (const node of nodes) {
    visit(node, ancestors)
    if (node.children) {
      walk(node.children, visit, [...ancestors, node.id])
    }
  }
}

function addDescendantContext(node: MindMapData, context: Set<string>): void {
  for (const child of node.children ?? []) {
    context.add(child.id)
    addDescendantContext(child, context)
  }
}

export function analyzeMindMapTagFilter(
  roots: MindMapData[],
  activeTags: string[],
): MindMapTagFilterState {
  const normalizedTags = activeTags.map(normalize).filter(Boolean)
  const availableTags = new Set<string>()
  const tagMatches = new Set<string>()
  const tagContext = new Set<string>()
  const allNodeIds: string[] = []

  walk(roots, (node, ancestors) => {
    allNodeIds.push(node.id)

    for (const tag of node.tags || []) {
      availableTags.add(tag)
    }

    if (normalizedTags.length > 0) {
      const nodeTags = (node.tags || []).map(normalize)
      const hasMatchingTag = normalizedTags.some((tag) =>
        nodeTags.includes(tag),
      )
      if (hasMatchingTag) {
        tagMatches.add(node.id)
        tagContext.add(node.id)
        for (const ancestorId of ancestors) {
          tagContext.add(ancestorId)
        }
        addDescendantContext(node, tagContext)
      }
    }
  })

  const dimmedNodes = new Set<string>()
  if (normalizedTags.length > 0) {
    for (const id of allNodeIds) {
      if (!tagContext.has(id)) dimmedNodes.add(id)
    }
  }

  return {
    availableTags: Array.from(availableTags).sort((a, b) =>
      a.localeCompare(b),
    ),
    tagMatches,
    tagContext,
    dimmedNodes,
  }
}
