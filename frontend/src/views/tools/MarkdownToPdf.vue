<!-- Markdown 转 PDF：复用 Markdown 来源选择器和 Word 排版链路，由 LibreOffice 生成 PDF。 -->
<script setup lang="ts">
import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import { BaseSelect } from '@/components/common'
import MarkdownSourcePicker from '@/features/markdown/components/MarkdownSourcePicker.vue'
import type { MarkdownSource } from '@/features/markdown/source'
import { convertMarkdownToPdf, downloadMarkdownToPdf } from '@/api/tools'
import type { MarkdownToPdfConvertResponse } from '@/api/tools'
import type { PdfOptions } from '@/features/markdown-pdf/types'

type Phase = 'idle' | 'ready' | 'progress' | 'result' | 'error'
const phase = ref<Phase>('idle')
const source = ref<MarkdownSource | null>(null)
const result = ref<MarkdownToPdfConvertResponse | null>(null)
const error = ref('')
const notice = ref('')
const options = reactive<PdfOptions>({
  landscape: false,
  marginMm: 18,
  fontSize: 11,
  pageNumbers: true,
})
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
const busy = computed(() => phase.value === 'progress')
let controller: AbortController | null = null
let requestVersion = 0

function handleSource(value: MarkdownSource) {
  source.value = value
  result.value = null
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
  result.value = null
  error.value = ''
  notice.value = ''
  phase.value = 'progress'
  try {
    const converted = await convertMarkdownToPdf(selected, options, currentController.signal)
    if (version !== requestVersion) return
    result.value = converted
    phase.value = 'result'
  } catch (cause: unknown) {
    if (version !== requestVersion || currentController.signal.aborted) return
    error.value = cause instanceof Error ? cause.message : '转换失败，请稍后重试'
    phase.value = 'error'
  } finally {
    if (version === requestVersion) controller = null
  }
}

async function download() {
  if (!result.value) return
  try {
    await downloadMarkdownToPdf(result.value.task_id)
    notice.value = `已开始下载：${result.value.output_filename}`
  } catch (cause: unknown) {
    error.value = cause instanceof Error ? cause.message : '下载失败'
    phase.value = 'error'
  }
}

function reset() {
  requestVersion++
  controller?.abort()
  controller = null
  source.value = null
  result.value = null
  error.value = ''
  notice.value = ''
  phase.value = 'idle'
}

onBeforeUnmount(() => {
  requestVersion++
  controller?.abort()
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
      <fieldset class="grid gap-5 sm:grid-cols-2 lg:grid-cols-4" :disabled="busy || phase === 'result'">
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
        使用现有 Markdown 转 Word 排版后由 LibreOffice 生成 PDF，中文标题和图片沿用 Word 转换链路。
      </p>
      <button
        v-if="phase === 'ready' || phase === 'error'"
        type="button"
        class="bg-primary hover:bg-primary-dark focus-visible:outline-primary mt-5 rounded-lg px-5 py-2.5 text-sm font-medium text-white focus-visible:outline-2 focus-visible:outline-offset-2 disabled:opacity-50"
        :disabled="!validOptions"
        @click="convert"
      >
        <font-awesome-icon :icon="['fas', 'file-pdf']" class="mr-1.5" aria-hidden="true" />
        生成 PDF
      </button>
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
        正在生成 DOCX 并调用 LibreOffice 转换 PDF…
      </p>
      <button type="button" class="border-border rounded-lg border px-4 py-2 text-sm" @click="reset">取消</button>
    </section>

    <section v-if="result" class="border-border bg-surface rounded-2xl border p-6">
      <h2 class="mb-4 font-semibold">转换完成</h2>
      <div class="mb-5 flex flex-wrap gap-3">
        <button
          type="button"
          class="bg-primary hover:bg-primary-dark focus-visible:outline-primary rounded-lg px-5 py-2.5 text-sm font-medium text-white focus-visible:outline-2 focus-visible:outline-offset-2"
          @click="download"
        >
          <font-awesome-icon :icon="['fas', 'download']" class="mr-1.5" aria-hidden="true" />
          下载 PDF
        </button>
        <button type="button" class="border-border hover:bg-hover rounded-lg border px-5 py-2.5 text-sm" @click="reset">重新选择</button>
      </div>
      <p class="text-text-secondary text-sm">{{ result.output_filename }}</p>
      <ul v-if="result.warnings.length" class="text-text-secondary mt-4 list-disc space-y-1 pl-5 text-sm">
        <li v-for="warning in result.warnings" :key="warning">{{ warning }}</li>
      </ul>
    </section>

    <section v-if="error" class="border-error bg-surface rounded-xl border p-4" role="alert">
      <p class="text-error text-sm">{{ error }}</p>
    </section>
    <p v-if="notice" class="text-sm" role="status">{{ notice }}</p>
    <footer class="text-text-secondary text-center text-xs">本地处理；PDF 使用已验证的 Markdown → Word → LibreOffice 链路。</footer>
  </main>
</template>
