<script setup lang="ts">
import { computed, ref } from 'vue'
import { Marked } from 'marked'
import { markedHighlight } from 'marked-highlight'
import hljs from 'highlight.js'
import {
  convertEpub,
  downloadEpub,
  getEpubPreview,
} from '@/api/tools'
import type { EpubPreviewResponse } from '@/api/tools'

const markdown = new Marked(
  markedHighlight({
    emptyLangClass: 'hljs',
    langPrefix: 'hljs language-',
    highlight(code, lang) {
      const language = hljs.getLanguage(lang) ? lang : 'plaintext'
      return hljs.highlight(code, { language }).value
    },
  }),
  {
    renderer: {
      html: () => '',
      link: function ({ href, title, tokens }) {
        const safeHref = safeUrl(href)
        const text = this.parser.parseInline(tokens)
        const titleAttr = title ? ` title="${escapeAttribute(title)}"` : ''
        return `<a href="${escapeAttribute(safeHref)}"${titleAttr}>${text}</a>`
      },
      image: function ({ href, text }) {
        if (href.startsWith('images/')) {
          const imageName = href.slice('images/'.length)
          return `<div class="markdown-image-placeholder">图片资源请在下载 ZIP 后查看：images/${escapeHtml(imageName)}</div>`
        }
        return `<span class="markdown-image-placeholder">已隐藏不安全图片资源：${escapeHtml(text || href)}</span>`
      },
    },
  },
)

const MAX_FILE_SIZE = 50 * 1024 * 1024

type PageState = 'upload' | 'progress' | 'result' | 'error'
type ViewMode = 'split' | 'preview'

const currentState = ref<PageState>('upload')
const errorMessage = ref('')
const selectedFile = ref<File | null>(null)
const currentTaskId = ref('')
const preview = ref<EpubPreviewResponse | null>(null)
const editingMarkdown = ref('')
const progressValue = ref(0)
const progressStage = ref('正在处理 EPUB 文件...')
const viewMode = ref<ViewMode>('split')
const fileInput = ref<HTMLInputElement | null>(null)
const leftEditorRef = ref<HTMLTextAreaElement | null>(null)
const rightPreviewRef = ref<HTMLElement | null>(null)
let isSyncing = false
let lastSyncRatio = -1

const renderedMarkdown = computed(() => {
  if (!editingMarkdown.value) return ''
  const rendered = markdown.parse(editingMarkdown.value, { async: false })
  return rendered
})

function safeUrl(value: string): string {
  try {
    const url = new URL(value, window.location.origin)
    if (['http:', 'https:', 'mailto:'].includes(url.protocol)) return value
  } catch {
    // Invalid URLs are rendered as inert links.
  }
  return '#'
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char] || char)
}

function escapeAttribute(value: string): string {
  return escapeHtml(value)
}

function validateFile(file: File): string | null {
  if (!file.name.toLowerCase().endsWith('.epub')) return '仅支持 EPUB 格式'
  if (file.size > MAX_FILE_SIZE) return '文件大小不能超过 50MB'
  return null
}

function openFilePicker() {
  fileInput.value?.click()
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) void handleFile(file)
  input.value = ''
}

function onDragOver(event: DragEvent) {
  event.preventDefault()
}

function onDrop(event: DragEvent) {
  event.preventDefault()
  const file = event.dataTransfer?.files?.[0]
  if (file) void handleFile(file)
}

async function handleFile(file: File) {
  const validationError = validateFile(file)
  if (validationError) {
    errorMessage.value = validationError
    currentState.value = 'error'
    return
  }

  selectedFile.value = file
  preview.value = null
  currentTaskId.value = ''
  progressValue.value = 0
  progressStage.value = '正在处理 EPUB 文件...'
  currentState.value = 'progress'

  try {
    progressValue.value = 20
    const result = await convertEpub(file)
    currentTaskId.value = result.task_id
    progressValue.value = 80
    progressStage.value = '正在生成预览...'
    const data = await getEpubPreview(result.task_id)
    preview.value = data
    editingMarkdown.value = data.markdown_content
    progressValue.value = 100
    progressStage.value = '转换完成'
    currentState.value = 'result'
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '转换失败，请稍后重试'
    currentState.value = 'error'
  }
}

async function handleDownload() {
  if (!currentTaskId.value) return
  try {
    await downloadEpub(currentTaskId.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '下载失败'
    currentState.value = 'error'
  }
}

function syncScroll(source: HTMLElement, target: HTMLElement) {
  const ratio = source.scrollTop / Math.max(1, source.scrollHeight - source.clientHeight)
  if (Math.abs(ratio - lastSyncRatio) < 0.005) return
  lastSyncRatio = ratio
  target.scrollTop = ratio * Math.max(1, target.scrollHeight - target.clientHeight)
}

function onLeftScroll() {
  if (isSyncing || viewMode.value === 'preview') return
  isSyncing = true
  requestAnimationFrame(() => {
    if (leftEditorRef.value && rightPreviewRef.value) syncScroll(leftEditorRef.value, rightPreviewRef.value)
    isSyncing = false
  })
}

function onRightScroll() {
  if (isSyncing || viewMode.value === 'preview') return
  isSyncing = true
  requestAnimationFrame(() => {
    if (rightPreviewRef.value && leftEditorRef.value) syncScroll(rightPreviewRef.value, leftEditorRef.value)
    isSyncing = false
  })
}

function resetUpload() {
  currentState.value = 'upload'
  errorMessage.value = ''
  selectedFile.value = null
  currentTaskId.value = ''
  preview.value = null
  editingMarkdown.value = ''
  progressValue.value = 0
  progressStage.value = '正在处理 EPUB 文件...'
}
</script>

<template>
  <main class="mx-auto w-full py-7" :style="{ maxWidth: currentState === 'result' && viewMode === 'split' ? '1400px' : '860px' }">
    <section class="mb-5 rounded-2xl border border-border bg-surface p-8">
      <div class="mb-[18px] text-[13px] font-semibold uppercase tracking-[0.5px] text-text-secondary">
        <font-awesome-icon :icon="['far', 'file']" class="mr-1.5" />
        选择文件
      </div>
      <div v-if="currentState === 'upload' || currentState === 'error'">
        <div
          class="cursor-pointer rounded-xl border-2 border-dashed border-border py-11 text-center transition-all duration-250 hover:border-primary hover:bg-primary-light"
          role="button"
          tabindex="0"
          @click="openFilePicker"
          @keydown.enter.prevent="openFilePicker"
          @keydown.space.prevent="openFilePicker"
          @dragover="onDragOver"
          @drop="onDrop"
        >
          <div class="mb-3.5 text-[38px] text-text-tertiary"><font-awesome-icon :icon="['fas', 'book']" /></div>
          <h2 class="mb-1.5 text-[15px] font-semibold">将 EPUB 文件拖拽到此处</h2>
          <p class="mb-[18px] text-[13px] text-text-secondary">或点击下方按钮选择文件</p>
          <button
            type="button"
            class="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-primary px-[22px] py-[9px] font-inherit text-[13px] font-medium text-white transition-all duration-200 hover:bg-primary-dark"
            @click.stop="openFilePicker"
          >
            <font-awesome-icon :icon="['fas', 'upload']" />
            选择 EPUB 文件
          </button>
          <div class="mt-3.5 text-[12px] text-text-tertiary">支持 .epub 格式，最大 50MB</div>
        </div>
        <input ref="fileInput" type="file" accept=".epub,application/epub+zip" class="hidden" @change="onFileChange" />
      </div>
      <div v-if="currentState === 'progress' || currentState === 'result'" class="mt-[18px] flex items-center justify-center gap-3 rounded-lg bg-[#F9F9F6] px-5 py-3 text-[13px]">
        <font-awesome-icon :icon="['far', 'circle-check']" class="text-success" />
        <span class="font-medium">{{ selectedFile?.name }}</span>
        <span v-if="selectedFile" class="text-text-secondary">({{ (selectedFile.size / 1024 / 1024).toFixed(1) }} MB)</span>
      </div>
    </section>

    <section v-if="currentState === 'progress'" class="mb-5 rounded-2xl border border-border bg-surface p-8">
      <div class="mb-[18px] text-[13px] font-semibold uppercase tracking-[0.5px] text-text-secondary">
        <font-awesome-icon :icon="['far', 'hourglass-half']" class="mr-1.5" />正在处理
      </div>
      <div class="mb-3 flex items-center justify-between text-[12px] text-text-secondary"><span>{{ progressStage }}</span><span>{{ progressValue }}%</span></div>
      <div class="mb-5 h-1.5 w-full overflow-hidden rounded-full bg-[#F0F0EC]"><div class="h-full rounded-full bg-primary transition-all duration-500" :style="{ width: `${progressValue}%` }"></div></div>
      <div class="flex items-center gap-2.5 text-[13px] font-medium"><span class="w-5 text-center text-sm text-primary"><font-awesome-icon :icon="['fas', 'spinner']" spin /></span>{{ progressStage }}</div>
    </section>

    <section v-if="currentState === 'result' && preview" class="mb-5 rounded-2xl border border-border bg-surface p-8">
      <div class="mb-[18px] flex items-center justify-between">
        <div class="text-[13px] font-semibold uppercase tracking-[0.5px] text-text-secondary"><font-awesome-icon :icon="['far', 'file-lines']" class="mr-1.5" />转换结果</div>
        <div class="flex overflow-hidden rounded-lg border border-border text-[12px]"><button type="button" class="cursor-pointer px-3 py-1.5 font-inherit" :class="viewMode === 'split' ? 'bg-primary text-white' : 'bg-surface text-text-secondary hover:bg-hover'" @click="viewMode = 'split'">双栏</button><button type="button" class="cursor-pointer border-l border-border px-3 py-1.5 font-inherit" :class="viewMode === 'preview' ? 'bg-primary text-white' : 'bg-surface text-text-secondary hover:bg-hover'" @click="viewMode = 'preview'">预览</button></div>
      </div>
      <div class="mb-[18px] flex flex-wrap gap-2.5">
        <button type="button" class="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-primary px-[22px] py-[9px] font-inherit text-[13px] font-medium text-white transition-all duration-200 hover:bg-primary-dark" @click="handleDownload"><font-awesome-icon :icon="['fas', 'download']" />下载 ZIP</button>
        <button type="button" class="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-border bg-transparent px-[22px] py-[9px] font-inherit text-[13px] font-medium text-text-secondary transition-all duration-200 hover:border-[#999] hover:text-text" @click="resetUpload"><font-awesome-icon :icon="['fas', 'rotate']" />重新上传</button>
      </div>
      <div class="mb-3 flex items-center text-[12px] text-text-secondary"><span class="mr-4"><font-awesome-icon :icon="['far', 'file-lines']" class="mr-1" />{{ preview.chapter_count }} 个章节</span><span><font-awesome-icon :icon="['far', 'image']" class="mr-1" />{{ preview.image_count }} 张图片</span></div>
      <div class="flex overflow-hidden rounded-lg border border-border" aria-label="Markdown 预览">
        <div v-show="viewMode === 'split'" class="w-1/2 border-r border-border"><textarea ref="leftEditorRef" v-model="editingMarkdown" readonly aria-label="Markdown 原文" class="markdown-editor block h-[560px] w-full resize-none border-0 bg-[#F9F9F6] p-6 font-mono text-[14px] leading-relaxed text-text outline-none" spellcheck="false" @scroll="onLeftScroll"></textarea></div>
        <div ref="rightPreviewRef" class="markdown-preview h-[560px] overflow-y-auto" :class="viewMode === 'split' ? 'w-1/2' : 'w-full'" @scroll="onRightScroll"><div class="p-6"><div v-html="renderedMarkdown" class="max-w-none"></div></div></div>
      </div>
    </section>

    <section v-if="currentState === 'error'" class="mt-4 flex items-start gap-3 rounded-lg border border-[#FFD7D7] bg-[#FFF5F5] p-4 pl-5">
      <font-awesome-icon :icon="['far', 'circle-xmark']" class="mt-0.5 text-lg text-error" />
      <div class="flex-1"><h4 class="mb-1 text-[14px] font-semibold">转换失败</h4><p class="text-[13px] text-text-secondary">{{ errorMessage }}</p></div>
      <button type="button" class="cursor-pointer rounded-lg border border-border bg-transparent px-3 py-1.5 font-inherit text-xs text-text-secondary transition-all duration-200 hover:border-[#999] hover:text-text" @click="resetUpload">重新上传</button>
    </section>
    <footer class="mt-5 text-center text-[12px] text-text-tertiary"><font-awesome-icon :icon="['far', 'clock']" class="mr-1" />本地处理，文件不会上传</footer>
  </main>
</template>

<style>
.markdown-preview { background: var(--color-surface); color: var(--color-text); }
.markdown-preview h1, .markdown-preview h2, .markdown-preview h3, .markdown-preview h4 { margin-top: 20px; margin-bottom: 10px; font-weight: 650; line-height: 1.4; }
.markdown-preview h1 { margin-top: 0; font-size: 22px; border-bottom: 2px solid var(--color-primary-light); padding-bottom: 10px; }
.markdown-preview h2 { font-size: 19px; border-bottom: 1px solid var(--color-border); padding-bottom: 7px; }
.markdown-preview h3 { font-size: 16px; }
.markdown-preview p, .markdown-preview ul, .markdown-preview ol { margin-bottom: 14px; font-size: 14px; line-height: 1.8; }
.markdown-preview ul, .markdown-preview ol { padding-left: 22px; }
.markdown-preview ul { list-style: disc; }
.markdown-preview ol { list-style: decimal; }
.markdown-preview blockquote { margin-bottom: 16px; padding: 12px 18px; border-left: 4px solid var(--color-primary); background: var(--color-primary-light); }
.markdown-preview pre { margin-bottom: 16px; padding: 18px; overflow-x: auto; border-radius: 10px; background: #1e1e1e; }
.markdown-preview pre code { color: #d4d4d4; }
.markdown-preview code { border-radius: 5px; background: var(--color-hover); padding: 2px 7px; color: #c7254e; }
.markdown-preview img { max-width: 100%; height: auto; margin: 12px 0; border-radius: 8px; }
.markdown-image-placeholder { margin: 12px 0; padding: 10px 12px; border: 1px dashed var(--color-border); border-radius: 8px; color: var(--color-text-secondary); font-size: 13px; }
.markdown-preview a { color: var(--color-primary-dark); text-decoration: underline; }
.markdown-preview table { width: 100%; margin-bottom: 16px; border-collapse: collapse; font-size: 13px; }
.markdown-preview th, .markdown-preview td { border: 1px solid var(--color-border); padding: 8px 12px; text-align: left; }
.markdown-preview th { background: var(--color-hover); }
.markdown-preview hr { margin: 24px 0; border: none; border-top: 1px solid var(--color-border); }
.markdown-editor::-webkit-scrollbar, .markdown-preview::-webkit-scrollbar { width: 6px; }
.markdown-editor::-webkit-scrollbar-thumb, .markdown-preview::-webkit-scrollbar-thumb { border-radius: 3px; background: var(--color-border); }
</style>
