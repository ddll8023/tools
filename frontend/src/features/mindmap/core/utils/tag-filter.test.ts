import { describe, expect, it } from 'vitest'
import type { MindMapData } from '../types'
import { analyzeMindMapTagFilter } from './tag-filter'

const data: MindMapData[] = [
  {
    id: 'root',
    text: 'Project Plan',
    children: [
      {
        id: 'frontend',
        text: 'React UI',
        tags: ['frontend'],
        children: [{ id: 'child', text: 'Component' }],
      },
      {
        id: 'backend',
        text: 'API Proxy',
        tags: ['backend'],
      },
    ],
  },
]

describe('mind map tag filters', () => {
  it('collects available tags', () => {
    const result = analyzeMindMapTagFilter(data, [])

    expect(result.availableTags).toEqual(['backend', 'frontend'])
  })

  it('keeps ancestor context and dims unrelated nodes', () => {
    const result = analyzeMindMapTagFilter(data, ['frontend'])

    expect(result.tagMatches.has('frontend')).toBe(true)
    expect(result.tagContext.has('root')).toBe(true)
    expect(result.dimmedNodes.has('backend')).toBe(true)
    expect(result.dimmedNodes.has('frontend')).toBe(false)
    expect(result.dimmedNodes.has('child')).toBe(false)
  })
})
