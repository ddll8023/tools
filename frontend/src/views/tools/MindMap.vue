<script setup lang="ts">
import { ref } from 'vue'
import { MindMap } from '@/features/mindmap/components'

const MAX_MARKDOWN_SIZE = 10 * 1024 * 1024
const DEFAULT_MARKDOWN = `思维导图
- 从 Markdown 开始
  - 编写大纲
  - 查看地图更新
- 梳理结构
  - 每级使用两个空格
  - 添加 **粗体** 或 #标签
- 导出结果
  - SVG 在任意尺寸都清晰
  - PNG 支持本地下载`

const markdown = ref(DEFAULT_MARKDOWN)
const fileName = ref('示例思维导图')
const errorMessage = ref('')
const fileInput = ref<HTMLInputElement | null>(null)

function openFilePicker() {
  fileInput.value?.click()
}

function validateFile(file: File): string | null {
  const filename = file.name.toLowerCase()
  if (!filename.endsWith('.md') && !filename.endsWith('.markdown')) {
    return '仅支持 .md 或 .markdown 文件。'
  }
  if (file.size > MAX_MARKDOWN_SIZE) {
    return 'Markdown 文件不能超过 10MB。'
  }
  return null
}

async function openFile(file: File) {
  const validationError = validateFile(file)
  if (validationError) {
    errorMessage.value = validationError
    return
  }

  try {
    const text = await file.text()
    if (!text.trim()) {
      errorMessage.value = 'Markdown 文件不能为空。'
      return
    }
    markdown.value = text
    fileName.value = file.name.replace(/\.(markdown?|md)$/i, '') || '思维导图'
    errorMessage.value = ''
  } catch {
    errorMessage.value = '文件读取失败，请重新选择。'
  }
}

function handleFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (file) void openFile(file)
}

function handleDrop(event: DragEvent) {
  const file = event.dataTransfer?.files?.[0]
  if (file) void openFile(file)
}

function resetExample() {
  markdown.value = DEFAULT_MARKDOWN
  fileName.value = '示例思维导图'
  errorMessage.value = ''
}
</script>

<template>
  <main
    class="flex h-full min-h-0 flex-col overflow-hidden bg-[#f7f7f5]"
    @dragover.prevent
    @drop.prevent="handleDrop"
  >
    <header class="flex min-h-14 shrink-0 items-center justify-between gap-4 border-b border-[#e8e8e3] bg-white px-4 py-2">
      <div class="min-w-0">
        <h1 class="truncate text-sm font-semibold text-[#2f2f2f]">{{ fileName }}</h1>
        <p class="text-xs text-[#999]">Markdown 在本地解析，内容不会上传。</p>
      </div>
      <div class="flex shrink-0 items-center gap-2">
        <input
          ref="fileInput"
          type="file"
          accept=".md,.markdown,text/markdown"
          class="hidden"
          @change="handleFileChange"
        />
        <button
          type="button"
          class="rounded-md border border-[#deded8] bg-white px-3 py-1.5 text-xs text-[#555] transition hover:border-[#d99a2b] hover:text-[#b4770d]"
          @click="openFilePicker"
        >
          打开 Markdown
        </button>
        <button
          type="button"
          class="rounded-md border border-[#deded8] bg-white px-3 py-1.5 text-xs text-[#555] transition hover:border-[#d99a2b] hover:text-[#b4770d]"
          @click="resetExample"
        >
          重置示例
        </button>
      </div>
    </header>

    <div v-if="errorMessage" class="flex shrink-0 items-center justify-between gap-3 border-b border-[#f1c4c4] bg-[#fff4f4] px-4 py-2 text-xs text-[#b42318]" role="alert">
      <span>{{ errorMessage }}</span>
      <button type="button" class="shrink-0 underline" @click="errorMessage = ''">关闭</button>
    </div>

    <div class="min-h-0 flex-1 overflow-hidden">
      <MindMap v-model:markdown="markdown" />
    </div>
  </main>
</template>
