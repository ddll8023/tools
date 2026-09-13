import type { LayoutDirection, LayoutNode, Edge, MindMapData, ThemeMode } from '../types'
import type { ThemeColors } from './theme'
import type { MindMapPlugin } from '../plugins/types'
import { THEME, generateExportStyles, getLevel1TextColor, getTheme } from './theme'
import { buildSvgNodeTextString, parseInlineMarkdown } from './inline-markdown'
import { initFormulaEngine, requireFormula } from './formula'
import { measureNodeContent } from './content-layout'
import { runExportNodeDecoration, runExportOverlay } from '../plugins/runner'
import { layoutMultiRoot } from './layout'
import { parseMindMapMarkdownInput } from './input'
import { normalizeData } from './tree-ops'

interface ExportOptions {
  padding?: number
  scale?: number
  background?: string
  /** When true, avoid foreignObject elements (for PNG canvas export) */
  pngSafe?: boolean
}

export interface ExportMindMapToSVGOptions {
  data?: MindMapData | MindMapData[]
  markdown?: string
  defaultDirection?: LayoutDirection
  theme?: ThemeMode
  plugins?: MindMapPlugin[]
  readonly?: boolean
  foldOverrides?: Record<string, boolean>
  padding?: number
  background?: string
}

function resolveExportTheme(mode: ThemeMode = 'auto'): ThemeColors {
  if (mode === 'dark') return getTheme('dark')
  if (mode === 'light') return getTheme('light')
  const prefersDark =
    typeof window !== 'undefined' &&
    typeof window.matchMedia === 'function' &&
    window.matchMedia('(prefers-color-scheme: dark)').matches
  return getTheme(prefersDark ? 'dark' : 'light')
}

/**
 * Build SVG string for export. Embeds a <style> block with resolved values
 * and applies semantic CSS classes to elements for external customization.
 * Works for both SVG file export and PNG conversion.
 */
export function buildExportSVG(
  nodes: LayoutNode[],
  edges: Edge[],
  options: ExportOptions = {},
  theme: ThemeColors = THEME,
  plugins?: MindMapPlugin[],
): string {
  const { padding = 40, pngSafe = false, background = pngSafe ? '#ffffff' : theme.canvas.bgColor } = options
  if (pngSafe) {
    for (const token of collectFormulas(nodes, plugins)) requireFormula(token.content, token.type === 'latex-block')
  }

  let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
  for (const n of nodes) {
    minX = Math.min(minX, n.x - n.width / 2)
    maxX = Math.max(maxX, n.x + n.width / 2)
    minY = Math.min(minY, n.y - n.height / 2)
    maxY = Math.max(maxY, n.y + n.height / 2)
  }

  const width = maxX - minX + padding * 2
  const height = maxY - minY + padding * 2
  const offsetX = -minX + padding
  const offsetY = -minY + padding

  const parts: string[] = []
  parts.push(`<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}">`)

  // Embedded style block with resolved values
  parts.push(`<defs>`)
  parts.push(`  <style>`)
  parts.push(`    ${generateExportStyles(theme)}`)
  parts.push(`  </style>`)

  // Arrow marker for cross-links
  if (edges.some(e => e.isCrossLink)) {
    parts.push(`<marker id="arrowhead" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto">`)
    parts.push(`<path d="M0,0 L8,3 L0,6" fill="none" stroke="currentColor" stroke-width="1.5"/>`)
    parts.push(`</marker>`)
  }

  parts.push(`</defs>`)

  parts.push(`<rect width="100%" height="100%" fill="${background}"/>`)
  parts.push(`<g transform="translate(${offsetX}, ${offsetY})">`)

  // Edges
  for (const edge of edges) {
    const toNode = nodes.find(n => n.id === edge.toId)
    const branchAttr = toNode?.branchIndex !== undefined ? ` data-branch-index="${toNode.branchIndex}"` : ''
    let attrs = `class="mindmap-edge" d="${edge.path}" stroke="${edge.color}"${branchAttr}`
    if (edge.strokeDasharray) {
      attrs += ` stroke-dasharray="${edge.strokeDasharray}"`
    }
    if (edge.isCrossLink) {
      attrs += ` marker-end="url(#arrowhead)" opacity="0.7"`
    }
    parts.push(`<path ${attrs}/>`)

    // Edge label
    if (edge.label) {
      // Approximate midpoint of the path
      const fromNode = nodes.find(n => n.id === edge.fromId)
      if (fromNode && toNode) {
        const mx = (fromNode.x + toNode.x) / 2
        const my = (fromNode.y + toNode.y) / 2
        parts.push(`<text class="mindmap-edge-label" x="${mx}" y="${my - 6}" text-anchor="middle" font-size="11" fill="${edge.color}" opacity="0.8">${edge.label}</text>`)
      }
    }
  }

  // Nodes
  for (const node of nodes) {
    const nx = node.x
    const ny = node.y
    const branchAttr = node.branchIndex !== undefined ? ` data-branch-index="${node.branchIndex}"` : ''

    if (node.depth === 0) {
      const { fontSize, fontWeight, fontFamily, textColor } = theme.root
      const bgColor = theme.root.bgColor
      const content = measureNodeContent(node, fontSize, fontWeight, fontFamily, plugins)
      parts.push(`<g class="mindmap-node-g mindmap-node-root" transform="translate(${nx}, ${ny})"${branchAttr}>`)
      parts.push(`<rect class="mindmap-node-bg" x="${-node.width / 2}" y="${-node.height / 2}" width="${node.width}" height="${node.height}" rx="${node.height / 2}" ry="${node.height / 2}" fill="${bgColor}"/>`)
      parts.push(buildSvgNodeTextString(content.mainText, fontSize, fontWeight, fontFamily, textColor, node.taskStatus, node.remark, plugins, theme.highlight.textColor, theme.highlight.bgColor, pngSafe))
      // Plugin: export node decorations
      if (plugins && plugins.length > 0) {
        parts.push(runExportNodeDecoration(plugins, node, theme, plugins, pngSafe))
      }
      parts.push(`</g>`)
    } else {
      const isLevel1 = node.depth === 1
      const fontSize = isLevel1 ? theme.level1.fontSize : theme.node.fontSize
      const fontWeight = isLevel1 ? theme.level1.fontWeight : theme.node.fontWeight
      const textColor = isLevel1
        ? getLevel1TextColor(node.color, node.branchIndex)
        : theme.node.textColor

      parts.push(`<g class="mindmap-node-g mindmap-node-child${isLevel1 ? ' mindmap-node-level1' : ''}" transform="translate(${nx}, ${ny})"${branchAttr}>`)
      if (isLevel1) {
        parts.push(`<rect class="mindmap-node-bg" x="${-node.width / 2}" y="${-node.height / 2}" width="${node.width}" height="${node.height}" rx="8" ry="8" fill="${node.color}"/>`)
      }
      const content = measureNodeContent(node, fontSize, fontWeight, theme.node.fontFamily, plugins)
      parts.push(buildSvgNodeTextString(content.mainText, fontSize, fontWeight, theme.node.fontFamily, textColor, node.taskStatus, node.remark, plugins, theme.highlight.textColor, theme.highlight.bgColor, pngSafe))
      if (!isLevel1) {
        const textW = node.width - theme.node.paddingH * 2
        const hasDisplayMathFollowLine = content.multiLines.some((line) => line.isDisplayMath)
        const underlineY = hasDisplayMathFollowLine
          ? Math.max(fontSize / 2 + 4, content.bottom + 4)
          : Math.max(fontSize / 2 + 4, content.main.bottom + 4)
        parts.push(`<line class="mindmap-node-underline" x1="${-textW / 2}" y1="${underlineY}" x2="${textW / 2}" y2="${underlineY}" stroke="${node.color}"/>`)
      }
      // Plugin: export node decorations
      if (plugins && plugins.length > 0) {
        parts.push(runExportNodeDecoration(plugins, node, theme, plugins, pngSafe))
      }
      parts.push(`</g>`)
    }
  }

  // Plugin: export overlay (cross-link arrows, etc.)
  if (plugins && plugins.length > 0) {
    parts.push(runExportOverlay(plugins, nodes, edges, theme))
  }

  parts.push(`</g>`)
  parts.push(`</svg>`)
  return parts.join('\n')
}

// Backward-compatible alias
export const buildExportSVGForPNG = buildExportSVG

export function exportMindMapToSVG({
  data,
  markdown,
  defaultDirection = 'both',
  theme: themeMode = 'auto',
  plugins: pluginsProp,
  readonly = false,
  foldOverrides,
  padding,
  background,
}: ExportMindMapToSVGOptions): string {
  const plugins = pluginsProp && pluginsProp.length > 0 ? pluginsProp : undefined
  const parsed = markdown !== undefined
    ? parseMindMapMarkdownInput(markdown, plugins)
    : null
  const roots = parsed
    ? parsed.roots
    : data
      ? normalizeData(data)
      : [{ id: 'md-0', text: 'Root' }]
  const direction = parsed?.direction ?? defaultDirection
  const activeTheme = resolveExportTheme(parsed?.theme ?? themeMode)
  const { nodes, edges } = layoutMultiRoot(
    roots,
    direction,
    {},
    {},
    plugins,
    readonly,
    foldOverrides ?? {},
  )

  return buildExportSVG(
    nodes,
    edges,
    { padding, background },
    activeTheme,
    plugins,
  )
}

function collectFormulas(nodes: LayoutNode[], plugins?: MindMapPlugin[]) {
  return nodes.flatMap((node) => [node.text, ...(node.multiLineContent ?? [])])
    .flatMap((text) => parseInlineMarkdown(text, plugins))
    .filter((token) => token.type === 'latex-inline' || token.type === 'latex-block')
}

interface PreparedPNGOptions extends ExportOptions {
  data: MindMapData[]
  direction: LayoutDirection
  colorMap: Record<string, string>
  splitIndices: Record<string, number>
  foldOverrides: Record<string, boolean>
  readonly: boolean
  theme: ThemeColors
  plugins?: MindMapPlugin[]
}

/** Snapshot geometry is recomputed AFTER math readiness; a first-click export cannot use stale sizes. */
export async function exportPreparedPNG(options: PreparedPNGOptions): Promise<Blob> {
  const { data, direction, colorMap, splitIndices, foldOverrides, readonly, theme, plugins } = options
  const layout = () => layoutMultiRoot(data, direction, colorMap, splitIndices, plugins, readonly, foldOverrides)
  const formulas = collectFormulas(layout().nodes, plugins)
  if (formulas.length) {
    await initFormulaEngine()
    for (const token of formulas) requireFormula(token.content, token.type === 'latex-block')
  }
  const { nodes, edges } = layout()
  return exportToPNG(buildExportSVG(nodes, edges, { ...options, pngSafe: true }, theme, plugins), options)
}

export async function exportToPNG(
  svgString: string,
  options: ExportOptions = {},
): Promise<Blob> {
  const defaultScale = typeof window !== 'undefined' ? Math.max(window.devicePixelRatio ?? 1, 2) : 2
  const { scale = defaultScale } = options
  const doc = new DOMParser().parseFromString(svgString, 'image/svg+xml')
  if (doc.querySelector('parsererror')) throw new Error('Invalid export SVG')
  const svgEl = doc.documentElement
  const width = parseFloat(svgEl.getAttribute('width') || '800')
  const height = parseFloat(svgEl.getAttribute('height') || '600')
  if (![width, height, scale].every((value) => Number.isFinite(value) && value > 0)) {
    throw new Error('Invalid PNG dimensions or scale')
  }
  const pixelWidth = Math.ceil(width * scale)
  const pixelHeight = Math.ceil(height * scale)
  if (pixelWidth > 32767 || pixelHeight > 32767 || pixelWidth * pixelHeight > 64 * 1024 * 1024) {
    throw new Error('PNG 图片过大，请降低导出倍率。')
  }
  const url = URL.createObjectURL(new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' }))
  try {
    const img = new Image()
    await new Promise<void>((resolve, reject) => {
      const timeout = window.setTimeout(() => reject(new Error('SVG 图片加载超时，请检查公式或图片内容。')), 15000)
      const finish = (error?: Error) => {
        window.clearTimeout(timeout)
        if (error) reject(error)
        else resolve()
      }
      img.onload = () => finish()
      img.onerror = () => finish(new Error('SVG 图片加载失败，请检查公式或图片内容。'))
      img.src = url
    })
    const canvas = document.createElement('canvas')
    canvas.width = pixelWidth
    canvas.height = pixelHeight
    const ctx = canvas.getContext('2d')
    if (!ctx) throw new Error('Canvas is unavailable for PNG export')
    ctx.scale(scale, scale)
    ctx.drawImage(img, 0, 0, width, height)
    return await new Promise<Blob>((resolve, reject) => {
      canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error('Failed to create PNG blob')), 'image/png')
    })
  } finally {
    URL.revokeObjectURL(url)
  }
}
