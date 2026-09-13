import { describe, expect, it } from 'vitest'
import type { MindMapData } from '../types'
import { latexPlugin } from '../plugins/latex'
import { multiLinePlugin } from '../plugins/multi-line'
import { parseInlineMarkdown } from './inline-markdown'
import { parseMarkdownMultiRoot, toMarkdownMultiRoot } from './markdown'

const latexPlugins = [latexPlugin, multiLinePlugin]

// Compare structure only — parsing assigns fresh ids, so ids are ignored.
const shape = (n: MindMapData): unknown => ({
  text: n.text,
  children: n.children?.map(shape),
})

describe('markdown round-trip', () => {
  it('parses ATX headings and their following lists as one hierarchy', () => {
    const roots = parseMarkdownMultiRoot(`# Root

## First section
- Item A
  - Detail A
### Nested section
- Item B
## Second section
- Item C`)

    expect(roots.map(shape)).toEqual([
      {
        text: 'Root',
        children: [
          {
            text: 'First section',
            children: [
              { text: 'Item A', children: [{ text: 'Detail A' }] },
              { text: 'Nested section', children: [{ text: 'Item B' }] },
            ],
          },
          { text: 'Second section', children: [{ text: 'Item C' }] },
        ],
      },
    ])
  })

  it('removes heading markers without confusing #tags for headings', () => {
    const roots = parseMarkdownMultiRoot('# Root\n- Topic #important')

    expect(roots[0].text).toBe('Root')
    expect(roots[0].children?.[0].text).toBe('Topic #important')
  })

  it('is idempotent on structure across parse → serialize → parse', () => {
    const first = parseMarkdownMultiRoot('- Root\n  - A\n    - A1\n  - B')
    const round = parseMarkdownMultiRoot(toMarkdownMultiRoot(first))
    expect(round.map(shape)).toEqual(first.map(shape))
  })

  it('preserves a deeply nested outline', () => {
    const first = parseMarkdownMultiRoot(
      '- Root\n  - One\n    - One-A\n      - One-A-i\n  - Two',
    )
    const round = parseMarkdownMultiRoot(toMarkdownMultiRoot(first))
    expect(round.map(shape)).toEqual(first.map(shape))
    expect(first[0].text).toBe('Root')
    expect(first[0].children?.map((c) => c.text)).toEqual(['One', 'Two'])
  })

  it('keeps node text content in the serialized output', () => {
    const md = toMarkdownMultiRoot([
      { id: 'r', text: 'Topic', children: [{ id: 'a', text: 'Detail' }] },
    ])
    expect(md).toContain('Topic')
    expect(md).toContain('Detail')
  })

  it('parses inline, same-line block, and multi-line block formulas', () => {
    const tokens = parseInlineMarkdown(
      'inline $M=2^{20}$ and $$M=2^{20}$$',
      latexPlugins,
    )

    expect(tokens.map((token) => token.type)).toEqual([
      'text', 'latex-inline', 'text', 'latex-block',
    ])
    expect(tokens[1]).toEqual({ type: 'latex-inline', content: 'M=2^{20}' })
    expect(tokens[3]).toEqual({ type: 'latex-block', content: 'M=2^{20}' })

    const multiLineTokens = parseInlineMarkdown(
      '$$\n\nline1\nline2\n\n$$',
      latexPlugins,
    )
    expect(multiLineTokens).toEqual([
      { type: 'latex-block', content: 'line1\nline2' },
    ])
    expect(parseInlineMarkdown('$M\n=2^{20}$', latexPlugins)).not.toContainEqual(
      expect.objectContaining({ type: 'latex-inline' }),
    )
  })

  it('keeps a standard block formula attached to its parent node', () => {
    const roots = parseMarkdownMultiRoot(
      '- CPU 执行时间\n\n  $$\n  CPU执行时间=\\frac{指令条数\\times CPI}{主频}\n  $$\n\n  - 子节点',
      latexPlugins,
    )
    const node = roots[0]

    expect(node.text).toBe('CPU 执行时间')
    expect(node.multiLineContent).toEqual([
      '$$\nCPU执行时间=\\frac{指令条数\\times CPI}{主频}\n$$',
    ])
    expect(node.children?.map((child) => child.text)).toEqual(['子节点'])
    expect(parseInlineMarkdown(node.multiLineContent![0], latexPlugins)).toEqual([
      { type: 'latex-block', content: 'CPU执行时间=\\frac{指令条数\\times CPI}{主频}' },
    ])
  })

  it('collects multiple block formulas and round-trips their standard syntax', () => {
    const roots = parseMarkdownMultiRoot(
      '- Formulae\n\n  $$\n  M=2^{20}\n  $$\n\n  $$\n  G=2^{30}\n  $$',
      latexPlugins,
    )
    expect(roots[0].multiLineContent).toEqual([
      '$$\nM=2^{20}\n$$',
      '$$\nG=2^{30}\n$$',
    ])

    const serialized = toMarkdownMultiRoot(roots, latexPlugins)
    expect(serialized).toContain('- Formulae\n  $$\n  M=2^{20}\n  $$\n  $$\n  G=2^{30}\n  $$')
    expect(parseMarkdownMultiRoot(serialized, latexPlugins)[0].multiLineContent)
      .toEqual(roots[0].multiLineContent)

    const preserved = parseMarkdownMultiRoot(
      '- Multi-line\n\n  $$\n  line1\n\n  line2\n  $$',
      latexPlugins,
    )
    expect(preserved[0].multiLineContent).toEqual([
      '$$\nline1\n\nline2\n$$',
    ])
  })

  it('parses formulas nested inside formatted text without parsing code', () => {
    const tokens = parseInlineMarkdown(
      '**补码 $+0$ 和 $-0$ 相同**',
      latexPlugins,
    )
    expect(tokens).toEqual([
      { type: 'bold', content: '补码 ' },
      { type: 'latex-inline', content: '+0' },
      { type: 'bold', content: ' 和 ' },
      { type: 'latex-inline', content: '-0' },
      { type: 'bold', content: ' 相同' },
    ])
  })

  it('does not parse formulas inside inline or fenced code', () => {
    expect(parseInlineMarkdown('`$M=2^{20}$`', latexPlugins)).toEqual([
      { type: 'code', content: '$M=2^{20}$' },
    ])
    expect(parseInlineMarkdown('```markdown\n$test$\n$$\ntest\n$$\n```', latexPlugins))
      .not.toContainEqual(expect.objectContaining({ type: 'latex-block' }))
    expect(parseInlineMarkdown('```markdown\n$test$\n```', latexPlugins))
      .not.toContainEqual(expect.objectContaining({ type: 'latex-inline' }))

    const roots = parseMarkdownMultiRoot(
      '- Code sample\n  ```markdown\n  - $test$\n  $$\n  test\n  $$\n  ```\n- Next',
      latexPlugins,
    )
    expect(roots[0].children?.map((child) => child.text)).toEqual(['Next'])
  })

  it('parses nested and flat-title conventions to the same structure', () => {
    // The serializer emits the root's children at column 0 ("flat title"),
    // while authored input usually nests them under the root bullet. Both must
    // yield identical structure, or export → re-import would mangle depth ≥ 2.
    const nested = parseMarkdownMultiRoot('- Root\n  - A\n    - A1\n  - B')
    const flat = parseMarkdownMultiRoot('Root\n- A\n  - A1\n- B')
    expect(flat.map(shape)).toEqual(nested.map(shape))
    expect(nested[0].children?.[0].children?.[0].text).toBe('A1')
  })
})
