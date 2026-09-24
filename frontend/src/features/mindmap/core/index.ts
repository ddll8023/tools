/** 思维导图核心能力入口：统一导出数据、布局、操作和导出工具。 */
export type {
  CrossLink,
  Edge,
  LayoutDirection,
  LayoutNode,
  MindMapData,
  MindMapEvent,
  MindMapPNGExportOptions,
  TaskStatus,
  ThemeMode,
  ToolbarConfig,
} from './types'

export {
  parseMarkdownList,
  parseMarkdownMultiRoot,
  parseMarkdownWithFrontMatter,
  toMarkdownList,
  toMarkdownMultiRoot,
} from './utils/markdown'
export { parseInitialMindMapInput, parseMindMapMarkdownInput } from './utils/input'
export {
  parseImportText,
  validateMindMapData,
  isMindMapData,
} from './utils/import'
export {
  exportMindMapToXMind,
  parseXMindFile,
  XMindFormatError,
} from './utils/xmind'
export type { XMindInput } from './utils/xmind'
export {
  layoutMindMap,
  layoutMultiRoot,
  computeEdgePath,
} from './utils/layout'
export {
  buildExportSVG,
  buildExportSVGForPNG,
  exportMindMapToSVG,
  exportPreparedPNG,
  exportToPNG,
} from './utils/export'
export {
  parseInlineMarkdown,
  computeTokenLayouts,
  buildSvgNodeTextString,
  buildSvgTextLineString,
  stripInlineMarkdown,
} from './utils/inline-markdown'
export { measureContentLine, measureNodeContent } from './utils/content-layout'
export { analyzeMindMapTagFilter } from './utils/tag-filter'
export {
  cloneMindMapData,
  cloneHistorySnapshot,
  areHistorySnapshotsEqual,
  pushHistorySnapshot,
} from './utils/history'
export {
  generateId,
  normalizeData,
  findSubtreeMulti,
  getDescendantIds,
  addChildMulti,
  addSiblingMulti,
  removeNodeMulti,
  updateNodeFieldsMulti,
  moveNodeMulti,
  swapSiblingsMulti,
  moveSiblingMulti,
  regenerateIds,
  addChildToSide,
  moveChildToSide,
} from './utils/tree-ops'
export {
  getTheme,
  getLevel1TextColor,
  generateCSSVariables,
  generateExportStyles,
  BRANCH_COLORS,
  THEME,
} from './utils/theme'
export { highlightMindmapHTML } from './utils/highlight'
export {
  initFormulaEngine,
  requireFormula,
  measureFormula,
  buildFormulaSvg,
  getFormulaRevision,
  subscribeFormulaEngine,
} from './utils/formula'

export type { MindMapMessages } from './utils/i18n'
export { detectLocale, resolveMessages } from './utils/i18n'

export type {
  LayoutContext,
  MindMapPlugin,
  ParseContext,
  ParsedLineResult,
} from './plugins/types'
export {
  allPlugins,
  crossLinkPlugin,
  dottedLinePlugin,
  foldingPlugin,
  frontMatterPlugin,
  latexPlugin,
  multiLinePlugin,
  tagsPlugin,
} from './plugins'
