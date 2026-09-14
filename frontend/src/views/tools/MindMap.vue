<script setup lang="ts">
import { ref } from 'vue'
import { MindMap } from '@/features/mindmap/components'
import { parseXMindFile } from '@/features/mindmap/core'

type MindMapExportFormat = 'markdown' | 'xmind' | 'svg' | 'png'

const MAX_IMPORT_SIZE = 10 * 1024 * 1024
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
const errorMessage = ref('')
const fileName = ref('示例思维导图')
const fileInput = ref<HTMLInputElement | null>(null)
const mindMapRef = ref<InstanceType<typeof MindMap> | null>(null)
const exportingFormat = ref<MindMapExportFormat | null>(null)

function validateFile(file: File): string | null {
  const filename = file.name.toLowerCase()
  if (!filename.endsWith('.md') && !filename.endsWith('.markdown') && !filename.endsWith('.xmind')) {
    return '仅支持 .md、.markdown 或 .xmind 文件。'
  }
  if (file.size > MAX_IMPORT_SIZE) {
    return '思维导图文件不能超过 10MB。'
  }
  return null
}

function getImportSource(file: File): 'markdown' | 'xmind' {
  return file.name.toLowerCase().endsWith('.xmind') ? 'xmind' : 'markdown'
}

function importMarkdown(text: string): boolean {
  if (!text.trim()) {
    errorMessage.value = 'Markdown 文件不能为空。'
    return false
  }

  const mindMap = mindMapRef.value
  if (!mindMap) {
    errorMessage.value = '思维导图尚未准备好，请稍后重试。'
    return false
  }

  mindMap.importMarkdown(text)
  return true
}

async function openFile(file: File) {
  const validationError = validateFile(file)
  if (validationError) {
    errorMessage.value = validationError
    return
  }

  try {
    const source = getImportSource(file)
    if (source === 'xmind') {
      const mindMap = mindMapRef.value
      if (!mindMap) {
        errorMessage.value = '思维导图尚未准备好，请稍后重试。'
        return
      }
      mindMap.importData(await parseXMindFile(await file.arrayBuffer()))
    } else {
      if (!importMarkdown(await file.text())) return
    }
    fileName.value = file.name.replace(/\.(?:md|markdown|xmind)$/i, '') || '思维导图'
    errorMessage.value = ''
  } catch (error) {
    errorMessage.value = error instanceof Error && error.message
      ? error.message
      : '文件读取失败，请重新选择。'
  }
}

function openFilePicker() {
  fileInput.value?.click()
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

function handleReset() {
  fileName.value = '示例思维导图'
  errorMessage.value = ''
}

function getExportBaseName(): string {
  return fileName.value.replace(/[\\/:*?"<>|]/g, '_').trim() || '思维导图'
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

async function handleExport(format: MindMapExportFormat) {
  const mindMap = mindMapRef.value
  if (!mindMap || exportingFormat.value) return

  exportingFormat.value = format
  errorMessage.value = ''
  const baseName = getExportBaseName()

  try {
    if (format === 'markdown') {
      downloadBlob(
        new Blob([mindMap.getMarkdown()], { type: 'text/markdown;charset=utf-8' }),
        `${baseName}.md`,
      )
    } else if (format === 'xmind') {
      const xmind = await mindMap.exportToXMind()
      if (!xmind) throw new Error('XMind 导出不可用。')
      downloadBlob(xmind, `${baseName}.xmind`)
    } else if (format === 'svg') {
      const svg = await mindMap.exportToSVG()
      if (!svg) throw new Error('SVG 导出不可用。')
      downloadBlob(
        new Blob([svg], { type: 'image/svg+xml;charset=utf-8' }),
        `${baseName}.svg`,
      )
    } else {
      const png = await mindMap.exportToPNG()
      if (!png) throw new Error('PNG 导出不可用。')
      downloadBlob(png, `${baseName}.png`)
    }
  } catch (error) {
    errorMessage.value = error instanceof Error && error.message
      ? error.message
      : '导出失败，请稍后重试。'
  } finally {
    exportingFormat.value = null
  }
}
</script>

<template>
  <main
    class="flex h-full min-h-0 flex-col overflow-hidden bg-bg"
    @dragover.prevent
    @drop.prevent="handleDrop"
  >
    <div v-if="errorMessage" class="flex shrink-0 items-center justify-between gap-3 border-b border-[#f1c4c4] bg-[#fff4f4] px-4 py-2 text-xs text-[#b42318]" role="alert">
      <span>{{ errorMessage }}</span>
      <button type="button" class="shrink-0 underline" @click="errorMessage = ''">关闭</button>
    </div>

    <input
      ref="fileInput"
      type="file"
      accept=".md,.markdown,.xmind,text/markdown,application/xmind,application/zip"
      class="hidden"
      @change="handleFileChange"
    />

    <div class="min-h-0 flex-1 overflow-hidden bg-bg">
      <MindMap
        ref="mindMapRef"
        theme="light"
        v-model:markdown="markdown"
        @import-request="openFilePicker"
        @export-request="handleExport"
        @reset="handleReset"
      />
    </div>
  </main>
</template>
