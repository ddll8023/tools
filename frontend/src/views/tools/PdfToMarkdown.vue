/**
 * PDF 转 Markdown 工具页
 * 功能描述：上传 PDF → 转换 → 预览 → 下载，支持标准/深度双引擎
 * 依赖组件：无
 */
<script setup lang="ts">
import { ref, computed } from 'vue'
import { Marked } from 'marked'
import { markedHighlight } from 'marked-highlight'
import hljs from 'highlight.js'
import { convertPdf, getPreview, getProgress, downloadMd } from '@/api/tools'
import type { PreviewResponse } from '@/api/tools'

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
      // 禁止原始 HTML，防止 PDF 内容或编辑内容注入脚本
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
          return `<div class="markdown-image-placeholder">图片资源未嵌入预览：images/${escapeHtml(imageName)}</div>`
        }
        return `<span class="markdown-image-placeholder">已隐藏不安全图片资源：${escapeHtml(text || href)}</span>`
      },
    },
  },
)

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

const MAX_FILE_SIZE = 50 * 1024 * 1024
const POLL_INTERVAL = 1500

type PageState = 'upload' | 'progress' | 'result' | 'error'
type ViewMode = 'split' | 'preview'

const currentState = ref<PageState>('upload')
const errorMessage = ref('')
const preview = ref<PreviewResponse | null>(null)
const selectedFile = ref<File | null>(null)
const currentTaskId = ref('')
const deepParse = ref(false)
const progressValue = ref(0)
const progressStage = ref('')

/* ── 双栏编辑相关 ── */
const viewMode = ref<ViewMode>('split')
const editingMarkdown = ref('')
const downloadWarning = ref('')

/* ── 元素引用 ── */
const leftEditorRef = ref<HTMLTextAreaElement | null>(null)
const rightPreviewRef = ref<HTMLElement | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)

function openFilePicker() {
  fileInput.value?.click()
}

/* 双栏模式下容器宽度自适应：宽屏 1400px，单栏/其他保持 860px */
const isWideMode = computed(() => currentState.value === 'result' && viewMode.value === 'split')

/*
 * renderedMarkdown 计算属性
 * 依赖 editingMarkdown，编辑时实时重渲染
 */
const renderedMarkdown = computed(() => {
  if (!editingMarkdown.value) return ''
  return markdown.parse(editingMarkdown.value, { async: false })
})

/* ════════════════════════════════════════
   同步滚动 — 连续比例跟随
   ════════════════════════════════════════ */

let isSyncing = false
let lastSyncRatio = -1

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
    const left = leftEditorRef.value
    const right = rightPreviewRef.value
    if (left && right) syncScroll(left, right)
    isSyncing = false
  })
}

function onRightScroll() {
  if (isSyncing || viewMode.value === 'preview') return
  isSyncing = true
  requestAnimationFrame(() => {
    const left = leftEditorRef.value
    const right = rightPreviewRef.value
    if (left && right) syncScroll(right, left)
    isSyncing = false
  })
}

function validateFile(file: File): string | null {
  if (!file.name.toLowerCase().endsWith('.pdf')) {
    return '仅支持 PDF 格式'
  }
  if (file.size > MAX_FILE_SIZE) {
    return '文件大小不能超过 50MB'
  }
  return null
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  handleFile(file)
  input.value = ''
}

function onDrop(event: DragEvent) {
  event.preventDefault()
  const file = event.dataTransfer?.files?.[0]
  if (!file) return
  handleFile(file)
}

function onDragOver(event: DragEvent) {
  event.preventDefault()
}

async function handleFile(file: File) {
  const err = validateFile(file)
  if (err) {
    errorMessage.value = err
    currentState.value = 'error'
    return
  }

  selectedFile.value = file
  currentState.value = 'progress'

  try {
    const result = await convertPdf(file, deepParse.value)

    if (deepParse.value) {
      currentTaskId.value = result.task_id
      const ok = await pollProgress(result.task_id)
      // 轮询已失败时保留真实错误文案，不再调用 preview 覆盖为"转换结果不存在"
      if (!ok) return
      const data = await getPreview(result.task_id)
      preview.value = data
      editingMarkdown.value = data.markdown_content
      currentState.value = 'result'
    } else {
      currentTaskId.value = result.task_id
      const data = await getPreview(result.task_id)
      preview.value = data
      editingMarkdown.value = data.markdown_content
      currentState.value = 'result'
    }
  } catch (e: any) {
    errorMessage.value = e.message || '转换失败，请稍后重试'
    currentState.value = 'error'
  }
}

/** 轮询深度解析进度；返回 false 表示解析失败，调用方应终止后续流程 */
async function pollProgress(taskId: string): Promise<boolean> {
  while (true) {
    try {
      const p = await getProgress(taskId)
      progressValue.value = p.progress
      progressStage.value = p.stage

      if (p.progress < 0) {
        errorMessage.value = p.stage || '深度解析失败'
        currentState.value = 'error'
        return false
      }
      if (p.progress >= 100) return true
    } catch (e: any) {
      errorMessage.value = e.message || '深度解析失败'
      currentState.value = 'error'
      return false
    }
    await new Promise(r => setTimeout(r, POLL_INTERVAL))
  }
}

/**
 * 下载转换结果：以当前编辑内容为准；
 * 存在图片资源时后端返回 ZIP 包（Markdown + images/），否则返回单个 .md；
 * 转换结果中本就缺失的图片会通过提示告知用户。
 */
async function handleDownload() {
  if (!currentTaskId.value || !editingMarkdown.value) return
  downloadWarning.value = ''
  try {
    const { missingTotal } = await downloadMd(currentTaskId.value, editingMarkdown.value)
    if (missingTotal > 0) {
      downloadWarning.value = `有 ${missingTotal} 个图片资源在转换结果中缺失，未包含在下载文件里`
    }
  } catch (e: any) {
    errorMessage.value = e.message || '下载失败'
    currentState.value = 'error'
  }
}

function resetUpload() {
  currentState.value = 'upload'
  errorMessage.value = ''
  preview.value = null
  selectedFile.value = null
  currentTaskId.value = ''
  deepParse.value = false
  progressValue.value = 0
  progressStage.value = ''
  editingMarkdown.value = ''
  downloadWarning.value = ''
}
</script>

<template>
  <main class="mx-auto w-full py-7" :style="{ maxWidth: isWideMode ? '1400px' : '860px' }">
    <section class="mb-5 rounded-2xl border border-border bg-surface p-8">
      <div class="mb-[18px] text-[13px] font-semibold uppercase tracking-[0.5px] text-text-secondary">
        <font-awesome-icon :icon="['far', 'file']" class="mr-1.5" />
        选择文件
      </div>

      <div v-if="currentState === 'upload' || currentState === 'error'">
        <div
          class="cursor-pointer rounded-xl border-2 border-dashed border-border py-11 text-center transition-all duration-250 hover:border-primary hover:bg-primary-light"
          @dragover="onDragOver" @drop="onDrop"
        >
          <div class="mb-3.5 text-[38px] text-text-tertiary">
            <font-awesome-icon :icon="['fas', 'file-pdf']" />
          </div>
          <h2 class="mb-1.5 text-[15px] font-semibold">将 PDF 文件拖拽到此处</h2>
          <p class="mb-[18px] text-[13px] text-text-secondary">或点击下方按钮选择文件</p>
          <button
            class="inline-flex items-center gap-2 rounded-lg bg-primary px-[22px] py-[9px] font-inherit text-[13px] font-medium text-white cursor-pointer transition-all duration-200 hover:bg-primary-dark"
            @click="openFilePicker"
          >
            <font-awesome-icon :icon="['fas', 'upload']" />
            选择 PDF 文件
          </button>
          <div class="mt-3.5 text-[12px] text-text-tertiary">支持 .pdf 格式，最大 50MB</div>
        </div>

        <label class="mt-4 flex cursor-pointer items-center gap-2.5 text-[13px] text-text-secondary hover:text-text">
          <input v-model="deepParse" type="checkbox" class="h-4 w-4 cursor-pointer accent-primary" />
          <span>深度解析（适用于复杂排版、扫描件或多栏布局）</span>
        </label>

        <input ref="fileInput" type="file" accept=".pdf" class="hidden" @change="onFileChange" />
      </div>

      <div
        v-if="currentState === 'progress' || currentState === 'result'"
        class="mt-[18px] flex items-center justify-center gap-3 rounded-lg bg-[#F9F9F6] px-5 py-3 text-[13px]"
      >
        <font-awesome-icon :icon="['far', 'circle-check']" class="text-success" />
        <span class="font-medium">{{ selectedFile?.name }}</span>
        <span v-if="selectedFile" class="text-text-secondary">({{ (selectedFile.size / 1024 / 1024).toFixed(1) }} MB)</span>
      </div>
    </section>

    <!-- 进度 -->
    <section v-if="currentState === 'progress'" class="mb-5 rounded-2xl border border-border bg-surface p-8">
      <div class="mb-[18px] text-[13px] font-semibold uppercase tracking-[0.5px] text-text-secondary">
        <font-awesome-icon :icon="['far', 'hourglass-half']" class="mr-1.5" />
        正在处理
      </div>

      <template v-if="!deepParse">
        <div class="mb-5 h-1.5 w-full overflow-hidden rounded-full bg-[#F0F0EC]">
          <div class="h-full w-full animate-pulse rounded-full bg-primary transition-all duration-400"></div>
        </div>
        <div class="flex items-center gap-2.5 text-[13px] font-medium">
          <span class="w-5 text-center text-sm text-primary">
            <font-awesome-icon :icon="['fas', 'spinner']" spin />
          </span>
          正在解析 PDF 文件...
        </div>
      </template>

      <template v-else>
        <div class="mb-3 flex items-center justify-between text-[12px] text-text-secondary">
          <span>{{ progressStage }}</span>
          <span>{{ progressValue }}%</span>
        </div>
        <div class="mb-5 h-1.5 w-full overflow-hidden rounded-full bg-[#F0F0EC]">
          <div
            class="h-full rounded-full bg-primary transition-all duration-500"
            :style="{ width: progressValue + '%' }"
          ></div>
        </div>
        <div class="flex items-center gap-2.5 text-[13px] font-medium">
          <span class="w-5 text-center text-sm text-primary">
            <font-awesome-icon :icon="['fas', 'spinner']" spin />
          </span>
          {{ progressStage }}
        </div>
      </template>
    </section>

    <!-- 结果 -->
    <section v-if="currentState === 'result' && preview" class="mb-5 rounded-2xl border border-border bg-surface p-8">
      <div class="mb-[18px] flex items-center justify-between">
        <div class="text-[13px] font-semibold uppercase tracking-[0.5px] text-text-secondary">
          <font-awesome-icon :icon="['far', 'file-lines']" class="mr-1.5" />
          转换结果
        </div>
        <!-- 双栏/单栏切换 -->
        <div class="flex overflow-hidden rounded-lg border border-border text-[12px]">
          <button
            class="cursor-pointer px-3 py-1.5 font-inherit transition-all"
            :class="viewMode === 'split' ? 'bg-primary text-white' : 'bg-surface text-text-secondary hover:bg-hover'"
            @click="viewMode = 'split'"
          >双栏</button>
          <button
            class="cursor-pointer border-l border-border px-3 py-1.5 font-inherit transition-all"
            :class="viewMode === 'preview' ? 'bg-primary text-white' : 'bg-surface text-text-secondary hover:bg-hover'"
            @click="viewMode = 'preview'"
          >预览</button>
        </div>
      </div>

      <div class="mb-[18px] flex flex-wrap gap-2.5">
        <button
          class="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-primary px-[22px] py-[9px] font-inherit text-[13px] font-medium text-white transition-all duration-200 hover:bg-primary-dark"
          @click="handleDownload"
        >
          <font-awesome-icon :icon="['fas', 'download']" />
          {{ preview.image_count > 0 ? '下载（ZIP 含图片）' : '下载 .md' }}
        </button>
        <button
          class="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-border bg-transparent px-[22px] py-[9px] font-inherit text-[13px] font-medium text-text-secondary transition-all duration-200 hover:border-[#999] hover:text-text"
          @click="resetUpload"
        >
          <font-awesome-icon :icon="['fas', 'rotate']" />
          重新上传
        </button>
      </div>

      <div class="mb-3 flex items-center justify-between text-[12px] text-text-secondary">
        <div>
          <span class="mr-4"><font-awesome-icon :icon="['far', 'file']" class="mr-1" />{{ preview.page_count }} 页</span>
          <span class="mr-4"><font-awesome-icon :icon="['fas', 'table']" class="mr-1" />{{ preview.table_count }} 个表格</span>
          <span><font-awesome-icon :icon="['far', 'image']" class="mr-1" />{{ preview.image_count }} 张图片</span>
        </div>
      </div>

      <!-- 下载提示：转换结果中缺失的图片资源 -->
      <div
        v-if="downloadWarning"
        class="mb-3 flex items-start gap-2 rounded-lg border border-[#F2E3C9] bg-[#FFF9EF] px-4 py-2.5 text-[12px] text-[#8A6D3B]"
      >
        <font-awesome-icon :icon="['fas', 'triangle-exclamation']" class="mt-0.5" />
        <span>{{ downloadWarning }}</span>
      </div>

      <!-- 双栏预览容器 -->
      <div class="flex overflow-hidden rounded-lg border border-border">
        <!-- 左栏：Markdown 原文编辑 -->
        <div
          v-show="viewMode === 'split'"
          class="w-1/2 border-r border-border"
        >
          <textarea
            ref="leftEditorRef"
            v-model="editingMarkdown"
            class="markdown-editor block h-[560px] w-full resize-none border-0 bg-[#F9F9F6] p-6 font-mono text-[14px] leading-relaxed text-text outline-none"
            @scroll="onLeftScroll"
            spellcheck="false"
          ></textarea>
        </div>
        <!-- 右栏：渲染预览 -->
        <div
          ref="rightPreviewRef"
          class="markdown-preview h-[560px] overflow-y-auto"
          :class="viewMode === 'split' ? 'w-1/2' : 'w-full'"
          @scroll="onRightScroll"
        >
          <div class="p-6">
            <div v-html="renderedMarkdown" class="max-w-none"></div>
          </div>
        </div>
      </div>
    </section>

    <!-- 错误 -->
    <section v-if="currentState === 'error'" class="mt-4 flex items-start gap-3 rounded-lg border border-[#FFD7D7] bg-[#FFF5F5] p-4 pl-5">
      <font-awesome-icon :icon="['far', 'circle-xmark']" class="mt-0.5 text-lg text-error" />
      <div class="flex-1">
        <h4 class="mb-1 text-[14px] font-semibold">转换失败</h4>
        <p class="text-[13px] text-text-secondary">{{ errorMessage }}</p>
      </div>
      <button
        class="cursor-pointer rounded-lg border border-border bg-transparent px-3 py-1.5 font-inherit text-xs text-text-secondary transition-all duration-200 hover:border-[#999] hover:text-text"
        @click="resetUpload"
      >
        重新上传
      </button>
    </section>

    <footer class="mt-5 text-center text-[12px] text-text-tertiary">
      <font-awesome-icon :icon="['far', 'clock']" class="mr-1" />
      本地处理，文件不会上传
    </footer>
  </main>
</template>

<style>
/* highlight.js github-dark 主题 */
@import 'highlight.js/styles/github-dark.css';

/* ════════════════════════════════════════
   Markdown 预览样式（全局，作用于 v-html 内容）
   风格：浅色页面 + 深色代码块 + 品牌暖色点缀
   ════════════════════════════════════════ */

/* ── 标题系统 ── */
.markdown-preview h1 {
  margin-bottom: 16px;
  font-size: 22px;
  font-weight: 700;
  line-height: 1.3;
  color: var(--color-text);
  border-bottom: 2px solid var(--color-primary-light);
  padding-bottom: 10px;
}
.markdown-preview h2 {
  margin-top: 30px;
  margin-bottom: 12px;
  font-size: 19px;
  font-weight: 650;
  line-height: 1.35;
  color: var(--color-text);
  border-bottom: 1px solid var(--color-border);
  padding-bottom: 7px;
}
.markdown-preview h3 {
  margin-top: 24px;
  margin-bottom: 10px;
  font-size: 16px;
  font-weight: 600;
  line-height: 1.4;
  color: var(--color-text);
}
.markdown-preview h4 {
  margin-top: 20px;
  margin-bottom: 8px;
  font-size: 14px;
  font-weight: 600;
  line-height: 1.4;
  color: var(--color-text-secondary);
}

/* ── 正文 ── */
.markdown-preview p {
  margin-bottom: 14px;
  font-size: 14px;
  line-height: 1.8;
  color: var(--color-text);
}

/* ── 列表 ── */
.markdown-preview ul,
.markdown-preview ol {
  margin-bottom: 14px;
  padding-left: 22px;
  font-size: 14px;
  line-height: 1.8;
  color: var(--color-text);
}
.markdown-preview ul {
  list-style-type: disc;
}
.markdown-preview ul ul {
  list-style-type: circle;
}
.markdown-preview ol {
  list-style-type: decimal;
}
.markdown-preview li {
  margin-bottom: 3px;
}
.markdown-preview li > ul,
.markdown-preview li > ol {
  margin-bottom: 0;
}

/* ── 行内代码 ── */
.markdown-preview code {
  padding: 2px 7px;
  font-family: 'JetBrains Mono', 'Cascadia Code', 'Consolas', monospace;
  font-size: 12.5px;
  background-color: var(--color-hover);
  border: 1px solid #E8E8E4;
  border-radius: 5px;
  color: #C7254E;
}

/* ── 代码块（深色主题 + 阴影） ── */
.markdown-preview pre {
  margin-bottom: 16px;
  padding: 18px;
  overflow-x: auto;
  background-color: #1E1E1E;
  border: 1px solid #333;
  border-radius: 10px;
  line-height: 1.6;
  box-shadow: 0 2px 8px rgba(0,0,0,0.10);
}
.markdown-preview pre code {
  padding: 0;
  font-family: 'JetBrains Mono', 'Cascadia Code', 'Consolas', monospace;
  font-size: 12.5px;
  background: none;
  border: none;
  border-radius: 0;
  color: #D4D4D4;
}

/* ── 引用块 ── */
.markdown-preview blockquote {
  margin-bottom: 16px;
  padding: 16px 20px;
  border-left: 4px solid var(--color-primary);
  background: linear-gradient(to right, var(--color-primary-light) 0%, #FEFCF8 100%);
  border-radius: 0 10px 10px 0;
  font-size: 14px;
  line-height: 1.75;
  color: var(--color-text);
  box-shadow: 0 1px 4px rgba(0,0,0,0.04);
}
.markdown-preview blockquote p {
  margin-bottom: 0;
}
.markdown-preview blockquote p + p {
  margin-top: 10px;
}

/* ── 表格 ── */
.markdown-preview table {
  margin-bottom: 16px;
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-size: 13px;
  line-height: 1.6;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  overflow: hidden;
}
.markdown-preview th,
.markdown-preview td {
  padding: 10px 14px;
  border-bottom: 1px solid var(--color-border);
  border-right: 1px solid var(--color-border);
  text-align: left;
}
.markdown-preview th:last-child,
.markdown-preview td:last-child {
  border-right: none;
}
.markdown-preview tr:last-child td {
  border-bottom: none;
}
.markdown-preview th {
  background-color: var(--color-hover);
  font-weight: 600;
  color: var(--color-text);
}
.markdown-preview td {
  color: var(--color-text);
}
.markdown-preview tr:nth-child(even) td {
  background-color: var(--color-bg);
}
.markdown-preview tr:hover td {
  background-color: var(--color-primary-light);
}

/* ── 分割线 ── */
.markdown-preview hr {
  margin: 24px 0;
  border: none;
  height: 1px;
  background: linear-gradient(to right, transparent, var(--color-border), transparent);
}

/* ── 链接 ── */
.markdown-preview a {
  color: var(--color-primary-dark);
  text-decoration: underline;
  text-decoration-color: var(--color-primary-light);
  text-underline-offset: 3px;
  text-decoration-thickness: 1.5px;
  transition: all 0.2s;
}
.markdown-preview a:hover {
  text-decoration-color: var(--color-primary);
}

/* ── 粗体/斜体 ── */
.markdown-preview strong {
  font-weight: 650;
}
.markdown-preview em {
  font-style: italic;
}

/* ── 图片占位符（图片资源不在预览中内嵌展示） ── */
.markdown-preview img {
  max-width: 100%;
  height: auto;
  border-radius: 8px;
  margin: 12px 0;
  border: 1px solid var(--color-border);
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}

.markdown-image-placeholder {
  margin: 12px 0;
  padding: 10px 12px;
  border: 1px dashed var(--color-border);
  border-radius: 8px;
  color: var(--color-text-secondary);
  font-size: 13px;
}

/* ── 首尾元素间距清除 ── */
.markdown-preview > :first-child {
  margin-top: 0;
}
.markdown-preview > :last-child {
  margin-bottom: 0;
}

/* ── 预览容器自定义滚动条 ── */
.markdown-preview::-webkit-scrollbar {
  width: 6px;
}
.markdown-preview::-webkit-scrollbar-track {
  background: transparent;
}
.markdown-preview::-webkit-scrollbar-thumb {
  background: var(--color-border);
  border-radius: 3px;
}
.markdown-preview::-webkit-scrollbar-thumb:hover {
  background: var(--color-text-tertiary);
}

/* ════════════════════════════════════════
   Markdown 编辑区样式
   ════════════════════════════════════════ */

/* ── 编辑区默认滚动条 ── */
.markdown-editor::-webkit-scrollbar {
  width: 6px;
}
.markdown-editor::-webkit-scrollbar-track {
  background: transparent;
}
.markdown-editor::-webkit-scrollbar-thumb {
  background: var(--color-border);
  border-radius: 3px;
}
.markdown-editor::-webkit-scrollbar-thumb:hover {
  background: var(--color-text-tertiary);
}

/* ── 编辑区占位符 ── */
.markdown-editor::placeholder {
  color: var(--color-text-tertiary);
}

/* ── 编辑区选中文本 ── */
.markdown-editor::selection {
  background: var(--color-primary-light);
}
</style>
