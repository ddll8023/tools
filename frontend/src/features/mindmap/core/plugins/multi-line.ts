import type { MindMapPlugin } from './types'
import type { MindMapData } from '../types'
import { buildSvgTextLineString, isMultilineBlockFormula } from '../utils/inline-markdown'
import { measureNodeContent } from '../utils/content-layout'
import { getLevel1TextColor } from '../utils/theme'

function hasDisplayMathSyntax(text: string): boolean {
  return /\$\$[\s\S]+?\$\$/.test(text)
}

export const multiLinePlugin: MindMapPlugin = {
  name: 'multi-line',

  collectFollowLines(lines, startIdx, node) {
    let consumed = 0
    const multiLines: string[] = []
    let j = startIdx
    while (j < lines.length) {
      const m = lines[j].match(/^(\s*)\|\s?(.*)$/)
      if (m) {
        multiLines.push(m[2])
        consumed++
        j++
      } else {
        break
      }
    }
    if (multiLines.length > 0) {
      ;(node as MindMapData).multiLineContent = multiLines
    }
    return consumed
  },

  serializeFollowLines(node, indent) {
    if (!node.multiLineContent || node.multiLineContent.length === 0) return []
    // latexPlugin serializes a node's complete follow-line sequence when it
    // contains a standard multi-line display formula. Avoid duplicating it.
    if (node.multiLineContent.some(isMultilineBlockFormula)) return []
    const prefix = indent === 0 ? '' : ''
    void prefix
    return node.multiLineContent.map(line => `| ${line}`)
  },

  adjustNodeSize(node, width, height, fontSize) {
    if (!node.multiLineContent || node.multiLineContent.length === 0) {
      return { width, height }
    }
    const lineHeight = fontSize * 1.4
    const normalLineCount = node.multiLineContent.filter((line) => !hasDisplayMathSyntax(line)).length
    const extraHeight = normalLineCount * lineHeight
    return { width, height: height + extraHeight }
  },

  exportNodeDecoration(node, theme, plugins) {
    if (!node.multiLineContent || node.multiLineContent.length === 0) return ''

    const fontSize = node.depth === 0
      ? theme.root.fontSize
      : node.depth === 1 ? theme.level1.fontSize : theme.node.fontSize
    const fontFamily = node.depth === 0 ? theme.root.fontFamily : theme.node.fontFamily
    const textColor = node.depth === 0
      ? theme.root.textColor
      : node.depth === 1
        ? getLevel1TextColor(node.color, node.branchIndex)
        : theme.node.textColor
    const fontWeight = node.depth === 0 ? theme.root.fontWeight : node.depth === 1 ? theme.level1.fontWeight : theme.node.fontWeight
    const content = measureNodeContent(node, fontSize, fontWeight, fontFamily, plugins)

    const parts: string[] = []
    for (let i = 0; i < node.multiLineContent.length; i++) {
      const line = content.multiLines[i]
      if (line.isMergedIntoMain) continue
      parts.push(buildSvgTextLineString(
        node.multiLineContent[i], line.fontSize, 400, fontFamily, textColor, line.y,
        plugins, theme.highlight.textColor, theme.highlight.bgColor,
        line.isDisplayMath ? undefined : 0.8,
      ))
    }
    return parts.join('')
  },
}
