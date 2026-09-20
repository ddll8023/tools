<!-- Markdown 来源选择器：复用选择、拖拽和桌面路径解析，不发起转换请求。 -->
<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import type { MarkdownSource } from '../source'

const props = withDefaults(defineProps<{
  disabled?: boolean
  maxMarkdownBytes?: number
}>(), { disabled: false, maxMarkdownBytes: 50 * 1024 * 1024 })
const emit = defineEmits<{
  select: [source: MarkdownSource]
  error: [message: string]
}>()
const fileInput = ref<HTMLInputElement | null>(null)
const picking = ref(false)
const isDesktop = computed(() => Boolean(window.desktopApi?.fileDialog))
const unavailable = computed(() => props.disabled || picking.value)
let disposed = false
onBeforeUnmount(() => { disposed = true })

function validate(name: string, size: number): boolean {
  if (!/\.(md|markdown|zip)$/i.test(name)) {
    emit('error', '仅支持 .md、.markdown 或 .zip 文件')
    return false
  }
  const limit = /\.zip$/i.test(name) ? 50 * 1024 * 1024 : props.maxMarkdownBytes
  if (size === 0 || size > limit) {
    emit('error', size === 0 ? '文件不能为空' : `该文件不能超过 ${limit / 1024 / 1024}MB`)
    return false
  }
  return true
}

function acceptFiles(files: FileList | null) {
  if (unavailable.value || !files?.length) return
  const dialog = window.desktopApi?.fileDialog
  // 每次都消费缓存，避免上一次 ZIP/多文件拖入的路径影响后续选择。
  const paths = dialog?.takeDroppedPaths() ?? []
  if (files.length !== 1) {
    emit('error', '每次请选择一个 Markdown 或 ZIP 文件')
    return
  }
  const file = files[0]
  if (!validate(file.name, file.size)) return
  let localPath = ''
  if (dialog && /\.(md|markdown)$/i.test(file.name)) {
    try {
      localPath = dialog.getPathForFile(file)
    } catch {
      // File 跨 contextBridge 后可能失去磁盘来源，回退到 preload 的事件缓存。
    }
    if (!localPath && paths.length === 1 && paths[0].split(/[\\/]/).pop() === file.name) {
      localPath = paths[0]
    }
  }
  emit('select', localPath
    ? { kind: 'local', name: file.name, size: file.size, path: localPath }
    : { kind: 'upload', name: file.name, size: file.size, file })
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  acceptFiles(input.files)
  input.value = ''
}

async function pickLocalMarkdown() {
  if (unavailable.value) return
  picking.value = true
  try {
    const picked = await window.desktopApi?.fileDialog.pickMarkdown()
    if (!picked || disposed || props.disabled || !validate(picked.name, picked.size)) return
    emit('select', { kind: 'local', ...picked })
  } catch {
    if (!disposed) emit('error', '无法打开文件选择对话框，请重试')
  } finally {
    picking.value = false
  }
}
</script>

<template>
  <div
    class="border-border rounded-xl border-2 border-dashed px-5 py-9 text-center"
    :class="unavailable ? 'opacity-60' : 'hover:border-primary hover:bg-primary-light'"
    @dragover.prevent
    @drop.prevent="acceptFiles($event.dataTransfer?.files ?? null)"
  >
    <font-awesome-icon :icon="['far', 'file-lines']" class="text-text-secondary mb-3 text-3xl" aria-hidden="true" />
    <h2 class="mb-2 text-base font-semibold">选择或拖入 Markdown 文件</h2>
    <p class="text-text-secondary mb-5 text-sm">
      {{ isDesktop ? '选择本地文件可读取文档目录内的图片；也可上传资源 ZIP' : '图片需与 Markdown 一起打包为 ZIP' }}
    </p>
    <div class="flex flex-wrap justify-center gap-3">
      <button
        v-if="isDesktop"
        type="button"
        class="bg-primary hover:bg-primary-dark focus-visible:outline-primary rounded-lg px-5 py-2.5 text-sm font-medium text-white focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed"
        :disabled="unavailable"
        @click="pickLocalMarkdown"
      >选择本地 Markdown</button>
      <button
        type="button"
        class="border-border hover:bg-hover focus-visible:outline-primary rounded-lg border px-5 py-2.5 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed"
        :disabled="unavailable"
        @click="fileInput?.click()"
      >{{ isDesktop ? '上传文件 / ZIP' : '选择文件' }}</button>
    </div>
    <p class="text-text-secondary mt-4 text-xs">
      Markdown 最大 {{ maxMarkdownBytes / 1024 / 1024 }}MB；ZIP 最大 50MB，且只能包含一个 Markdown
    </p>
    <input ref="fileInput" type="file" accept=".md,.markdown,.zip" class="hidden" :disabled="unavailable" @change="onFileChange" />
  </div>
</template>
