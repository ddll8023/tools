<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import MindMapCanvas from './MindMapCanvas.vue'
import MindMapContextMenu from './MindMapContextMenu.vue'
import {
  allPlugins,
  generateCSSVariables,
  getTheme,
  addChildMulti,
  addChildToSide,
  addSiblingMulti,
  cloneHistorySnapshot,
  cloneMindMapData,
  buildExportSVG,
  exportMindMapToXMind,
  exportPreparedPNG,
  generateId,
  findSubtreeMulti,
  getDescendantIds,
  initFormulaEngine,
  layoutMultiRoot,
  moveChildToSide,
  moveNodeMulti,
  normalizeData,
  parseInitialMindMapInput,
  pushHistorySnapshot,
  regenerateIds,
  removeNodeMulti,
  subscribeFormulaEngine,
  swapSiblingsMulti,
  toMarkdownMultiRoot,
  updateNodeFieldsMulti,
} from '../core'
import type {
  Edge,
  LayoutDirection,
  LayoutNode,
  MindMapData,
  MindMapEvent,
  MindMapPlugin,
  ThemeMode,
  ToolbarConfig,
} from '../core'
import type { MindMapHistorySnapshot } from '../core/utils/history'
import type { ThemeColors } from '../core/utils/theme'

interface Props {
  data?: MindMapData | MindMapData[]
  markdown?: string
  defaultDirection?: LayoutDirection
  theme?: ThemeMode
  toolbar?: boolean | ToolbarConfig
  plugins?: MindMapPlugin[]
  activeTags?: string[]
  readonly?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  defaultDirection: 'both',
  theme: 'auto',
  toolbar: true,
  plugins: () => [],
  activeTags: () => [],
  readonly: true,
})

const emit = defineEmits<{
  event: [event: MindMapEvent]
  directionChange: [direction: LayoutDirection]
  markdownChange: [markdown: string]
  dataChange: [data: MindMapData[]]
  selectedNodeChange: [nodeId: string | null]
  activeTagsChange: [tags: string[]]
}>()

const svgRef = ref<SVGSVGElement | null>(null)
const mapData = shallowRef<MindMapData[]>([])
const direction = ref<LayoutDirection>(props.defaultDirection)
const frontMatterTheme = ref<ThemeMode | undefined>()
const colorMap = shallowRef<Record<string, string>>({})
const foldOverrides = shallowRef<Record<string, boolean>>({})
const splitIndices = shallowRef<Record<string, number>>({})
const activeTags = ref<string[]>([...props.activeTags])
const selectedNodeId = ref<string | null>(null)
const editingNodeId = ref<string | null>(null)
const editText = ref('')
const historyPast = ref<MindMapHistorySnapshot[]>([])
const historyFuture = ref<MindMapHistorySnapshot[]>([])
const dropTargetId = ref<string | null>(null)
const contextMenu = ref<{ x: number; y: number; nodeId: string | null } | null>(null)
const clipboardNode = shallowRef<MindMapData | null>(null)
const exportError = ref<string | null>(null)
const nodeDrag = ref<{
  pointerId: number
  nodeId: string
  startX: number
  startY: number
  moved: boolean
  lastSwapAt: number
  lastSwapTarget: string | null
} | null>(null)
const pan = ref({ x: 0, y: 0 })
const zoom = ref(1)
const initialReady = ref(false)
const isPanning = ref(false)
const formulaRevision = ref(0)
const systemDark = ref(false)
let mediaQuery: MediaQueryList | undefined

const activePlugins = computed(() => (props.plugins.length > 0 ? props.plugins : allPlugins))
const toolbarConfig = computed(() => {
  if (props.toolbar === false) return { zoom: false, history: false, tags: false }
  if (props.toolbar === true) return { zoom: true, history: !props.readonly, tags: false }
  return {
    zoom: props.toolbar.zoom ?? true,
    history: props.toolbar.history ?? !props.readonly,
    tags: props.toolbar.tags ?? false,
  }
})
const formulasEnabled = computed(() => containsFormula(mapData.value))
const resolvedThemeMode = computed<'light' | 'dark'>(() => {
  const mode = frontMatterTheme.value ?? props.theme
  if (mode === 'auto') return systemDark.value ? 'dark' : 'light'
  return mode
})
const theme = computed<ThemeColors>(() => getTheme(resolvedThemeMode.value))
const themeVariables = computed(() => generateCSSVariables(theme.value))
const canUndo = computed(() => historyPast.value.length > 0)
const canRedo = computed(() => historyFuture.value.length > 0)

const layoutState = computed<{ nodes: LayoutNode[]; edges: Edge[] }>(() => {
  // Formula readiness changes measured dimensions and therefore the layout.
  void formulaRevision.value
  return layoutMultiRoot(
    mapData.value,
    direction.value,
    colorMap.value,
    splitIndices.value,
    activePlugins.value,
    true,
    foldOverrides.value,
  )
})
const nodes = computed(() => layoutState.value.nodes)
const edges = computed(() => layoutState.value.edges)
const nodeMap = computed<Record<string, LayoutNode>>(() => {
  const result: Record<string, LayoutNode> = {}
  for (const node of nodes.value) result[node.id] = node
  return result
})
const dimmedNodes = computed(() => {
  const result = new Set<string>()
  if (activeTags.value.length === 0) return result
  const normalized = activeTags.value.map((tag) => tag.trim().toLocaleLowerCase()).filter(Boolean)
  if (normalized.length === 0) return result

  const visible = new Set<string>()
  walkData(mapData.value, (node, ancestors) => {
    const tags = (node.tags ?? []).map((tag) => tag.trim().toLocaleLowerCase())
    if (!normalized.some((tag) => tags.includes(tag))) return
    visible.add(node.id)
    ancestors.forEach((id) => visible.add(id))
    addDescendants(node, visible)
  })
  nodes.value.forEach((node) => {
    if (!visible.has(node.id)) result.add(node.id)
  })
  return result
})

let stopFormulaSubscription: (() => void) | undefined
let resizeObserver: ResizeObserver | undefined
let panStart: { pointerId: number; x: number; y: number; panX: number; panY: number } | null = null

function containsFormula(roots: MindMapData[]): boolean {
  let found = false
  walkData(roots, (node) => {
    const texts = [node.text, ...(node.multiLineContent ?? [])]
    if (texts.some((text) => /\$\$[\s\S]+?\$\$|\$[^$\r\n]+?\$/.test(text))) found = true
  })
  return found
}

function resetHistory() {
  historyPast.value = []
  historyFuture.value = []
  emit('event', { type: 'historyChange', canUndo: false, canRedo: false })
}

function makeHistorySnapshot(): MindMapHistorySnapshot {
  return {
    mapData: mapData.value,
    direction: direction.value,
    splitIndices: splitIndices.value,
    foldOverrides: foldOverrides.value,
    selectedNodeId: selectedNodeId.value,
  }
}

function recordHistory() {
  historyPast.value = pushHistorySnapshot(historyPast.value, makeHistorySnapshot())
  historyFuture.value = []
  emit('event', {
    type: 'historyChange',
    canUndo: historyPast.value.length > 0,
    canRedo: false,
  })
}

function publishMarkdown() {
  emit('markdownChange', toMarkdownMultiRoot(mapData.value, activePlugins.value))
}

function publishDataChange() {
  emit('dataChange', cloneMindMapData(mapData.value))
}

function updateMapData(nextData: MindMapData[], event?: MindMapEvent) {
  if (JSON.stringify(nextData) === JSON.stringify(mapData.value)) return
  recordHistory()
  mapData.value = nextData
  publishDataChange()
  if (event) emit('event', event)
  publishMarkdown()
}

function applyHistorySnapshot(snapshot: MindMapHistorySnapshot) {
  mapData.value = cloneMindMapData(snapshot.mapData)
  publishDataChange()
  direction.value = snapshot.direction
  splitIndices.value = { ...snapshot.splitIndices }
  foldOverrides.value = { ...snapshot.foldOverrides }
  selectedNodeId.value = snapshot.selectedNodeId
  editingNodeId.value = null
  editText.value = ''
  publishMarkdown()
}

function handleUndo() {
  const previous = historyPast.value.pop()
  if (!previous) return
  historyFuture.value.push(cloneHistorySnapshot(makeHistorySnapshot()))
  applyHistorySnapshot(previous)
  emit('event', {
    type: 'undo',
    canUndo: historyPast.value.length > 0,
    canRedo: historyFuture.value.length > 0,
  })
}

function handleRedo() {
  const next = historyFuture.value.pop()
  if (!next) return
  historyPast.value.push(cloneHistorySnapshot(makeHistorySnapshot()))
  applyHistorySnapshot(next)
  emit('event', {
    type: 'redo',
    canUndo: historyPast.value.length > 0,
    canRedo: historyFuture.value.length > 0,
  })
}

function applyInput() {
  if (props.data !== undefined) {
    mapData.value = normalizeData(props.data)
    splitIndices.value = {}
    frontMatterTheme.value = undefined
    selectedNodeId.value = null
    editingNodeId.value = null
    resetHistory()
    return
  }

  if (props.markdown !== undefined) {
    const currentMarkdown = mapData.value.length > 0
      ? toMarkdownMultiRoot(mapData.value, activePlugins.value)
      : ''
    if (currentMarkdown === props.markdown && mapData.value.length > 0) return

    const parsed = parseInitialMindMapInput(undefined, props.markdown, activePlugins.value)
    mapData.value = parsed?.roots ?? [{ id: 'md-0', text: 'Root' }]
    splitIndices.value = {}
    direction.value = parsed?.direction ?? props.defaultDirection
    frontMatterTheme.value = parsed?.theme
    selectedNodeId.value = null
    editingNodeId.value = null
    editText.value = ''
    resetHistory()
    return
  }

  mapData.value = [{ id: 'md-0', text: 'Root' }]
  splitIndices.value = {}
  direction.value = props.defaultDirection
  frontMatterTheme.value = undefined
  selectedNodeId.value = null
  editingNodeId.value = null
  resetHistory()
}

function walkData(
  roots: MindMapData[],
  visit: (node: MindMapData, ancestors: string[]) => void,
  ancestors: string[] = [],
) {
  for (const node of roots) {
    visit(node, ancestors)
    if (node.children) walkData(node.children, visit, [...ancestors, node.id])
  }
}

function addDescendants(node: MindMapData, visible: Set<string>) {
  for (const child of node.children ?? []) {
    visible.add(child.id)
    addDescendants(child, visible)
  }
}

function closeContextMenu() {
  contextMenu.value = null
}

function openContextMenu(event: MouseEvent, nodeId: string | null) {
  event.preventDefault()
  event.stopPropagation()
  const svg = svgRef.value
  if (!svg) return
  const rect = svg.getBoundingClientRect()
  const menuWidth = 190
  const menuHeight = nodeId ? 260 : 180
  contextMenu.value = {
    x: Math.min(Math.max(8, event.clientX - rect.left), Math.max(8, rect.width - menuWidth)),
    y: Math.min(Math.max(8, event.clientY - rect.top), Math.max(8, rect.height - menuHeight)),
    nodeId,
  }
}

function startNodeEdit(nodeId: string, fallbackText?: string) {
  if (props.readonly) return
  const node = nodeMap.value[nodeId]
  if (!node) return
  selectedNodeId.value = nodeId
  editingNodeId.value = nodeId
  editText.value = fallbackText ?? node.text
  emit('event', { type: 'nodeFocus', nodeId })
}

function handleNodeClick(event: MouseEvent, nodeId: string) {
  closeContextMenu()
  if (props.readonly) return
  event.stopPropagation()
  selectedNodeId.value = nodeId
  emit('event', { type: 'nodeSelect', nodeId })
}

function handleNodeDoubleClick(event: MouseEvent, nodeId: string, text: string) {
  if (props.readonly) return
  event.stopPropagation()
  closeContextMenu()
  startNodeEdit(nodeId, text)
}

function handleNodeContextMenu(event: MouseEvent, nodeId: string) {
  if (!props.readonly) {
    selectedNodeId.value = nodeId
    emit('event', { type: 'nodeSelect', nodeId })
  }
  openContextMenu(event, nodeId)
}

function handleCanvasContextMenu(event: MouseEvent) {
  const target = event.target as Element | null
  if (target?.closest('.mindmap-node-g')) return
  openContextMenu(event, null)
}

function handleEditChange(text: string) {
  editText.value = text
}

function handleEditCommit() {
  const nodeId = editingNodeId.value
  if (!nodeId) return
  const currentNode = nodeMap.value[nodeId]
  if (!currentNode) {
    editingNodeId.value = null
    return
  }

  const nextText = editText.value.trim() || currentNode.text
  const oldText = currentNode.text
  editingNodeId.value = null
  editText.value = ''
  if (nextText === oldText) return

  updateMapData(
    updateNodeFieldsMulti(mapData.value, nodeId, { text: nextText }),
    { type: 'nodeTextChange', nodeId, oldText, newText: nextText },
  )
}

function handleEditCancel() {
  editingNodeId.value = null
  editText.value = ''
}

function handleAddChild(event: MouseEvent, parentId: string, side?: 'left' | 'right') {
  if (props.readonly) return
  event.stopPropagation()
  const node: MindMapData = { id: generateId(), text: '新节点' }
  const parentRoot = mapData.value.find((root) => root.id === parentId)
  const sideResult = parentRoot && side
    ? addChildToSide(parentRoot, node, side, Math.ceil((parentRoot.children?.length ?? 0) / 2))
    : null
  const nextData = sideResult
    ? mapData.value.map((root) => root.id === parentId ? sideResult.data : root)
    : addChildMulti(mapData.value, parentId, node)
  updateMapData(nextData, {
    type: 'nodeAdd',
    node,
    parentId,
  })
  if (sideResult && parentRoot) {
    splitIndices.value = {
      ...splitIndices.value,
      [parentRoot.id]: sideResult.newSplitIndex,
    }
  }
  selectedNodeId.value = node.id
  editingNodeId.value = node.id
  editText.value = node.text
}

function handleDeleteNode(nodeId: string) {
  if (props.readonly) return
  const isOnlyRoot = mapData.value.length === 1 && mapData.value[0]?.id === nodeId
  if (isOnlyRoot) return
  const nextData = removeNodeMulti(mapData.value, nodeId)
  updateMapData(nextData, { type: 'nodeDelete', nodeId })
  splitIndices.value = {}
  selectedNodeId.value = null
  editingNodeId.value = null
  editText.value = ''
}

function handleContextAddChild() {
  const nodeId = contextMenu.value?.nodeId
  if (!nodeId || props.readonly) return
  handleAddChild(new MouseEvent('click'), nodeId)
}

function handleContextEdit() {
  const nodeId = contextMenu.value?.nodeId
  if (nodeId) startNodeEdit(nodeId)
}

function handleContextDelete() {
  const nodeId = contextMenu.value?.nodeId
  if (nodeId) handleDeleteNode(nodeId)
}

function handleContextCopy() {
  const nodeId = contextMenu.value?.nodeId
  if (!nodeId) return
  clipboardNode.value = findSubtreeMulti(mapData.value, nodeId)
}

function handleContextCut() {
  const nodeId = contextMenu.value?.nodeId
  if (!nodeId || props.readonly) return
  clipboardNode.value = findSubtreeMulti(mapData.value, nodeId)
  handleDeleteNode(nodeId)
}

function handleContextPaste() {
  const parentId = contextMenu.value?.nodeId
  if (!parentId || props.readonly || !clipboardNode.value) return
  const node = regenerateIds(clipboardNode.value)
  updateMapData(addChildMulti(mapData.value, parentId, node), {
    type: 'nodeAdd',
    node,
    parentId,
  })
  selectedNodeId.value = node.id
  editingNodeId.value = null
  editText.value = ''
}

function handleContextNewRoot() {
  if (props.readonly) return
  const node: MindMapData = { id: generateId(), text: '新根节点' }
  updateMapData([...mapData.value, node], { type: 'nodeAdd', node, parentId: null })
  selectedNodeId.value = node.id
  editingNodeId.value = node.id
  editText.value = node.text
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  URL.revokeObjectURL(url)
}

function reportExportError(error: unknown) {
  exportError.value = error instanceof Error ? error.message : '导出失败，请稍后重试。'
  window.setTimeout(() => {
    exportError.value = null
  }, 5000)
}

async function exportCurrentSVG(): Promise<string> {
  if (formulasEnabled.value) await initFormulaEngine()
  return buildExportSVG(
    nodes.value,
    edges.value,
    { padding: 48, background: theme.value.canvas.bgColor },
    theme.value,
    activePlugins.value,
  )
}

async function exportCurrentPNG(): Promise<Blob> {
  return exportPreparedPNG({
    data: cloneMindMapData(mapData.value),
    direction: direction.value,
    colorMap: colorMap.value,
    splitIndices: splitIndices.value,
    foldOverrides: foldOverrides.value,
    readonly: props.readonly,
    theme: theme.value,
    plugins: activePlugins.value,
    padding: 48,
  })
}

async function handleExportSVG() {
  try {
    const svg = await exportCurrentSVG()
    downloadBlob(new Blob([svg], { type: 'image/svg+xml;charset=utf-8' }), 'mindmap.svg')
  } catch (error) {
    reportExportError(error)
  }
}

async function handleExportPNG() {
  try {
    downloadBlob(await exportCurrentPNG(), 'mindmap.png')
  } catch (error) {
    reportExportError(error)
  }
}

function handleExportMarkdown() {
  try {
    const markdown = toMarkdownMultiRoot(mapData.value, activePlugins.value)
    downloadBlob(new Blob([markdown], { type: 'text/markdown;charset=utf-8' }), 'mindmap.md')
  } catch (error) {
    reportExportError(error)
  }
}

function handleExportXMind() {
  try {
    downloadBlob(exportMindMapToXMind(mapData.value), 'mindmap.xmind')
  } catch (error) {
    reportExportError(error)
  }
}

function handleCreateSibling(nodeId: string) {
  if (props.readonly) return
  const node: MindMapData = { id: generateId(), text: '新节点' }
  updateMapData(addSiblingMulti(mapData.value, nodeId, node), {
    type: 'nodeAdd',
    node,
    parentId: nodeMap.value[nodeId]?.parentId ?? null,
  })
  selectedNodeId.value = node.id
  editingNodeId.value = node.id
  editText.value = node.text
}

function handleKeydown(event: KeyboardEvent) {
  if (contextMenu.value) {
    if (event.key === 'Escape') closeContextMenu()
    return
  }

  const isMeta = event.metaKey || event.ctrlKey
  if (isMeta && event.key.toLowerCase() === 'z' && !event.shiftKey && !props.readonly) {
    event.preventDefault()
    handleUndo()
    return
  }
  if (isMeta && ((event.key.toLowerCase() === 'z' && event.shiftKey) || event.key.toLowerCase() === 'y') && !props.readonly) {
    event.preventDefault()
    handleRedo()
    return
  }
  if (props.readonly) {
    if (!event.shiftKey || isMeta) return
    if (event.code === 'Equal') {
      event.preventDefault()
      zoomIn()
    } else if (event.code === 'Minus') {
      event.preventDefault()
      zoomOut()
    } else if (event.code === 'Digit0') {
      event.preventDefault()
      fitView()
    } else if (event.code === 'KeyL') {
      event.preventDefault()
      setDirection('left')
    } else if (event.code === 'KeyR') {
      event.preventDefault()
      setDirection('right')
    } else if (event.code === 'KeyM') {
      event.preventDefault()
      setDirection('both')
    }
    return
  }

  if (editingNodeId.value) return
  const selectedId = selectedNodeId.value
  if (!selectedId) return

  if (event.key === 'Enter' && event.shiftKey) {
    event.preventDefault()
    handleCreateSibling(selectedId)
  } else if (event.key === 'Enter') {
    event.preventDefault()
    const node = nodeMap.value[selectedId]
    if (node) handleNodeDoubleClick(event, selectedId, node.text)
  } else if (event.key === 'Tab') {
    event.preventDefault()
    handleAddChild(event, selectedId)
  } else if (event.key === 'Delete' || event.key === 'Backspace') {
    event.preventDefault()
    handleDeleteNode(selectedId)
  }
}

function fitView() {
  const svg = svgRef.value
  if (!svg || nodes.value.length === 0) return

  const width = svg.clientWidth
  const height = svg.clientHeight
  if (width <= 0 || height <= 0) return

  const minX = Math.min(...nodes.value.map((node) => node.x - node.width / 2))
  const maxX = Math.max(...nodes.value.map((node) => node.x + node.width / 2))
  const minY = Math.min(...nodes.value.map((node) => node.y - node.height / 2))
  const maxY = Math.max(...nodes.value.map((node) => node.y + node.height / 2))
  const contentWidth = Math.max(1, maxX - minX)
  const contentHeight = Math.max(1, maxY - minY)
  const padding = 48
  const nextZoom = Math.min(2, Math.max(0.15, Math.min(
    (width - padding * 2) / contentWidth,
    (height - padding * 2) / contentHeight,
  )))

  zoom.value = nextZoom
  pan.value = {
    x: width / 2 - (minX + contentWidth / 2) * nextZoom,
    y: height / 2 - (minY + contentHeight / 2) * nextZoom,
  }
}

function updateZoom(nextZoom: number, centerX?: number, centerY?: number) {
  const svg = svgRef.value
  const boundedZoom = Math.min(2, Math.max(0.15, nextZoom))
  if (!svg) {
    zoom.value = boundedZoom
    return
  }

  const x = centerX ?? svg.clientWidth / 2
  const y = centerY ?? svg.clientHeight / 2
  const ratio = boundedZoom / zoom.value
  pan.value = {
    x: x - (x - pan.value.x) * ratio,
    y: y - (y - pan.value.y) * ratio,
  }
  zoom.value = boundedZoom
  emit('event', { type: 'zoomChange', zoom: boundedZoom })
}

function zoomIn() {
  updateZoom(zoom.value * 1.1)
}

function zoomOut() {
  updateZoom(zoom.value / 1.1)
}

function handleWheel(event: WheelEvent) {
  const svg = svgRef.value
  if (!svg) return
  const rect = svg.getBoundingClientRect()
  const factor = event.deltaY < 0 ? 1.1 : 1 / 1.1
  updateZoom(zoom.value * factor, event.clientX - rect.left, event.clientY - rect.top)
}

function clientToMapPosition(clientX: number, clientY: number) {
  const svg = svgRef.value
  if (!svg) return null
  const rect = svg.getBoundingClientRect()
  return {
    x: (clientX - rect.left - pan.value.x) / zoom.value,
    y: (clientY - rect.top - pan.value.y) / zoom.value,
  }
}

function findDropTarget(clientX: number, clientY: number, sourceId: string): string | null {
  const position = clientToMapPosition(clientX, clientY)
  const source = nodeMap.value[sourceId]
  if (!position || !source) return null

  const blocked = new Set([sourceId, ...getDescendantIds(sourceId, nodes.value)])
  return nodes.value.find((node) => {
    if (blocked.has(node.id) || node.id === source.parentId) return false
    const sameParent = node.parentId === source.parentId
    const verticalRadius = sameParent ? node.height * 0.22 : node.height / 2
    return (
      Math.abs(position.x - node.x) <= node.width / 2 &&
      Math.abs(position.y - node.y) <= verticalRadius
    )
  })?.id ?? null
}

function handleNodePointerDown(event: PointerEvent, nodeId: string) {
  if (props.readonly || event.button !== 0 || editingNodeId.value) return
  event.stopPropagation()
  selectedNodeId.value = nodeId
  nodeDrag.value = {
    pointerId: event.pointerId,
    nodeId,
    startX: event.clientX,
    startY: event.clientY,
    moved: false,
    lastSwapAt: 0,
    lastSwapTarget: null,
  }
  dropTargetId.value = null
  svgRef.value?.setPointerCapture(event.pointerId)
}

function handlePointerDown(event: PointerEvent) {
  if (event.button !== 0) return
  const target = event.target as Element | null
  if (target?.closest('a, .mindmap-fold-btn, .mindmap-node-g')) return
  const svg = svgRef.value
  if (!svg) return

  panStart = {
    pointerId: event.pointerId,
    x: event.clientX,
    y: event.clientY,
    panX: pan.value.x,
    panY: pan.value.y,
  }
  isPanning.value = true
  svg.setPointerCapture(event.pointerId)
}

function handleDragReorder(drag: NonNullable<typeof nodeDrag.value>, clientX: number, clientY: number) {
  const position = clientToMapPosition(clientX, clientY)
  const draggedNode = nodeMap.value[drag.nodeId]
  if (!position || !draggedNode) return

  if (draggedNode.parentId && draggedNode.depth === 1 && direction.value === 'both') {
    const currentSide = draggedNode.side
    const crossedToLeft = currentSide === 'right' && position.x < 0
    const crossedToRight = currentSide === 'left' && position.x > 0
    if (crossedToLeft || crossedToRight) {
      const targetSide = crossedToLeft ? 'left' : 'right'
      const root = mapData.value.find((item) => item.id === draggedNode.parentId)
      if (root) {
        const splitIndex = splitIndices.value[root.id] ?? Math.ceil((root.children?.length ?? 0) / 2)
        const result = moveChildToSide(root, drag.nodeId, targetSide, splitIndex)
        if (result) {
          updateMapData(
            mapData.value.map((item) => item.id === root.id ? result.data : item),
            { type: 'nodeMove', nodeId: drag.nodeId, targetId: root.id },
          )
          splitIndices.value = { ...splitIndices.value, [root.id]: result.newSplitIndex }
          nodeDrag.value = { ...drag, lastSwapAt: Date.now(), lastSwapTarget: null }
          dropTargetId.value = null
          return
        }
      }
    }
  }

  const siblings = nodes.value.filter((node) =>
    node.id !== drag.nodeId &&
    node.parentId === draggedNode.parentId &&
    node.side === draggedNode.side,
  )
  const sibling = siblings.find((node) =>
    Math.abs(position.y - node.y) < Math.max(draggedNode.height, node.height) * 0.6,
  )
  if (!sibling) {
    if (drag.lastSwapTarget !== null) {
      nodeDrag.value = { ...drag, lastSwapTarget: null }
    }
    return
  }

  const now = Date.now()
  if (sibling.id === drag.lastSwapTarget || now - drag.lastSwapAt < 350) return
  updateMapData(
    swapSiblingsMulti(mapData.value, drag.nodeId, sibling.id),
    { type: 'nodeMove', nodeId: drag.nodeId, targetId: sibling.id },
  )
  nodeDrag.value = { ...drag, lastSwapAt: now, lastSwapTarget: sibling.id }
}

function handlePointerMove(event: PointerEvent) {
  if (nodeDrag.value?.pointerId === event.pointerId) {
    const drag = nodeDrag.value
    if (!drag.moved && Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY) < 5) return
    if (!drag.moved) nodeDrag.value = { ...drag, moved: true }
    const activeDrag = nodeDrag.value ?? { ...drag, moved: true }
    dropTargetId.value = findDropTarget(event.clientX, event.clientY, activeDrag.nodeId)
    if (!dropTargetId.value) handleDragReorder(activeDrag, event.clientX, event.clientY)
    return
  }

  if (!panStart || panStart.pointerId !== event.pointerId) return
  pan.value = {
    x: panStart.panX + event.clientX - panStart.x,
    y: panStart.panY + event.clientY - panStart.y,
  }
}

function handlePointerUp(event: PointerEvent) {
  if (nodeDrag.value?.pointerId === event.pointerId) {
    const drag = nodeDrag.value
    const targetId = dropTargetId.value
    svgRef.value?.releasePointerCapture(event.pointerId)
    nodeDrag.value = null
    dropTargetId.value = null

    if (drag.moved && targetId) {
      const nextData = moveNodeMulti(mapData.value, drag.nodeId, targetId)
      if (nextData) {
        updateMapData(nextData, { type: 'nodeMove', nodeId: drag.nodeId, targetId })
        splitIndices.value = {}
      }
    }
    return
  }

  if (!panStart || panStart.pointerId !== event.pointerId) return
  svgRef.value?.releasePointerCapture(event.pointerId)
  panStart = null
  isPanning.value = false
}

function setDirection(nextDirection: LayoutDirection) {
  direction.value = nextDirection
  emit('directionChange', nextDirection)
  emit('event', { type: 'directionChange', direction: nextDirection })
  void nextTick(fitView)
}

function handleFoldToggle(nodeId: string) {
  const node = nodeMap.value[nodeId]
  if (!node?.hasChildren) return
  const expanded = node.isCollapsed === true
  if (!props.readonly) recordHistory()
  foldOverrides.value = { ...foldOverrides.value, [nodeId]: expanded }
  emit('event', { type: expanded ? 'nodeExpand' : 'nodeCollapse', nodeId })
  void nextTick(fitView)
}

function handleSystemTheme(event: MediaQueryListEvent) {
  systemDark.value = event.matches
}

function refreshFormulaEngine() {
  if (!formulasEnabled.value) return
  void initFormulaEngine().catch(() => undefined)
}

function replaceData(data: MindMapData | MindMapData[], importSource?: 'xmind') {
  mapData.value = cloneMindMapData(normalizeData(data))
  splitIndices.value = {}
  foldOverrides.value = {}
  frontMatterTheme.value = undefined
  selectedNodeId.value = null
  editingNodeId.value = null
  editText.value = ''
  resetHistory()
  publishDataChange()
  publishMarkdown()
  if (importSource) {
    emit('event', {
      type: 'import',
      source: importSource,
      data: cloneMindMapData(mapData.value),
    })
  }
}

function setData(data: MindMapData | MindMapData[]) {
  replaceData(data)
}

function importData(data: MindMapData | MindMapData[]) {
  replaceData(data, 'xmind')
}

function replaceMarkdown(markdown: string, importSource?: 'markdown') {
  const previousDirection = direction.value
  const parsed = parseInitialMindMapInput(undefined, markdown, activePlugins.value)
  const nextDirection = parsed?.direction ?? props.defaultDirection
  mapData.value = parsed?.roots ?? [{ id: 'md-0', text: 'Root' }]
  splitIndices.value = {}
  foldOverrides.value = {}
  direction.value = nextDirection
  frontMatterTheme.value = parsed?.theme
  selectedNodeId.value = null
  editingNodeId.value = null
  editText.value = ''
  resetHistory()
  publishDataChange()
  emit('markdownChange', markdown)
  if (previousDirection !== nextDirection) emit('directionChange', nextDirection)
  if (importSource) {
    emit('event', {
      type: 'import',
      source: importSource,
      data: cloneMindMapData(mapData.value),
    })
  }
}

function setMarkdown(markdown: string) {
  replaceMarkdown(markdown)
}

function importMarkdown(markdown: string) {
  replaceMarkdown(markdown, 'markdown')
}

function selectNode(nodeId: string | null) {
  if (nodeId !== null && !nodeMap.value[nodeId]) return
  selectedNodeId.value = nodeId
  emit('event', { type: 'nodeSelect', nodeId })
}

function focusNode(nodeId: string) {
  const node = nodeMap.value[nodeId]
  if (!node) return
  selectNode(nodeId)
  void nextTick(() => {
    const svg = svgRef.value
    if (!svg) return
    pan.value = {
      x: svg.clientWidth / 2 - node.x * zoom.value,
      y: svg.clientHeight / 2 - node.y * zoom.value,
    }
  })
}

function setNodeExpanded(nodeId: string, expanded: boolean) {
  const node = nodeMap.value[nodeId]
  if (!node?.hasChildren) return
  recordHistory()
  foldOverrides.value = { ...foldOverrides.value, [nodeId]: expanded }
  emit('event', { type: expanded ? 'nodeExpand' : 'nodeCollapse', nodeId })
  void nextTick(fitView)
}

watch(() => props.data, applyInput, { deep: true })
watch(() => props.markdown, (value) => {
  if (value === undefined) return
  const currentMarkdown = mapData.value.length > 0
    ? toMarkdownMultiRoot(mapData.value, activePlugins.value)
    : ''
  if (currentMarkdown !== value) applyInput()
})
watch(() => props.activeTags, (tags) => {
  activeTags.value = [...tags]
  emit('activeTagsChange', [...tags])
})
watch(selectedNodeId, (nodeId) => {
  emit('selectedNodeChange', nodeId)
})
watch(activeTags, (tags) => {
  emit('activeTagsChange', [...tags])
}, { deep: true })
watch(formulasEnabled, refreshFormulaEngine)
watch(() => nodes.value, () => {
  void nextTick(() => {
    fitView()
    initialReady.value = true
  })
})

onMounted(() => {
  applyInput()

  mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
  systemDark.value = mediaQuery.matches
  mediaQuery.addEventListener('change', handleSystemTheme)

  stopFormulaSubscription = subscribeFormulaEngine(() => {
    formulaRevision.value += 1
  })
  refreshFormulaEngine()

  resizeObserver = new ResizeObserver(() => fitView())
  if (svgRef.value) resizeObserver.observe(svgRef.value)
  void nextTick(() => {
    fitView()
    initialReady.value = true
  })

})

onBeforeUnmount(() => {
  mediaQuery?.removeEventListener('change', handleSystemTheme)
  stopFormulaSubscription?.()
  resizeObserver?.disconnect()
})

defineExpose({
  getData: () => cloneMindMapData(mapData.value),
  getMarkdown: () => toMarkdownMultiRoot(mapData.value, activePlugins.value),
  setData,
  setMarkdown,
  importData,
  importMarkdown,
  exportToXMind: () => exportMindMapToXMind(mapData.value),
  exportToSVG: exportCurrentSVG,
  exportToPNG: exportCurrentPNG,
  selectNode,
  focusNode,
  expandNode: (nodeId: string) => setNodeExpanded(nodeId, true),
  collapseNode: (nodeId: string) => setNodeExpanded(nodeId, false),
  fitView,
  setDirection,
  undo: handleUndo,
  redo: handleRedo,
  canUndo: () => canUndo.value,
  canRedo: () => canRedo.value,
})
</script>

<template>
  <section
    class="mindmap-viewer"
    :style="themeVariables"
    aria-label="思维导图查看器"
  >
    <svg
      ref="svgRef"
      class="mindmap-svg"
      :class="{ 'dragging-canvas': isPanning, 'dragging-node': nodeDrag !== null }"
      tabindex="0"
      role="tree"
      @pointerdown="handlePointerDown"
      @pointermove="handlePointerMove"
      @pointerup="handlePointerUp"
      @pointercancel="handlePointerUp"
      @pointerleave="handlePointerUp"
      @wheel.prevent="handleWheel"
      @click="closeContextMenu"
      @contextmenu="handleCanvasContextMenu"
      @keydown="handleKeydown"
    >
      <MindMapCanvas
        :nodes="nodes"
        :edges="edges"
        :node-map="nodeMap"
        :theme="theme"
        :direction="direction"
        :plugins="activePlugins"
        :pan="pan"
        :zoom="zoom"
        :initial-ready="initialReady"
        :dragging-canvas="isPanning"
        :dimmed-nodes="dimmedNodes"
        :readonly="readonly"
        :selected-node-id="selectedNodeId"
        :editing-node-id="editingNodeId"
        :edit-text="editText"
        :drop-target-id="dropTargetId"
        @fold-toggle="handleFoldToggle"
        @node-click="handleNodeClick"
        @node-pointer-down="handleNodePointerDown"
        @node-double-click="handleNodeDoubleClick"
        @node-context-menu="handleNodeContextMenu"
        @edit-change="handleEditChange"
        @edit-commit="handleEditCommit"
        @edit-cancel="handleEditCancel"
        @add-child="handleAddChild"
      />
    </svg>

    <MindMapContextMenu
      v-if="contextMenu"
      :x="contextMenu.x"
      :y="contextMenu.y"
      :node-id="contextMenu.nodeId"
      :readonly="readonly"
      :can-paste="clipboardNode !== null"
      @close="closeContextMenu"
      @add-child="handleContextAddChild"
      @edit="handleContextEdit"
      @delete="handleContextDelete"
      @copy="handleContextCopy"
      @cut="handleContextCut"
      @paste="handleContextPaste"
      @new-root="handleContextNewRoot"
      @direction-change="setDirection"
      @export-svg="handleExportSVG"
      @export-png="handleExportPNG"
      @export-markdown="handleExportMarkdown"
      @export-xmind="handleExportXMind"
    />

    <div v-if="exportError" class="mindmap-export-error" role="alert">
      {{ exportError }}
    </div>

    <div v-if="toolbarConfig.history" class="mindmap-history-controls" aria-label="历史操作">
      <button type="button" class="mindmap-ctrl-btn" :disabled="!canUndo" aria-label="撤销" title="撤销" @click="handleUndo">
        ↶
      </button>
      <button type="button" class="mindmap-ctrl-btn" :disabled="!canRedo" aria-label="重做" title="重做" @click="handleRedo">
        ↷
      </button>
    </div>

    <div v-if="toolbarConfig.zoom" class="mindmap-zoom-controls" aria-label="缩放控制">
      <button type="button" class="mindmap-ctrl-btn" aria-label="缩小" title="缩小" @click="zoomOut">
        −
      </button>
      <button type="button" class="mindmap-ctrl-pct" aria-label="适配视图" title="适配视图" @click="fitView">
        {{ Math.round(zoom * 100) }}%
      </button>
      <button type="button" class="mindmap-ctrl-btn" aria-label="放大" title="放大" @click="zoomIn">
        +
      </button>
    </div>
  </section>
</template>

<style src="../styles/mindmap.css"></style>

<style>
.mindmap-viewer {
  position: relative;
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background: var(--mindmap-canvas-bg);
}

.mindmap-viewer > .mindmap-svg {
  display: block;
  width: 100%;
  height: 100%;
}
</style>
