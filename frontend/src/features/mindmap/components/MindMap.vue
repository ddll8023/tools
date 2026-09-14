<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { BaseSelect } from '@/components/common'
import type { SelectOption } from '@/components/common'
import MindMapTextEditor from './MindMapTextEditor.vue'
import MindMapViewer from './MindMapViewer.vue'
import {
  normalizeData,
  toMarkdownMultiRoot,
} from '../core'
import type {
  LayoutDirection,
  MindMapData,
  MindMapEvent,
  MindMapPlugin,
  ThemeMode,
  ToolbarConfig,
} from '../core'

interface Props {
  markdown?: string
  data?: MindMapData | MindMapData[]
  defaultDirection?: LayoutDirection
  theme?: ThemeMode
  locale?: string
  readonly?: boolean
  toolbar?: boolean | ToolbarConfig
  activeTags?: string[]
  plugins?: MindMapPlugin[]
}

type MindMapExportFormat = 'markdown' | 'xmind' | 'svg' | 'png'

const exportOptions: SelectOption[] = [
  { value: 'markdown', label: 'Markdown' },
  { value: 'xmind', label: 'XMind' },
  { value: 'svg', label: 'SVG' },
  { value: 'png', label: 'PNG' },
]

const directionOptions: SelectOption[] = [
  { value: 'right', label: '向右展开' },
  { value: 'left', label: '向左展开' },
  { value: 'both', label: '两侧展开' },
]

const DEFAULT_MARKDOWN = `思维导图
- 从 Markdown 开始
  - 编写大纲
  - 查看地图更新
- 梳理结构
  - 每级使用两个空格
  - 添加 **粗体** 或 #标签
- 导出结果
  - SVG 在任意尺寸都清晰
  - PNG 支持 2x、3x 和 4x`

const props = withDefaults(defineProps<Props>(), {
  defaultDirection: 'right',
  theme: 'auto',
  readonly: false,
  toolbar: true,
  activeTags: () => [],
  plugins: () => [],
})

const emit = defineEmits<{
  'update:markdown': [value: string]
  dataChange: [data: MindMapData[]]
  event: [event: MindMapEvent]
  directionChange: [direction: LayoutDirection]
  selectedNodeChange: [nodeId: string | null]
  activeTagsChange: [tags: string[]]
  importRequest: []
  exportRequest: [format: MindMapExportFormat]
  reset: []
}>()

const localMarkdown = ref(
  props.markdown
  ?? (props.data ? toMarkdownMultiRoot(normalizeData(props.data), props.plugins) : DEFAULT_MARKDOWN),
)
const direction = ref<LayoutDirection>(props.defaultDirection)
const exportFormat = ref('')
const viewerRef = ref<InstanceType<typeof MindMapViewer> | null>(null)
const editorCollapsed = ref(false)

const currentMarkdown = computed(() => localMarkdown.value)

watch(() => props.markdown, (value) => {
  if (value !== undefined) localMarkdown.value = value
})
watch(() => props.data, (value) => {
  if (props.markdown === undefined && value) {
    localMarkdown.value = toMarkdownMultiRoot(normalizeData(value), props.plugins)
  }
}, { deep: true })

function handleMarkdownChange(value: string) {
  localMarkdown.value = value
  emit('update:markdown', value)
}

function handleViewerMarkdownChange(value: string) {
  handleMarkdownChange(value)
}

function handleDirectionChange(value: LayoutDirection) {
  direction.value = value
  viewerRef.value?.setDirection(value)
  emit('directionChange', value)
}

function handleViewerDirectionChange(value: LayoutDirection) {
  direction.value = value
  emit('directionChange', value)
}

function handleViewerDataChange(data: MindMapData[]) {
  emit('dataChange', data)
}

function handleViewerSelectedNodeChange(nodeId: string | null) {
  emit('selectedNodeChange', nodeId)
}

function handleViewerActiveTagsChange(tags: string[]) {
  emit('activeTagsChange', tags)
}

function resetExample() {
  handleMarkdownChange(DEFAULT_MARKDOWN)
  handleDirectionChange(props.defaultDirection)
  emit('reset')
}

function toggleEditor() {
  editorCollapsed.value = !editorCollapsed.value
  requestAnimationFrame(() => viewerRef.value?.fitView())
}

function handleExportSelect(format: string) {
  exportFormat.value = ''
  if (format === 'markdown' || format === 'xmind' || format === 'svg' || format === 'png') {
    emit('exportRequest', format)
  }
}

function handleDirectionSelect(value: string) {
  if (value === 'left' || value === 'right' || value === 'both') {
    handleDirectionChange(value)
  }
}

defineExpose({
  getMarkdown: () => viewerRef.value?.getMarkdown() ?? currentMarkdown.value,
  getData: () => viewerRef.value?.getData() ?? [],
  setData: (data: MindMapData | MindMapData[]) => viewerRef.value?.setData(data),
  setMarkdown: (value: string) => {
    localMarkdown.value = value
    viewerRef.value?.setMarkdown(value)
    emit('update:markdown', value)
  },
  importData: (data: MindMapData | MindMapData[]) => viewerRef.value?.importData(data),
  importMarkdown: (value: string) => {
    localMarkdown.value = value
    viewerRef.value?.importMarkdown(value)
    emit('update:markdown', value)
  },
  exportToXMind: () => viewerRef.value?.exportToXMind(),
  exportToSVG: () => viewerRef.value?.exportToSVG(),
  exportToPNG: () => viewerRef.value?.exportToPNG(),
  selectNode: (nodeId: string | null) => viewerRef.value?.selectNode(nodeId),
  focusNode: (nodeId: string) => viewerRef.value?.focusNode(nodeId),
  expandNode: (nodeId: string) => viewerRef.value?.expandNode(nodeId),
  collapseNode: (nodeId: string) => viewerRef.value?.collapseNode(nodeId),
  undo: () => viewerRef.value?.undo(),
  redo: () => viewerRef.value?.redo(),
  canUndo: () => viewerRef.value?.canUndo() ?? false,
  canRedo: () => viewerRef.value?.canRedo() ?? false,
  fitView: () => viewerRef.value?.fitView(),
  setDirection: handleDirectionChange,
})
</script>

<template>
  <section class="mindmap-workspace" aria-label="思维导图工作区">
    <header class="mindmap-workspace-toolbar">
      <div class="mindmap-workspace-title">
        <span class="mindmap-workspace-status" aria-hidden="true"></span>
        <h2>实时思维导图</h2>
      </div>
      <div class="mindmap-workspace-actions">
        <button type="button" class="mindmap-workspace-button mindmap-workspace-button--primary" @click="emit('importRequest')">
          导入
        </button>
        <BaseSelect
          v-model="exportFormat"
          :options="exportOptions"
          placeholder="导出"
          size="sm"
          aria-label="导出思维导图"
          @change="handleExportSelect"
        />
        <label class="mindmap-direction-control">
          <span>布局</span>
          <BaseSelect
            :model-value="direction"
            :options="directionOptions"
            size="sm"
            aria-label="布局方向"
            @change="handleDirectionSelect"
          />
        </label>
        <button type="button" class="mindmap-workspace-button" @click="toggleEditor">
          {{ editorCollapsed ? '显示编辑器' : '隐藏编辑器' }}
        </button>
        <button type="button" class="mindmap-workspace-button" @click="resetExample">
          重置示例
        </button>
      </div>
    </header>

    <div class="mindmap-workspace-grid" :class="{ 'is-editor-collapsed': editorCollapsed }">
      <section v-if="!editorCollapsed" class="mindmap-editor-panel" aria-label="Markdown 编辑器">
        <div class="mindmap-panel-heading">
          <h3>编写结构</h3>
          <span>{{ currentMarkdown.length.toLocaleString() }} 个字符</span>
        </div>
        <div class="mindmap-editor-content">
          <MindMapTextEditor
            :model-value="currentMarkdown"
            class-name="mindmap-workspace-editor"
            :readonly="readonly"
            @update:model-value="handleMarkdownChange"
          />
        </div>
        <p class="mindmap-editor-hint">两个空格表示一级子节点；修改后地图会实时更新。</p>
      </section>

      <section class="mindmap-map-panel" aria-label="思维导图预览">
        <MindMapViewer
          ref="viewerRef"
          :markdown="currentMarkdown"
          :data="markdown === undefined ? data : undefined"
          :active-tags="activeTags"
          :default-direction="direction"
          :theme="theme"
          :toolbar="toolbar"
          :plugins="plugins"
          :readonly="readonly"
          @event="emit('event', $event)"
          @markdown-change="handleViewerMarkdownChange"
          @data-change="handleViewerDataChange"
          @selected-node-change="handleViewerSelectedNodeChange"
          @active-tags-change="handleViewerActiveTagsChange"
          @direction-change="handleViewerDirectionChange"
        />
      </section>
    </div>
  </section>
</template>

<style>
.mindmap-workspace {
  display: flex;
  width: 100%;
  height: 100%;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  background: var(--color-surface);
  color: var(--color-text);
  font-family: inherit;
}

.mindmap-workspace-toolbar {
  display: flex;
  min-height: 52px;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid var(--color-border);
  background: var(--color-surface);
  padding: 10px 16px;
}

.mindmap-workspace-title,
.mindmap-workspace-actions,
.mindmap-direction-control {
  display: flex;
  align-items: center;
}

.mindmap-workspace-title,
.mindmap-workspace-actions {
  gap: 10px;
}

.mindmap-workspace-actions {
  flex-wrap: wrap;
  justify-content: flex-end;
}

.mindmap-workspace-title h2 {
  margin: 0;
  font-size: 14px;
  font-weight: 600;
}

.mindmap-workspace-status {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: var(--color-primary);
  box-shadow: 0 0 0 4px color-mix(in srgb, var(--color-primary) 14%, transparent);
}

.mindmap-direction-control {
  gap: 6px;
  color: var(--color-text-secondary);
  font-size: 12px;
}

.mindmap-workspace-button {
  cursor: pointer;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  background: var(--color-surface);
  color: var(--color-text-secondary);
  font: inherit;
  font-size: 13px;
  padding: 7px 12px;
  transition: border-color 0.2s, background 0.2s, color 0.2s;
}

.mindmap-workspace-button:hover {
  border-color: var(--color-primary);
  background: var(--color-hover);
  color: var(--color-primary-dark);
}

.mindmap-workspace-button:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

.mindmap-workspace-button--primary {
  border-color: var(--color-primary);
  background: var(--color-primary);
  color: #fff;
}

.mindmap-workspace-button--primary:hover {
  border-color: var(--color-primary-dark);
  background: var(--color-primary-dark);
  color: #fff;
}

.mindmap-workspace-grid {
  display: grid;
  min-height: 0;
  flex: 1;
  grid-template-columns: minmax(260px, 340px) minmax(0, 1fr);
}

.mindmap-workspace-grid.is-editor-collapsed {
  grid-template-columns: minmax(0, 1fr);
}

.mindmap-editor-panel {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  border-right: 1px solid var(--color-border);
  background: var(--color-bg);
}

.mindmap-panel-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--color-border);
  padding: 12px 14px;
}

.mindmap-panel-heading h3 {
  margin: 0;
  font-size: 13px;
  font-weight: 600;
}

.mindmap-panel-heading span,
.mindmap-editor-hint {
  color: var(--color-text-tertiary);
  font-size: 11px;
}

.mindmap-editor-content {
  position: relative;
  min-height: 0;
  flex: 1;
  overflow: hidden;
}

.mindmap-workspace-editor {
  padding: 16px;
}

.mindmap-editor-hint {
  margin: 0;
  border-top: 1px solid var(--color-border);
  padding: 9px 14px;
}

.mindmap-map-panel {
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: var(--color-bg);
}

@media (max-width: 860px) {
  .mindmap-workspace-grid {
    grid-template-columns: 1fr;
    grid-template-rows: minmax(220px, 40%) minmax(0, 1fr);
  }

  .mindmap-editor-panel {
    border-right: 0;
    border-bottom: 1px solid var(--color-border);
  }
}
</style>
