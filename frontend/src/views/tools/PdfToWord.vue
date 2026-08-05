/**
 * PDF 转 Word 工具页
 * 功能描述：上传包含文字层的 PDF → 转换 → 下载 DOCX
 * 依赖组件：无
 */
<script setup lang="ts">
import { ref } from 'vue'
import { convertPdfToWord, downloadWord } from '@/api/tools'
import type { PdfToWordConvertResponse } from '@/api/tools'

const MAX_FILE_SIZE = 50 * 1024 * 1024

type PageState = 'upload' | 'progress' | 'result' | 'error'

const currentState = ref<PageState>('upload')
const errorMessage = ref('')
const selectedFile = ref<File | null>(null)
const currentTaskId = ref('')
const conversionResult = ref<PdfToWordConvertResponse | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
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

function openFilePicker() {
  fileInputRef.value?.click()
}

async function handleFile(file: File) {
  const validationError = validateFile(file)
  if (validationError) {
    errorMessage.value = validationError
    currentState.value = 'error'
    return
  }

  selectedFile.value = file
  conversionResult.value = null
  currentTaskId.value = ''
  errorMessage.value = ''
  currentState.value = 'progress'

  try {
    const result = await convertPdfToWord(file)
    conversionResult.value = result
    currentTaskId.value = result.task_id
    currentState.value = 'result'
  } catch (error: unknown) {
    errorMessage.value = getErrorMessage(error, '转换失败，请稍后重试')
    currentState.value = 'error'
  }
}

async function handleDownload() {
  if (!currentTaskId.value) return

  try {
    await downloadWord(currentTaskId.value)
  } catch (error: unknown) {
    errorMessage.value = getErrorMessage(error, '下载失败')
    currentState.value = 'error'
  }
}

function resetUpload() {
  currentState.value = 'upload'
  errorMessage.value = ''
  selectedFile.value = null
  currentTaskId.value = ''
  conversionResult.value = null
}
</script>

<template>
  <main class="mx-auto w-full max-w-[860px] py-7">
    <section class="mb-5 rounded-2xl border border-border bg-surface p-8">
      <div
        class="mb-[18px] text-[13px] font-semibold uppercase tracking-[0.5px] text-text-secondary"
      >
        <font-awesome-icon :icon="['far', 'file']" class="mr-1.5" />
        选择文件
      </div>

      <div v-if="currentState === 'upload' || currentState === 'error'">
        <div
          class="cursor-pointer rounded-xl border-2 border-dashed border-border py-11 text-center transition-all duration-250 hover:border-primary hover:bg-primary-light"
          @dragover="onDragOver"
          @drop="onDrop"
        >
          <div class="mb-3.5 text-[38px] text-text-tertiary">
            <font-awesome-icon :icon="['fas', 'file-pdf']" />
          </div>
          <h2 class="mb-1.5 text-[15px] font-semibold">将 PDF 文件拖拽到此处</h2>
          <p class="mb-[18px] text-[13px] text-text-secondary">
            或点击下方按钮选择文件
          </p>
          <button
            type="button"
            class="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-primary px-[22px] py-[9px] font-inherit text-[13px] font-medium text-white transition-all duration-200 hover:bg-primary-dark focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
            @click="openFilePicker"
          >
            <font-awesome-icon :icon="['fas', 'upload']" />
            选择 PDF 文件
          </button>
          <div class="mt-3.5 text-[12px] text-text-tertiary">
            支持 .pdf 格式，最大 50MB；纯扫描 PDF 暂不支持
          </div>
        </div>

        <input
          ref="fileInputRef"
          type="file"
          accept=".pdf,application/pdf"
          class="hidden"
          @change="onFileChange"
        />
      </div>

      <div
        v-if="currentState === 'progress' || currentState === 'result'"
        class="mt-[18px] flex items-center justify-center gap-3 rounded-lg bg-[#F9F9F6] px-5 py-3 text-[13px]"
      >
        <font-awesome-icon :icon="['far', 'circle-check']" class="text-success" />
        <span class="font-medium">{{ selectedFile?.name }}</span>
        <span v-if="selectedFile" class="text-text-secondary">
          ({{ (selectedFile.size / 1024 / 1024).toFixed(1) }} MB)
        </span>
      </div>
    </section>

    <section
      v-if="currentState === 'progress'"
      class="mb-5 rounded-2xl border border-border bg-surface p-8"
      role="status"
      aria-live="polite"
      aria-busy="true"
    >
      <div
        class="mb-[18px] text-[13px] font-semibold uppercase tracking-[0.5px] text-text-secondary"
      >
        <font-awesome-icon :icon="['far', 'hourglass-half']" class="mr-1.5" />
        正在处理
      </div>

      <div class="mb-5 h-1.5 w-full overflow-hidden rounded-full bg-[#F0F0EC]">
        <div class="h-full w-full animate-pulse rounded-full bg-primary"></div>
      </div>
      <div class="flex items-center gap-2.5 text-[13px] font-medium">
        <span class="w-5 text-center text-sm text-primary">
          <font-awesome-icon :icon="['fas', 'spinner']" spin />
        </span>
        正在将 PDF 转换为 Word...
      </div>
    </section>

    <section
      v-if="currentState === 'result' && conversionResult"
      class="mb-5 rounded-2xl border border-border bg-surface p-8"
    >
      <div
        class="mb-[18px] text-[13px] font-semibold uppercase tracking-[0.5px] text-text-secondary"
      >
        <font-awesome-icon :icon="['fas', 'check-circle']" class="mr-1.5" />
        转换完成
      </div>

      <div class="mb-5 flex gap-3">
        <button
          type="button"
          class="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-primary px-[22px] py-[9px] font-inherit text-[13px] font-medium text-white transition-all duration-200 hover:bg-primary-dark focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          @click="handleDownload"
        >
          <font-awesome-icon :icon="['fas', 'download']" />
          下载 Word
        </button>
        <button
          type="button"
          class="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-border bg-transparent px-[22px] py-[9px] font-inherit text-[13px] font-medium text-text-secondary transition-all duration-200 hover:border-[#999] hover:text-text"
          @click="resetUpload"
        >
          <font-awesome-icon :icon="['fas', 'rotate']" />
          重新上传
        </button>
      </div>

      <div class="mb-3 flex items-center gap-4 text-[12px] text-text-secondary">
        <span>
          <font-awesome-icon :icon="['far', 'file']" class="mr-1" />
          {{ conversionResult.page_count }} 页
        </span>
        <span>
          <font-awesome-icon :icon="['fas', 'file-word']" class="mr-1" />
          DOCX
        </span>
      </div>

      <div class="rounded-lg border border-border bg-[#F9F9F6] px-5 py-3 text-[13px]">
        <font-awesome-icon :icon="['fas', 'file-word']" class="mr-1.5 text-primary" />
        <span class="font-medium">{{ conversionResult.output_filename }}</span>
      </div>

      <div
        v-if="conversionResult.warnings.length > 0"
        class="mt-4 flex items-start gap-3 rounded-lg border border-[#FFE3B3] bg-[#FFF9ED] p-4 text-[13px] text-text-secondary"
        role="status"
      >
        <font-awesome-icon :icon="['fas', 'triangle-exclamation']" class="mt-0.5 text-[#B8860B]" />
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
        class="mt-0.5 text-lg text-error"
      />
      <div class="flex-1">
        <h4 class="mb-1 text-[14px] font-semibold">转换失败</h4>
        <p class="text-[13px] text-text-secondary">{{ errorMessage }}</p>
      </div>
      <button
        type="button"
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
