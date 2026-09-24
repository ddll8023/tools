<!-- 思维导图画布：渲染连线、节点以及拖拽反馈。 -->
<script setup lang="ts">
import MindMapNode from './MindMapNode.vue'
import type { Edge, LayoutDirection, LayoutNode } from '../core/types'
import type { MindMapPlugin } from '../core/plugins/types'
import type { ThemeColors } from '../core/utils/theme'

interface DropIndicator {
  x: number
  y: number
  width: number
  color: string
}

interface Props {
  nodes: LayoutNode[]
  edges: Edge[]
  nodeMap: Record<string, LayoutNode>
  theme: ThemeColors
  direction: LayoutDirection
  plugins?: MindMapPlugin[]
  pan: { x: number; y: number }
  zoom: number
  initialReady: boolean
  draggingCanvas?: boolean
  draggingNodeId?: string | null
  dropIndicator?: DropIndicator | null
  dimmedNodes?: ReadonlySet<string>
  readonly?: boolean
  selectedNodeId?: string | null
  editingNodeId?: string | null
  editText?: string
  dropTargetId?: string | null
}

const props = withDefaults(defineProps<Props>(), {
  plugins: () => [],
  draggingCanvas: false,
  draggingNodeId: null,
  dropIndicator: null,
  dimmedNodes: () => new Set<string>(),
})

const emit = defineEmits<{
  foldToggle: [nodeId: string]
  nodeClick: [event: MouseEvent, nodeId: string]
  nodePointerDown: [event: PointerEvent, nodeId: string]
  nodeDoubleClick: [event: MouseEvent, nodeId: string, text: string]
  nodeContextMenu: [event: MouseEvent, nodeId: string]
  editChange: [text: string]
  editCommit: []
  editCancel: []
  addChild: [event: MouseEvent, parentId: string, side?: 'left' | 'right']
}>()

function edgeClass(edge: Edge): string[] {
  return [
    'mindmap-edge',
    edge.isCrossLink ? 'mindmap-edge-cross-link' : '',
    props.draggingCanvas ? '' : 'mindmap-edge-animated',
  ].filter(Boolean)
}

function handleNodePointerDown(event: PointerEvent, node: LayoutNode) {
  emit('nodePointerDown', event, node.id)
}

function handleNodeDoubleClick(event: MouseEvent, node: LayoutNode) {
  emit('nodeDoubleClick', event, node.id, node.text)
}

function handleAddChild(
  payload: { event: MouseEvent; side?: 'left' | 'right' },
  node: LayoutNode,
) {
  emit('addChild', payload.event, node.id, payload.side)
}
</script>

<template>
  <g
    :class="['mindmap-canvas', initialReady ? 'mindmap-canvas-ready' : '']"
    :transform="`translate(${pan.x}, ${pan.y}) scale(${zoom})`"
    :opacity="initialReady ? 1 : 0"
  >
    <g class="mindmap-edges">
      <defs v-if="edges.some((edge) => edge.isCrossLink)">
        <marker
          id="mindmap-arrowhead"
          marker-width="8"
          marker-height="6"
          refX="8"
          refY="3"
          orient="auto"
        >
          <path
            d="M0,0 L8,3 L0,6"
            fill="none"
            stroke="currentColor"
            stroke-width="1.5"
          />
        </marker>
      </defs>

      <g v-for="edge in edges" :key="edge.key">
        <path
          :d="edge.path"
          :class="edgeClass(edge)"
          :stroke="edge.color"
          :stroke-width="theme.connection.strokeWidth"
          stroke-linecap="round"
          :stroke-dasharray="edge.strokeDasharray"
          :marker-end="edge.isCrossLink ? 'url(#mindmap-arrowhead)' : undefined"
          :opacity="edge.isCrossLink ? 0.7 : 1"
          fill="none"
        />
        <text
          v-if="edge.label && nodeMap[edge.fromId] && nodeMap[edge.toId]"
          class="mindmap-edge-label"
          :x="(nodeMap[edge.fromId].x + nodeMap[edge.toId].x) / 2"
          :y="(nodeMap[edge.fromId].y + nodeMap[edge.toId].y) / 2 - 6"
          text-anchor="middle"
          font-size="11"
          :fill="edge.color"
          opacity="0.8"
          :font-family="theme.node.fontFamily"
        >
          {{ edge.label }}
        </text>
      </g>
    </g>

    <line
      v-if="dropIndicator"
      class="mindmap-drop-indicator"
      :x1="dropIndicator.x - dropIndicator.width / 2"
      :x2="dropIndicator.x + dropIndicator.width / 2"
      :y1="dropIndicator.y"
      :y2="dropIndicator.y"
      :stroke="dropIndicator.color"
      stroke-width="3"
      stroke-linecap="round"
    />

    <g class="mindmap-nodes">
      <MindMapNode
        v-for="node in nodes"
        :key="node.id"
        :node="node"
        :theme="theme"
        :direction="direction"
        :plugins="plugins"
        :dimmed="dimmedNodes.has(node.id)"
        :readonly="readonly"
        :selected="selectedNodeId === node.id"
        :dragging="draggingNodeId === node.id"
        :editing="editingNodeId === node.id"
        :edit-text="editText"
        :drop-target="dropTargetId === node.id"
        @fold-toggle="emit('foldToggle', $event)"
        @node-click="emit('nodeClick', $event, node.id)"
        @node-pointer-down="handleNodePointerDown($event, node)"
        @node-double-click="handleNodeDoubleClick($event, node)"
        @node-context-menu="emit('nodeContextMenu', $event, node.id)"
        @edit-change="emit('editChange', $event)"
        @edit-commit="emit('editCommit')"
        @edit-cancel="emit('editCancel')"
        @add-child="handleAddChild($event, node)"
      />
    </g>
  </g>
</template>
