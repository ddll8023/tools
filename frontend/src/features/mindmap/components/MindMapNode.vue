<script setup lang="ts">
import { computed } from 'vue'
import {
  BRANCH_COLORS,
  buildSvgNodeTextString,
  buildSvgTextLineString,
  getLevel1TextColor,
  measureNodeContent,
} from '../core'
import type { LayoutNode } from '../core/types'
import type { MindMapPlugin } from '../core/plugins/types'
import type { ThemeColors } from '../core/utils/theme'
import { sanitizeGeneratedSvg } from './safe-svg'

interface Props {
  node: LayoutNode
  theme: ThemeColors
  plugins?: MindMapPlugin[]
  dimmed?: boolean
  direction: 'left' | 'right' | 'both'
  readonly?: boolean
  selected?: boolean
  editing?: boolean
  editText?: string
  dropTarget?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  plugins: () => [],
  dimmed: false,
  readonly: false,
  selected: false,
  editing: false,
  editText: '',
  dropTarget: false,
})

const emit = defineEmits<{
  foldToggle: [nodeId: string]
  nodeClick: [event: MouseEvent]
  nodePointerDown: [event: PointerEvent]
  nodeDoubleClick: [event: MouseEvent]
  nodeContextMenu: [event: MouseEvent]
  editChange: [text: string]
  editCommit: []
  editCancel: []
  addChild: [payload: { event: MouseEvent; side?: 'left' | 'right' }]
}>()

const isRoot = computed(() => props.node.depth === 0)
const isLevel1 = computed(() => props.node.depth === 1)
const fontSize = computed(() => {
  if (isRoot.value) return props.theme.root.fontSize
  return isLevel1.value ? props.theme.level1.fontSize : props.theme.node.fontSize
})
const fontWeight = computed(() => {
  if (isRoot.value) return props.theme.root.fontWeight
  return isLevel1.value ? props.theme.level1.fontWeight : props.theme.node.fontWeight
})
const fontFamily = computed(() => (isRoot.value ? props.theme.root.fontFamily : props.theme.node.fontFamily))
const textColor = computed(() => {
  if (isRoot.value) return props.theme.root.textColor
  if (isLevel1.value) return getLevel1TextColor(props.node.color, props.node.branchIndex)
  return props.theme.node.textColor
})

const content = computed(() => measureNodeContent(
  props.node,
  fontSize.value,
  fontWeight.value,
  fontFamily.value,
  props.plugins,
))

const svgMarkup = computed(() => {
  const parts = [
    buildSvgNodeTextString(
      props.node.text,
      fontSize.value,
      fontWeight.value,
      fontFamily.value,
      textColor.value,
      props.node.taskStatus,
      props.node.remark,
      props.plugins,
      props.theme.highlight.textColor,
      props.theme.highlight.bgColor,
    ),
  ]

  for (const [index, line] of (props.node.multiLineContent ?? []).entries()) {
    const layout = content.value.multiLines[index]
    if (!layout || layout.isMergedIntoMain) continue
    parts.push(buildSvgTextLineString(
      line,
      layout.fontSize,
      400,
      fontFamily.value,
      textColor.value,
      layout.y,
      props.plugins,
      props.theme.highlight.textColor,
      props.theme.highlight.bgColor,
    ))
  }

  return sanitizeGeneratedSvg(parts.join(''))
})

const tagBadges = computed(() => {
  const tags = props.node.tags ?? []
  if (tags.length === 0) return []

  const tagFontSize = fontSize.value * 0.65
  const widths = tags.map((tag) => tag.length * tagFontSize * 0.65 + 10)
  const totalWidth = widths.reduce((sum, width) => sum + width, 0) + (tags.length - 1) * 4
  let x = -totalWidth / 2
  const colors = BRANCH_COLORS

  return tags.map((tag, index) => {
    const width = widths[index]
    const badge = {
      tag,
      x,
      width,
      color: colors[index % colors.length],
      fontSize: tagFontSize,
      y: content.value.tagY,
    }
    x += width + 4
    return badge
  })
})

const nodeClass = computed(() => [
  'mindmap-node-g',
  isRoot.value ? 'mindmap-node-root' : 'mindmap-node-child',
  isLevel1.value ? 'mindmap-node-level1' : '',
  props.dimmed ? 'mindmap-node-filter-dimmed' : '',
  props.selected ? 'mindmap-node-selected' : '',
  props.dropTarget ? 'mindmap-node-drop-target' : '',
  props.editing ? 'mindmap-node-editing' : '',
  props.node.placeholder ? 'mindmap-node-placeholder' : '',
])

const showInput = computed(() => props.editing)
const editInputWidth = computed(() => Math.max(props.node.width - 12, 80))

function handleNodeClick(event: MouseEvent) {
  if (props.readonly) return
  event.stopPropagation()
  emit('nodeClick', event)
}

function handleNodePointerDown(event: PointerEvent) {
  if (props.readonly || event.button !== 0) return
  const target = event.target as Element | null
  if (target?.closest('.mindmap-add-btn, .mindmap-fold-btn, .mindmap-edit-input')) return
  event.stopPropagation()
  emit('nodePointerDown', event)
}

function handleNodeDoubleClick(event: MouseEvent) {
  if (props.readonly) return
  event.stopPropagation()
  emit('nodeDoubleClick', event)
}

function handleNodeContextMenu(event: MouseEvent) {
  if (props.readonly) return
  event.preventDefault()
  event.stopPropagation()
  emit('nodeContextMenu', event)
}

function handleEditKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter') {
    event.preventDefault()
    emit('editCommit')
  } else if (event.key === 'Escape') {
    event.preventDefault()
    emit('editCancel')
  }
}

function focusEditInput(element: HTMLInputElement | null) {
  if (!element) return
  requestAnimationFrame(() => {
    element.focus()
    element.select()
  })
}

function handleEditInput(event: Event) {
  emit('editChange', (event.target as HTMLInputElement).value)
}

const foldX = computed(() => {
  const offset = props.node.width / 2 + 14
  if (isRoot.value) return props.direction === 'left' ? -offset : offset
  return props.node.side === 'left' ? -offset : offset
})

function toggleFold(event: MouseEvent | KeyboardEvent) {
  event.stopPropagation()
  emit('foldToggle', props.node.id)
}

function handleFoldKeydown(event: KeyboardEvent) {
  if (event.key !== 'Enter' && event.key !== ' ') return
  event.preventDefault()
  toggleFold(event)
}
</script>

<template>
  <g
    :class="nodeClass"
    :transform="`translate(${node.x}, ${node.y})`"
    role="treeitem"
    :aria-label="node.text"
    :aria-selected="selected"
    :tabindex="readonly ? undefined : 0"
    :data-node-id="node.id"
    @pointerdown="handleNodePointerDown"
    @mousedown.stop
    @click="handleNodeClick"
    @dblclick="handleNodeDoubleClick"
    @contextmenu="handleNodeContextMenu"
  >
    <rect
      class="mindmap-node-bg"
      :x="-node.width / 2"
      :y="-node.height / 2"
      :width="node.width"
      :height="node.height"
      :rx="isRoot ? node.height / 2 : isLevel1 ? 8 : 4"
      :ry="isRoot ? node.height / 2 : isLevel1 ? 8 : 4"
      :fill="isRoot ? theme.root.bgColor : isLevel1 ? node.color : selected || dropTarget ? theme.selection.fillColor : 'transparent'"
      :stroke="selected || dropTarget ? theme.selection.strokeColor : 'none'"
      :stroke-width="dropTarget ? 3 : selected ? 2.5 : 0"
      :stroke-dasharray="dropTarget ? '6 4' : undefined"
    />

    <foreignObject
      v-if="showInput"
      :x="-editInputWidth / 2"
      :y="-node.height / 2"
      :width="editInputWidth"
      :height="node.height"
    >
      <input
        :ref="focusEditInput"
        class="mindmap-edit-input"
        :value="editText"
        :style="{
          fontSize: `${fontSize}px`,
          fontWeight: String(fontWeight),
          fontFamily,
          color: textColor,
          borderBottom: isRoot || isLevel1 ? 'none' : `2.5px solid ${node.color}`,
        }"
        aria-label="编辑节点文本"
        @input="handleEditInput"
        @keydown="handleEditKeydown"
        @blur="emit('editCommit')"
        @mousedown.stop
        @click.stop
      />
    </foreignObject>

    <g v-else class="mindmap-node-content" v-html="svgMarkup"></g>

    <g v-if="!showInput" v-for="badge in tagBadges" :key="`${node.id}-${badge.tag}`" class="mindmap-tag">
      <rect
        class="mindmap-tag-bg"
        :x="badge.x"
        :y="badge.y"
        :width="badge.width"
        :height="badge.fontSize + 6"
        rx="3"
        :fill="badge.color"
        opacity="0.15"
      />
      <text
        class="mindmap-tag-text"
        :x="badge.x + badge.width / 2"
        :y="badge.y + (badge.fontSize + 6) / 2"
        text-anchor="middle"
        dominant-baseline="central"
        :font-size="badge.fontSize"
        :fill="badge.color"
        :font-family="fontFamily"
      >
        {{ badge.tag }}
      </text>
    </g>

    <line
      v-if="!showInput && !isRoot && !isLevel1"
      class="mindmap-node-underline"
      :x1="-(node.width - theme.node.paddingH * 2) / 2"
      :y1="Math.max(fontSize / 2 + 4, content.main.bottom + 4)"
      :x2="(node.width - theme.node.paddingH * 2) / 2"
      :y2="Math.max(fontSize / 2 + 4, content.main.bottom + 4)"
      :stroke="node.color"
      stroke-width="2.5"
      stroke-linecap="round"
    />

    <g
      v-if="!showInput && node.hasChildren"
      class="mindmap-fold-btn"
      role="button"
      tabindex="0"
      :aria-label="node.isCollapsed ? '展开节点' : '折叠节点'"
      :aria-expanded="!node.isCollapsed"
      @pointerdown.stop
      @mousedown.stop
      @click="toggleFold"
      @keydown="handleFoldKeydown"
    >
      <title>{{ node.isCollapsed ? '展开节点' : '折叠节点' }}</title>
      <circle class="mindmap-fold-hit" :cx="foldX" cy="0" r="14" fill="transparent" />
      <rect
        class="mindmap-fold-surface"
        :x="foldX - 10"
        y="-10"
        width="20"
        height="20"
        rx="6"
        fill="transparent"
        stroke="transparent"
        stroke-width="1.5"
      />
      <g :transform="`translate(${foldX}, 0)`" aria-hidden="true" pointer-events="none">
        <path
          class="mindmap-fold-chevron"
          d="M -2 -4 L 2 0 L -2 4"
          fill="none"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </g>
    </g>

    <template v-if="!readonly && !showInput">
      <g
        v-if="isRoot && (direction === 'right' || direction === 'both')"
        class="mindmap-add-btn"
        @pointerdown.stop
        @mousedown.stop
        @click.stop="emit('addChild', { event: $event, side: 'right' })"
      >
        <circle :cx="node.width / 2 + 18" cy="0" r="11" :fill="theme.addBtn.fill" />
        <line :x1="node.width / 2 + 14" y1="0" :x2="node.width / 2 + 22" y2="0" :stroke="theme.addBtn.iconColor" stroke-width="2" stroke-linecap="round" />
        <line :x1="node.width / 2 + 18" y1="-4" :x2="node.width / 2 + 18" y2="4" :stroke="theme.addBtn.iconColor" stroke-width="2" stroke-linecap="round" />
      </g>
      <g
        v-if="isRoot && (direction === 'left' || direction === 'both')"
        class="mindmap-add-btn"
        @pointerdown.stop
        @mousedown.stop
        @click.stop="emit('addChild', { event: $event, side: 'left' })"
      >
        <circle :cx="-(node.width / 2 + 18)" cy="0" r="11" :fill="theme.addBtn.fill" />
        <line :x1="-(node.width / 2 + 22)" y1="0" :x2="-(node.width / 2 + 14)" y2="0" :stroke="theme.addBtn.iconColor" stroke-width="2" stroke-linecap="round" />
        <line :x1="-(node.width / 2 + 18)" y1="-4" :x2="-(node.width / 2 + 18)" y2="4" :stroke="theme.addBtn.iconColor" stroke-width="2" stroke-linecap="round" />
      </g>
      <g
        v-if="!isRoot"
        class="mindmap-add-btn"
        @pointerdown.stop
        @mousedown.stop
        @click.stop="emit('addChild', { event: $event })"
      >
        <circle :cx="node.side === 'left' ? -(node.width / 2 + 18) : node.width / 2 + 18" cy="0" r="11" :fill="theme.addBtn.fill" />
        <line :x1="(node.side === 'left' ? -(node.width / 2 + 22) : node.width / 2 + 14)" y1="0" :x2="(node.side === 'left' ? -(node.width / 2 + 14) : node.width / 2 + 22)" y2="0" :stroke="theme.addBtn.iconColor" stroke-width="2" stroke-linecap="round" />
        <line :x1="node.side === 'left' ? -(node.width / 2 + 18) : node.width / 2 + 18" y1="-4" :x2="node.side === 'left' ? -(node.width / 2 + 18) : node.width / 2 + 18" y2="4" :stroke="theme.addBtn.iconColor" stroke-width="2" stroke-linecap="round" />
      </g>
    </template>
  </g>
</template>
