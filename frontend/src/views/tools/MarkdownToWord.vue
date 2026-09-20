<!-- Markdown 转 Word 工具页：复用来源选择器，组织 DOCX/DOC 转换与下载流程。 -->
<script setup lang="ts">
import { onBeforeUnmount, ref } from 'vue'
import MarkdownSourcePicker from '@/features/markdown/components/MarkdownSourcePicker.vue'
import type { MarkdownSource } from '@/features/markdown/source'
import {
  convertLocalMarkdownToWord,
  convertMarkdownToWord,
  downloadMarkdownToWord,
} from '@/api/tools'
import type { MarkdownToWordConvertResponse, MarkdownToWordOutputFormat } from '@/api/tools'

type PageState = 'upload' | 'progress' | 'result' | 'error'

const currentState = ref<PageState>('upload')
const outputFormat = ref<MarkdownToWordOutputFormat>('docx')
const errorMessage = ref('')
const selectedSource = ref<MarkdownSource | null>(null)
const currentTaskId = ref('')
const conversionResult = ref<MarkdownToWordConvertResponse | null>(null)
let requestVersion = 0
onBeforeUnmount(() => { requestVersion++ })

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function handleSource(source: MarkdownSource) {
  selectedSource.value = source
  void convertSelected()
}

function handleSourceError(message: string) {
  errorMessage.value = message
  currentState.value = 'error'
}

async function convertSelected() {
  const source = selectedSource.value
  if (!source || currentState.value === 'progress') return
  const version = ++requestVersion

  currentTaskId.value = ''
  conversionResult.value = null
  errorMessage.value = ''
  currentState.value = 'progress'

  try {
    const result =
      source.kind === 'local'
        ? await convertLocalMarkdownToWord(source.path, outputFormat.value)
        : await convertMarkdownToWord(source.file, outputFormat.value)
    if (version !== requestVersion) return
    conversionResult.value = result
    currentTaskId.value = result.task_id
    currentState.value = 'result'
  } catch (error: unknown) {
    if (version !== requestVersion) return
    errorMessage.value = getErrorMessage(error, '转换失败，请稍后重试')
    currentState.value = 'error'
  }
}

async function handleDownload() {
  if (!currentTaskId.value || !conversionResult.value) return

  try {
    await downloadMarkdownToWord(currentTaskId.value, conversionResult.value.output_format)
  } catch (error: unknown) {
    errorMessage.value = getErrorMessage(error, '下载失败')
    currentState.value = 'error'
  }
}

function resetUpload() {
  requestVersion++
  currentState.value = 'upload'
  outputFormat.value = 'docx'
  errorMessage.value = ''
  selectedSource.value = null
  currentTaskId.value = ''
  conversionResult.value = null
}
</script>

<template>
  <main class="mx-auto w-full max-w-[860px] py-7">
    <section class="border-border bg-surface mb-5 rounded-2xl border p-8">
      <div
        class="text-text-secondary mb-[18px] text-[13px] font-semibold tracking-[0.5px] uppercase"
      >
        <font-awesome-icon :icon="['far', 'file-lines']" class="mr-1.5" aria-hidden="true" />
        选择文件
      </div>

      <MarkdownSourcePicker
        v-if="currentState === 'upload' || currentState === 'error'"
        @select="handleSource"
        @error="handleSourceError"
      />

      <div
        v-if="currentState === 'progress' || currentState === 'result'"
        class="mt-[18px] flex items-center justify-center gap-3 rounded-lg bg-[#F9F9F6] px-5 py-3 text-[13px]"
      >
        <font-awesome-icon
          :icon="['far', 'circle-check']"
          class="text-success"
          aria-hidden="true"
        />
        <span class="font-medium">{{ selectedSource?.name }}</span>
        <span v-if="selectedSource" class="text-text-secondary">
          ({{ (selectedSource.size / 1024 / 1024).toFixed(1) }} MB)
        </span>
        <span
          v-if="selectedSource"
          class="text-text-secondary rounded-full bg-[#EFEFEA] px-2 py-0.5 text-[11px]"
        >
          {{ selectedSource.kind === 'local' ? '本地路径读取' : '文件上传' }}
        </span>
      </div>
    </section>

    <section class="border-border bg-surface mb-5 rounded-2xl border p-8">
      <fieldset :disabled="currentState === 'progress' || currentState === 'result'">
        <legend class="text-text-secondary mb-3 text-[13px] font-semibold">输出格式</legend>
        <div class="flex flex-wrap gap-3">
          <label
            class="border-border hover:border-primary flex cursor-pointer items-center gap-2 rounded-lg border px-4 py-2.5 text-[13px] transition-colors"
            :class="
              outputFormat === 'docx' ? 'border-primary bg-primary-light text-primary-dark' : ''
            "
          >
            <input v-model="outputFormat" type="radio" value="docx" class="accent-primary" />
            <span>DOCX</span>
          </label>
          <label
            class="border-border hover:border-primary flex cursor-pointer items-center gap-2 rounded-lg border px-4 py-2.5 text-[13px] transition-colors"
            :class="
              outputFormat === 'doc' ? 'border-primary bg-primary-light text-primary-dark' : ''
            "
          >
            <input v-model="outputFormat" type="radio" value="doc" class="accent-primary" />
            <span>DOC</span>
          </label>
        </div>
        <p class="text-text-tertiary mt-3 text-[12px]">
          DOC 格式需要本机可用的 LibreOffice；DOCX 不依赖 LibreOffice。
        </p>
      </fieldset>
    </section>

    <section
      v-if="currentState === 'progress'"
      class="border-border bg-surface mb-5 rounded-2xl border p-8"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <div
        class="text-text-secondary mb-[18px] text-[13px] font-semibold tracking-[0.5px] uppercase"
      >
        <font-awesome-icon :icon="['far', 'hourglass-half']" class="mr-1.5" aria-hidden="true" />
        正在处理
      </div>

      <div class="mb-5 h-1.5 w-full overflow-hidden rounded-full bg-[#F0F0EC]">
        <div class="bg-primary h-full w-full animate-pulse rounded-full"></div>
      </div>
      <div class="flex items-center gap-2.5 text-[13px] font-medium">
        <span class="text-primary w-5 text-center text-sm">
          <font-awesome-icon :icon="['fas', 'spinner']" spin aria-hidden="true" />
        </span>
        正在生成 {{ outputFormat.toUpperCase() }} 文档...
      </div>
    </section>

    <section
      v-if="currentState === 'result' && conversionResult"
      class="border-border bg-surface mb-5 rounded-2xl border p-8"
    >
      <div
        class="text-text-secondary mb-[18px] text-[13px] font-semibold tracking-[0.5px] uppercase"
      >
        <font-awesome-icon :icon="['fas', 'check-circle']" class="mr-1.5" aria-hidden="true" />
        转换完成
      </div>

      <div class="mb-5 flex gap-3">
        <button
          type="button"
          class="bg-primary font-inherit hover:bg-primary-dark focus-visible:outline-primary inline-flex cursor-pointer items-center gap-2 rounded-lg px-[22px] py-[9px] text-[13px] font-medium text-white transition-all duration-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          @click="handleDownload"
        >
          <font-awesome-icon :icon="['fas', 'download']" aria-hidden="true" />
          下载 {{ conversionResult.output_format.toUpperCase() }}
        </button>
        <button
          type="button"
          class="border-border font-inherit text-text-secondary hover:text-text focus-visible:outline-primary inline-flex cursor-pointer items-center gap-2 rounded-lg border bg-transparent px-[22px] py-[9px] text-[13px] font-medium transition-all duration-200 hover:border-[#999] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          @click="resetUpload"
        >
          <font-awesome-icon :icon="['fas', 'rotate']" aria-hidden="true" />
          重新上传
        </button>
      </div>

      <div class="text-text-secondary mb-3 flex items-center gap-4 text-[12px]">
        <span>
          <font-awesome-icon :icon="['far', 'file-lines']" class="mr-1" aria-hidden="true" />
          {{ conversionResult.output_format.toUpperCase() }}
        </span>
        <span>
          <font-awesome-icon :icon="['fas', 'file-word']" class="mr-1" aria-hidden="true" />
          {{ conversionResult.output_filename }}
        </span>
      </div>

      <div
        v-if="conversionResult.warnings.length > 0"
        class="text-text-secondary mt-4 flex items-start gap-3 rounded-lg border border-[#FFE3B3] bg-[#FFF9ED] p-4 text-[13px]"
        role="status"
      >
        <font-awesome-icon
          :icon="['fas', 'triangle-exclamation']"
          class="mt-0.5 text-[#B8860B]"
          aria-hidden="true"
        />
        <ul class="list-disc space-y-1 pl-4">
          <li v-for="warning in conversionResult.warnings" :key="warning">{{ warning }}</li>
        </ul>
      </div>
    </section>

    <section
      v-if="currentState === 'error'"
      class="mt-4 flex items-start gap-3 rounded-lg border border-[#FFD7D7] bg-[#FFF5F5] p-4 pl-5"
      role="alert"
    >
      <font-awesome-icon
        :icon="['far', 'circle-xmark']"
        class="text-error mt-0.5 text-lg"
        aria-hidden="true"
      />
      <div class="flex-1">
        <h4 class="mb-1 text-[14px] font-semibold">转换失败</h4>
        <p class="text-text-secondary text-[13px]">{{ errorMessage }}</p>
      </div>
      <button
        type="button"
        class="border-border font-inherit text-text-secondary hover:text-text focus-visible:outline-primary cursor-pointer rounded-lg border bg-transparent px-3 py-1.5 text-xs transition-all duration-200 hover:border-[#999] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
        @click="resetUpload"
      >
        重新上传
      </button>
    </section>

    <footer class="text-text-tertiary mt-5 text-center text-[12px]">
      <font-awesome-icon :icon="['far', 'clock']" class="mr-1" aria-hidden="true" />
      本地处理，文件不会上传
    </footer>
  </main>
</template>
