<!-- Markdown 转 PDF：前端离线渲染公式与 SVG，再由桌面端打印为 PDF。 -->
<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import { BaseSelect } from '@/components/common'
import MarkdownSourcePicker from '@/features/markdown/components/MarkdownSourcePicker.vue'
import type { MarkdownSource } from '@/features/markdown/source'
import { buildPdfHtml, renderMarkdown } from '@/features/markdown-pdf/render'
import { prepareMarkdownSource } from '@/features/markdown-pdf/prepare'
import type { PdfDocument, PdfOptions } from '@/features/markdown-pdf/types'

type Phase = 'idle' | 'ready' | 'progress' | 'preview' | 'error'
const phase = ref<Phase>('idle')
const source = ref<MarkdownSource | null>(null)
const renderedDoc = ref<PdfDocument | null>(null)
const warnings = ref<string[]>([])
const error = ref('')
const notice = ref('')
const exporting = ref(false)
const options = reactive<PdfOptions>({
  landscape: false,
  marginMm: 18,
  fontSize: 11,
  pageNumbers: true,
})
const isDesktop = computed(() => Boolean(window.desktopApi?.markdownPdf))
const direction = computed({
  get: () => options.landscape ? 'landscape' : 'portrait',
  set: (value: string) => { options.landscape = value === 'landscape' },
})
const fontSize = computed({
  get: () => String(options.fontSize),
  set: (value: string) => { options.fontSize = Number(value) },
})
const directionOptions = [
  { value: 'portrait', label: '纵向' },
  { value: 'landscape', label: '横向' },
]
const fontOptions = [9, 10, 11, 12, 14, 16].map((size) => ({
  value: String(size),
  label: `${size} pt`,
}))
const validOptions = computed(() => (
  Number.isInteger(options.marginMm) && options.marginMm >= 10 && options.marginMm <= 30
  && Number.isInteger(options.fontSize) && options.fontSize >= 8 && options.fontSize <= 20
))
const busy = computed(() => phase.value === 'progress' || exporting.value)
// 预览与打印共用同一份 HTML，改动排版参数即可看到与导出结果一致的效果。
const previewSrcdoc = computed(() => (
  renderedDoc.value ? buildPdfHtml(renderedDoc.value.previewHtml, options) : ''
))
let controller: AbortController | null = null
let requestVersion = 0
let requestId = ''

function handleSource(value: MarkdownSource) {
  source.value = value
  renderedDoc.value = null
  warnings.value = []
  error.value = ''
  notice.value = ''
  phase.value = 'ready'
}

function handleSourceError(message: string) {
  error.value = message
  phase.value = 'error'
}

async function convert() {
  const selected = source.value
  if (!selected || busy.value || !validOptions.value) return
  controller?.abort()
  const currentController = new AbortController()
  controller = currentController
  const version = ++requestVersion
  renderedDoc.value = null
  warnings.value = []
  error.value = ''
  notice.value = ''
  phase.value = 'progress'
  try {
    const prepared = await prepareMarkdownSource(selected)
    const rendered = await renderMarkdown(prepared, currentController.signal)
    if (version !== requestVersion) return
    renderedDoc.value = rendered
    warnings.value = [...prepared.warnings, ...rendered.warnings]
    phase.value = 'preview'
  } catch (cause: unknown) {
    if (version !== requestVersion || currentController.signal.aborted) return
    error.value = cause instanceof Error ? cause.message : '文档渲染失败，请稍后重试'
    phase.value = 'error'
  } finally {
    if (version === requestVersion) controller = null
  }
}

/** 调用桌面端打印通道；用户取消保存不算失败。 */
async function exportPdf() {
  const rendered = renderedDoc.value
  const selected = source.value
  const api = window.desktopApi?.markdownPdf
  if (!rendered || !selected || !api || busy.value) return
  exporting.value = true
  error.value = ''
  notice.value = ''
  requestId = crypto.randomUUID()
  try {
    const result = await api.export({
      requestId,
      filename: selected.name,
      html: buildPdfHtml(rendered.html, options),
      options: { ...options },
    })
    if (result.status === 'saved') notice.value = `已保存：${result.filename}`
    else if (result.status === 'cancelled') notice.value = '已取消保存'
    else error.value = result.message
  } catch {
    error.value = 'PDF 导出失败，请检查目标目录权限后重试'
  } finally {
    exporting.value = false
    requestId = ''
  }
}

async function cancelExport() {
  const api = window.desktopApi?.markdownPdf
  if (!api || !requestId) return
  try {
    await api.cancel(requestId)
  } catch {
    error.value = '取消导出失败，请重试'
  }
}

function reset() {
  requestVersion++
  controller?.abort()
  controller = null
  if (requestId) void cancelExport()
  source.value = null
  renderedDoc.value = null
  warnings.value = []
  error.value = ''
  notice.value = ''
  phase.value = 'idle'
}

onBeforeUnmount(() => {
  requestVersion++
  controller?.abort()
  if (requestId) void cancelExport()
})
</script>

<template>
  <main class="mx-auto w-full max-w-[900px] space-y-5 py-7" :aria-busy="busy">
    <section class="border-border bg-surface rounded-2xl border p-6">
      <MarkdownSourcePicker
        v-if="!source"
        :disabled="busy"
        @select="handleSource"
        @error="handleSourceError"
      />
      <div v-else class="flex flex-wrap items-center justify-between gap-4">
        <div class="min-w-0">
          <p class="font-medium break-all">{{ source.name }}</p>
          <p class="text-text-secondary mt-1 text-sm">
            {{ source.kind === 'local' ? '本地文件及目录内图片' : '上传 Markdown 与资源 ZIP' }}
          </p>
        </div>
        <button
          type="button"
          class="border-border hover:bg-hover focus-visible:outline-primary rounded-lg border px-4 py-2 text-sm focus-visible:outline-2 disabled:opacity-50"
          :disabled="busy"
          @click="reset"
        >更换文件</button>
      </div>
    </section>

    <section v-if="source" class="border-border bg-surface rounded-2xl border p-6">
      <h2 class="mb-4 font-semibold">PDF 排版设置</h2>
      <fieldset class="grid gap-5 sm:grid-cols-2 lg:grid-cols-4" :disabled="busy">
        <div>
          <label for="pdf-direction" class="mb-2 block text-sm">纸张方向 · A4</label>
          <BaseSelect id="pdf-direction" v-model="direction" :options="directionOptions" block />
        </div>
        <div>
          <label for="pdf-font" class="mb-2 block text-sm">正文字号</label>
          <BaseSelect id="pdf-font" v-model="fontSize" :options="fontOptions" block />
        </div>
        <div>
          <label for="pdf-margin" class="mb-2 block text-sm">四周页边距（mm）</label>
          <input
            id="pdf-margin"
            v-model.number="options.marginMm"
            type="number"
            min="10"
            max="30"
            step="1"
            :aria-invalid="!validOptions"
            class="border-border focus-visible:outline-primary w-full rounded-lg border px-3 py-2 text-sm focus-visible:outline-2"
          />
          <p class="text-text-secondary mt-1 text-xs">10–30 mm，整数</p>
        </div>
        <label class="flex items-center gap-2 self-center text-sm">
          <input v-model="options.pageNumbers" type="checkbox" class="accent-primary" />
          显示页码 / 总页数
        </label>
      </fieldset>
      <p class="text-text-secondary mt-4 text-xs">
        公式与 SVG 由应用内置的 MathJax 矢量渲染，图片按 Markdown 所在目录与 Obsidian 库根解析。
      </p>
      <div class="mt-5 flex flex-wrap gap-3">
        <button
          v-if="phase === 'ready' || phase === 'error'"
          type="button"
          class="bg-primary hover:bg-primary-dark focus-visible:outline-primary rounded-lg px-5 py-2.5 text-sm font-medium text-white focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-50"
          :disabled="!validOptions"
          @click="convert"
        >
          <font-awesome-icon :icon="['fas', 'file-pdf']" class="mr-1.5" aria-hidden="true" />
          生成预览
        </button>
        <button
          v-if="phase === 'preview'"
          type="button"
          class="bg-primary hover:bg-primary-dark focus-visible:outline-primary rounded-lg px-5 py-2.5 text-sm font-medium text-white focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-50"
          :disabled="busy || !validOptions || !isDesktop"
          @click="exportPdf"
        >
          <font-awesome-icon :icon="['fas', 'download']" class="mr-1.5" aria-hidden="true" />
          导出 PDF
        </button>
        <button
          v-if="exporting"
          type="button"
          class="border-border hover:bg-hover rounded-lg border px-5 py-2.5 text-sm"
          @click="cancelExport"
        >取消导出</button>
      </div>
      <p v-if="!isDesktop" class="text-text-secondary mt-3 text-xs">PDF 导出仅在桌面应用中可用。</p>
    </section>

    <section
      v-if="phase === 'progress'"
      class="border-border bg-surface flex items-center justify-between gap-4 rounded-2xl border p-6"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <p class="text-sm">
        <font-awesome-icon :icon="['fas', 'spinner']" spin class="text-primary mr-2" aria-hidden="true" />
        正在渲染公式与图片…
      </p>
      <button type="button" class="border-border rounded-lg border px-4 py-2 text-sm" @click="reset">取消</button>
    </section>

    <section v-if="phase === 'preview'" class="border-border bg-surface rounded-2xl border p-6">
      <h2 class="mb-4 font-semibold">预览</h2>
      <iframe
        :srcdoc="previewSrcdoc"
        title="PDF 排版预览"
        sandbox=""
        class="border-border h-[70vh] w-full rounded-xl border"
      />
      <ul v-if="warnings.length" class="text-text-secondary mt-4 list-disc space-y-1 pl-5 text-sm">
        <li v-for="warning in warnings" :key="warning">{{ warning }}</li>
      </ul>
    </section>

    <section v-if="error" class="border-error bg-surface rounded-xl border p-4" role="alert">
      <p class="text-error text-sm">{{ error }}</p>
    </section>
    <p v-if="notice" class="text-sm" role="status">{{ notice }}</p>
    <footer class="text-text-secondary text-center text-xs">
      本地处理；公式与 SVG 由内置 MathJax 矢量渲染，PDF 由 Chromium 打印生成。
    </footer>
  </main>
</template>
