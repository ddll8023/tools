<script setup lang="ts">
import { nextTick, onMounted, ref } from 'vue'
import type { LayoutDirection } from '../core'

interface Props {
  x: number
  y: number
  nodeId: string | null
  readonly?: boolean
  canPaste?: boolean
}

const props = withDefaults(defineProps<Props>(), {
  readonly: false,
  canPaste: false,
})

const emit = defineEmits<{
  close: []
  addChild: []
  edit: []
  delete: []
  copy: []
  cut: []
  paste: []
  newRoot: []
  directionChange: [direction: LayoutDirection]
  exportSVG: []
  exportPNG: []
  exportMarkdown: []
  exportXMind: []
}>()

const menuRef = ref<HTMLElement | null>(null)

function closeAfter(action: () => void) {
  action()
  emit('close')
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') {
    event.preventDefault()
    emit('close')
    return
  }
  if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return

  const items = Array.from(menuRef.value?.querySelectorAll<HTMLButtonElement>('[role="menuitem"]') ?? [])
    .filter((item) => !item.disabled)
  if (items.length === 0) return

  event.preventDefault()
  const activeIndex = items.indexOf(document.activeElement as HTMLButtonElement)
  const offset = event.key === 'ArrowDown' ? 1 : -1
  items[(activeIndex + offset + items.length) % items.length].focus()
}

onMounted(async () => {
  await nextTick()
  menuRef.value?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus()
})
</script>

<template>
  <div
    ref="menuRef"
    class="mindmap-context-menu"
    :style="{ left: `${x}px`, top: `${y}px` }"
    role="menu"
    tabindex="-1"
    @click.stop
    @contextmenu.prevent.stop
    @keydown="handleKeydown"
  >
    <template v-if="nodeId">
      <template v-if="!readonly">
        <button type="button" class="mindmap-ctx-item" role="menuitem" @click="closeAfter(() => emit('addChild'))">
          添加子节点
        </button>
        <button type="button" class="mindmap-ctx-item" role="menuitem" @click="closeAfter(() => emit('edit'))">
          编辑节点
        </button>
        <div class="mindmap-ctx-divider" role="separator" />
      </template>
      <button type="button" class="mindmap-ctx-item" role="menuitem" @click="closeAfter(() => emit('copy'))">
        复制节点
      </button>
      <template v-if="!readonly">
        <button type="button" class="mindmap-ctx-item" role="menuitem" @click="closeAfter(() => emit('cut'))">
          剪切节点
        </button>
        <button type="button" class="mindmap-ctx-item" role="menuitem" :disabled="!canPaste" @click="closeAfter(() => emit('paste'))">
          粘贴为子节点
        </button>
        <div class="mindmap-ctx-divider" role="separator" />
        <button type="button" class="mindmap-ctx-item mindmap-ctx-delete" role="menuitem" @click="closeAfter(() => emit('delete'))">
          删除节点
        </button>
      </template>
      <div class="mindmap-ctx-divider" role="separator" />
    </template>
    <template v-else-if="!readonly">
      <button type="button" class="mindmap-ctx-item" role="menuitem" @click="closeAfter(() => emit('newRoot'))">
        新建根节点
      </button>
      <div class="mindmap-ctx-divider" role="separator" />
    </template>

    <div class="mindmap-ctx-divider" role="separator" />
    <button type="button" class="mindmap-ctx-item" role="menuitem" @click="closeAfter(() => emit('directionChange', 'left'))">
      向左布局
    </button>
    <button type="button" class="mindmap-ctx-item" role="menuitem" @click="closeAfter(() => emit('directionChange', 'both'))">
      两侧布局
    </button>
    <button type="button" class="mindmap-ctx-item" role="menuitem" @click="closeAfter(() => emit('directionChange', 'right'))">
      向右布局
    </button>
    <div class="mindmap-ctx-divider" role="separator" />
    <button type="button" class="mindmap-ctx-item" role="menuitem" @click="closeAfter(() => emit('exportSVG'))">
      导出 SVG
    </button>
    <button type="button" class="mindmap-ctx-item" role="menuitem" @click="closeAfter(() => emit('exportPNG'))">
      导出 PNG
    </button>
    <button type="button" class="mindmap-ctx-item" role="menuitem" @click="closeAfter(() => emit('exportMarkdown'))">
      导出 Markdown
    </button>
    <button type="button" class="mindmap-ctx-item" role="menuitem" @click="closeAfter(() => emit('exportXMind'))">
      导出 XMind
    </button>
  </div>
</template>
