import { describe, expect, it } from 'vitest'
import { exportMindMapToXMind, parseXMindFile } from './xmind'

describe('XMind import and export', () => {
  it('round-trips multiple roots through a modern XMind archive', async () => {
    const source = [
      {
        id: 'root-1',
        text: 'Root & One',
        remark: 'A note',
        tags: ['important'],
        children: [{ id: 'child-1', text: 'Child <One>' }],
      },
      { id: 'root-2', text: 'Root Two' },
    ]

    const imported = await parseXMindFile(exportMindMapToXMind(source))

    expect(imported).toEqual(source)
  })
})
