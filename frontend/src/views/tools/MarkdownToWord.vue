<script setup lang="ts">
import { ref } from 'vue'
import { convertMarkdownToWord, downloadMarkdownToWord } from '@/api/tools'
import type { MarkdownToWordConvertResponse, MarkdownToWordOutputFormat } from '@/api/tools'

const MAX_FILE_SIZE = 50 * 1024 * 1024

type PageState = 'upload' | 'progress' | 'result' | 'error'

const currentState = ref<PageState>('upload')
const outputFormat = ref<MarkdownToWordOutputFormat>('docx')
const errorMessage = ref('')
const selectedFile = ref<File | null>(null)
const currentTaskId = ref('')
const conversionResult = ref<MarkdownToWordConvertResponse | null>(null)
const fileInput = ref<HTMLInputElement | null>(null)

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function validateFile(file: File): string | null {
  const filename = file.name.toLowerCase()
  if (!filename.endsWith('.md') && !filename.endsWith('.markdown') && !filename.endsWith('.zip')) {
    return '仅支持 .md、.markdown 或 .zip 格式'
  }
  if (file.size > MAX_FILE_SIZE) {
    return '文件大小不能超过 50MB'
  }
  return null
}

function openFilePicker() {
  fileInput.value?.click()
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  void handleFile(file)
  input.value = ''
}

function onDrop(event: DragEvent) {
  event.preventDefault()
  const file = event.dataTransfer?.files?.[0]
  if (!file) return
  void handleFile(file)
}

function onDragOver(event: DragEvent) {
  event.preventDefault()
}

async function handleFile(file: File) {
  const validationError = validateFile(file)
  if (validationError) {
    errorMessage.value = validationError
    currentState.value = 'error'
    return
  }

  selectedFile.value = file
  currentTaskId.value = ''
  conversionResult.value = null
  errorMessage.value = ''
  currentState.value = 'progress'

  try {
    const result = await convertMarkdownToWord(file, outputFormat.value)
    conversionResult.value = result
    currentTaskId.value = result.task_id
    currentState.value = 'result'
  } catch (error: unknown) {
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
  currentState.value = 'upload'
  outputFormat.value = 'docx'
  errorMessage.value = ''
  selectedFile.value = null
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

      <div v-if="currentState === 'upload' || currentState === 'error'">
        <div
          class="border-border hover:border-primary hover:bg-primary-light cursor-pointer rounded-xl border-2 border-dashed py-11 text-center transition-all duration-250"
          @dragover="onDragOver"
          @drop="onDrop"
        >
          <div class="text-text-tertiary mb-3.5 text-[38px]">
            <font-awesome-icon :icon="['fas', 'file-word']" aria-hidden="true" />
          </div>
          <h2 class="mb-1.5 text-[15px] font-semibold">将 Markdown 文件拖拽到此处</h2>
          <p class="text-text-secondary mb-[18px] text-[13px]">
            支持直接上传 Markdown，或上传包含 Markdown 与 images/ 目录的 ZIP
          </p>
          <button
            type="button"
            class="bg-primary font-inherit hover:bg-primary-dark focus-visible:outline-primary inline-flex cursor-pointer items-center gap-2 rounded-lg px-[22px] py-[9px] text-[13px] font-medium text-white transition-all duration-200 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
            @click="openFilePicker"
          >
            <font-awesome-icon :icon="['fas', 'upload']" aria-hidden="true" />
            选择 Markdown 文件
          </button>
          <div class="text-text-tertiary mt-3.5 text-[12px]">
            支持 .md、.markdown、.zip，最大 50MB；ZIP 中只能包含一个 Markdown 文件
          </div>
        </div>

        <input
          ref="fileInput"
          type="file"
          accept=".md,.markdown,.zip,text/markdown,application/zip"
          class="hidden"
          @change="onFileChange"
        />
      </div>

      <div
        v-if="currentState === 'progress' || currentState === 'result'"
        class="mt-[18px] flex items-center justify-center gap-3 rounded-lg bg-[#F9F9F6] px-5 py-3 text-[13px]"
      >
        <font-awesome-icon
          :icon="['far', 'circle-check']"
          class="text-success"
          aria-hidden="true"
        />
        <span class="font-medium">{{ selectedFile?.name }}</span>
        <span v-if="selectedFile" class="text-text-secondary">
          ({{ (selectedFile.size / 1024 / 1024).toFixed(1) }} MB)
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
