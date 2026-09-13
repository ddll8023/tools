import type { MindMapPlugin } from './types'
import type { InlineToken } from '../utils/inline-markdown'
import {
  buildSvgTextLineString,
  escapeXml,
  isMultilineBlockFormula,
  normalizeFormulaContent,
} from '../utils/inline-markdown'
import { measureNodeContent } from '../utils/content-layout'
import { getLevel1TextColor } from '../utils/theme'

const MONO_FONT = "'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace"

function stripFormulaIndent(line: string, indent: string): string {
  return indent.length > 0 && line.startsWith(indent) ? line.slice(indent.length) : line
}

function isStandaloneFormulaDelimiter(line: string): boolean {
  return /^[ \t]*\$\$[ \t]*$/.test(line)
}

/** Parse LaTeX delimiters and collect standard display blocks; shared rendering emits pure SVG paths. */
export const latexPlugin: MindMapPlugin = {
  name: 'latex',

  inlineTokenPattern() {
    return { pattern: '\\$\\$([\\s\\S]+?)\\$\\$|\\$([^$\\r\\n]+?)\\$', priority: 3 }
  },

  createInlineToken(match, groupOffset) {
    const block = match[groupOffset + 1]
    const inline = match[groupOffset + 2]
    if (block !== undefined) return { type: 'latex-block', content: normalizeFormulaContent(block) } as InlineToken
    if (inline !== undefined) return { type: 'latex-inline', content: inline } as InlineToken
    return null
  },

  /** Collect standard Markdown display-math blocks before line parsing can see them as nodes. */
  collectFollowLines(lines, startIdx, node) {
    let cursor = startIdx
    const formulas: string[] = []

    while (cursor < lines.length) {
      let openingIdx = cursor
      while (openingIdx < lines.length && lines[openingIdx].trim() === '') openingIdx++
      if (openingIdx >= lines.length) break

      const opening = lines[openingIdx].match(/^([ \t]*)\$\$[ \t]*$/)
      if (!opening) break

      let closingIdx = openingIdx + 1
      while (closingIdx < lines.length && !isStandaloneFormulaDelimiter(lines[closingIdx])) {
        closingIdx++
      }
      if (closingIdx >= lines.length) break

      const content = normalizeFormulaContent(
        lines
          .slice(openingIdx + 1, closingIdx)
          .map((line) => stripFormulaIndent(line, opening[1]))
          .join('\n'),
      )
      formulas.push(`$$\n${content}\n$$`)
      cursor = closingIdx + 1
    }

    if (formulas.length === 0) return 0
    node.multiLineContent = [...(node.multiLineContent ?? []), ...formulas]
    return cursor - startIdx
  },

  /** Preserve standard block syntax when a parsed tree is serialized back to Markdown. */
  serializeFollowLines(node) {
    const lines = node.multiLineContent
    if (!lines?.some(isMultilineBlockFormula)) return []
    return lines.flatMap((line) =>
      isMultilineBlockFormula(line) ? line.split('\n') : [`| ${line}`],
    )
  },

  /** Export formulas without relying on multiLinePlugin when latexPlugin is used alone. */
  exportNodeDecoration(node, theme, plugins) {
    if (plugins?.some((plugin) => plugin.name === 'multi-line')) return ''

    const fontSize = node.depth === 0
      ? theme.root.fontSize
      : node.depth === 1 ? theme.level1.fontSize : theme.node.fontSize
    const fontFamily = node.depth === 0 ? theme.root.fontFamily : theme.node.fontFamily
    const textColor = node.depth === 0
      ? theme.root.textColor
      : node.depth === 1
        ? getLevel1TextColor(node.color, node.branchIndex)
        : theme.node.textColor
    const content = measureNodeContent(node, fontSize, node.depth === 0 ? theme.root.fontWeight : node.depth === 1 ? theme.level1.fontWeight : theme.node.fontWeight, fontFamily, plugins)
    const formulaIndexes = (node.multiLineContent ?? [])
      .map((line, index) => isMultilineBlockFormula(line) ? index : -1)
      .filter((index) => index >= 0 && !content.multiLines[index].isMergedIntoMain)
    if (formulaIndexes.length === 0) return ''

    return formulaIndexes.map((index) => {
      const line = content.multiLines[index]
      return buildSvgTextLineString(
        node.multiLineContent![index],
        line.fontSize,
        400,
        fontFamily,
        textColor,
        line.y,
        plugins,
        theme.highlight.textColor,
        theme.highlight.bgColor,
        line.isDisplayMath ? undefined : 0.8,
      )
    }).join('')
  },

  exportInlineToken(layout) {
    if (layout.token.type !== 'latex-inline' && layout.token.type !== 'latex-block') return ''
    if (layout.formula) return '<tspan></tspan>'
    return `<tspan font-family="${MONO_FONT}" font-style="italic" font-size="0.9em">${escapeXml(layout.token.content)}</tspan>`
  },
}
