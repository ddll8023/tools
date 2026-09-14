export type TaskStatus = 'todo' | 'doing' | 'done'

export interface CrossLink {
  targetAnchorId: string
  label?: string
  dotted?: boolean
}

export interface MindMapData {
  id: string
  text: string
  children?: MindMapData[]
  remark?: string
  taskStatus?: TaskStatus
  dottedLine?: boolean
  multiLineContent?: string[]
  tags?: string[]
  anchorId?: string
  crossLinks?: CrossLink[]
  collapsed?: boolean
  placeholder?: boolean
  listRoot?: boolean
}

export type LayoutDirection = 'left' | 'right' | 'both'

export type ThemeMode = 'light' | 'dark' | 'auto'

export interface ToolbarConfig {
  zoom?: boolean
  history?: boolean
  tags?: boolean
}

export interface LayoutNode {
  id: string
  text: string
  x: number
  y: number
  width: number
  height: number
  color: string
  depth: number
  side: 'left' | 'right' | 'root'
  parentId?: string
  remark?: string
  taskStatus?: TaskStatus
  branchIndex?: number
  dottedLine?: boolean
  multiLineContent?: string[]
  tags?: string[]
  anchorId?: string
  crossLinks?: CrossLink[]
  collapsed?: boolean
  /** True when the node has children, including when they are currently hidden. */
  hasChildren?: boolean
  /** Runtime folding state used by the renderer; does not change source data. */
  isCollapsed?: boolean
  placeholder?: boolean
}

export interface Edge {
  key: string
  path: string
  color: string
  fromId: string
  toId: string
  strokeDasharray?: string
  label?: string
  isCrossLink?: boolean
}

export type MindMapEvent =
  | { type: 'nodeAdd'; node: MindMapData; parentId: string | null }
  | { type: 'nodeDelete'; nodeId: string }
  | { type: 'nodeMove'; nodeId: string; targetId: string }
  | { type: 'nodeTextChange'; nodeId: string; oldText: string; newText: string }
  | { type: 'nodeSelect'; nodeId: string | null }
  | { type: 'nodeFocus'; nodeId: string }
  | { type: 'nodeCollapse'; nodeId: string }
  | { type: 'nodeExpand'; nodeId: string }
  | { type: 'import'; source: 'markdown' | 'json' | 'xmind'; data: MindMapData[] }
  | { type: 'undo'; canUndo: boolean; canRedo: boolean }
  | { type: 'redo'; canUndo: boolean; canRedo: boolean }
  | { type: 'historyChange'; canUndo: boolean; canRedo: boolean }
  | { type: 'tagFilterChange'; tags: string[] }
  | { type: 'modeChange'; mode: 'view' | 'text' }
  | { type: 'directionChange'; direction: LayoutDirection }
  | { type: 'zoomChange'; zoom: number }
  | { type: 'fullscreenChange'; fullscreen: boolean }

export interface MindMapPNGExportOptions {
  scale?: number
  padding?: number
  background?: string
}
