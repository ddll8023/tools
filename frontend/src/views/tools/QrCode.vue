/**
 * 文本或文件转二维码工具页
 * 功能描述：输入文本或选择小文件 → 生成二维码 PNG → 预览并下载
 * 依赖组件：无
 */
<script setup lang="ts">
import { computed, ref } from 'vue'
import { generateQrCode } from '@/api/tools'
import type { QrCodeResponse } from '@/api/tools'

const MAX_QR_PAYLOAD_BYTES = 2500
const MAX_FILE_SIZE = 1500

type InputMode = 'text' | 'file'
type PageState = 'input' | 'progress' | 'result' | 'error'

const inputMode = ref<InputMode>('text')
const currentState = ref<PageState>('input')
const errorMessage = ref('')
const textContent = ref('')
const selectedFile = ref<File | null>(null)
const qrResult = ref<QrCodeResponse | null>(null)
const fileInputRef = ref<HTMLInputElement | null>(null)
let requestSequence = 0

const textByteLength = computed(() => new TextEncoder().encode(textContent.value).length)
const textTooLong = computed(() => textByteLength.value > MAX_QR_PAYLOAD_BYTES)
const canGenerate = computed(() => {
  if (inputMode.value === 'text') {
    return textContent.value.length > 0 && !textTooLong.value
  }
  return selectedFile.value !== null
})

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function selectMode(mode: InputMode) {
  if (currentState.value === 'progress') return
  requestSequence += 1
  inputMode.value = mode
  currentState.value = 'input'
  errorMessage.value = ''
  qrResult.value = null
}

function openFilePicker() {
  fileInputRef.value?.click()
}

function validateFile(file: File): string | null {
  if (file.size === 0) return '不能选择空文件'
  if (file.size > MAX_FILE_SIZE) {
    return `文件过大：单个文件最大 ${(MAX_FILE_SIZE / 1000).toFixed(1)}KB（受二维码容量限制）`
  }
  return null
}

function handleFile(file: File) {
  if (currentState.value === 'progress') return
  requestSequence += 1
  const validationError = validateFile(file)
  if (validationError) {
    selectedFile.value = null
    errorMessage.value = validationError
    currentState.value = 'error'
    return
  }

  selectedFile.value = file
  inputMode.value = 'file'
  errorMessage.value = ''
  currentState.value = 'input'
  qrResult.value = null
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) handleFile(file)
  input.value = ''
}

function onDrop(event: DragEvent) {
  event.preventDefault()
  const file = event.dataTransfer?.files?.[0]
  if (file) handleFile(file)
}

function onDragOver(event: DragEvent) {
  event.preventDefault()
}

async function handleGenerate() {
  if (!canGenerate.value) return

  currentState.value = 'progress'
  errorMessage.value = ''
  qrResult.value = null
  const requestId = ++requestSequence

  try {
    let result: QrCodeResponse
    if (inputMode.value === 'text') {
      result = await generateQrCode(textContent.value)
    } else {
      const file = selectedFile.value
      if (!file) {
        currentState.value = 'input'
        return
      }
      result = await generateQrCode(undefined, file)
    }
    if (requestId !== requestSequence) return
    qrResult.value = result
    currentState.value = 'result'
  } catch (error: unknown) {
    if (requestId !== requestSequence) return
    errorMessage.value = getErrorMessage(error, '二维码生成失败，请稍后重试')
    currentState.value = 'error'
  }
}

function removeSelectedFile() {
  requestSequence += 1
  selectedFile.value = null
}

function handleDownload() {
  if (!qrResult.value) return

  const link = document.createElement('a')
  link.href = qrResult.value.image_data_url
  link.download = qrResult.value.filename
  document.body.appendChild(link)
  link.click()
  link.remove()
}

function resetUpload() {
  requestSequence += 1
  currentState.value = 'input'
  errorMessage.value = ''
  qrResult.value = null
  selectedFile.value = null
  textContent.value = ''
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  return `${(bytes / 1024).toFixed(1)} KB`
}
</script>

<template>
  <main class="mx-auto w-full max-w-[860px] py-7">
    <section class="mb-5 rounded-2xl border border-border bg-surface p-8">
      <div
        class="mb-[18px] text-[13px] font-semibold uppercase tracking-[0.5px] text-text-secondary"
      >
        <font-awesome-icon :icon="['fas', 'qrcode']" class="mr-1.5" />
        生成内容
      </div>

      <div class="mb-5 flex rounded-lg bg-[#F9F9F6] p-1" role="tablist" aria-label="二维码内容类型">
        <button
          type="button"
          role="tab"
          :aria-selected="inputMode === 'text'"
          :disabled="currentState === 'progress'"
          class="flex-1 rounded-md px-4 py-2 text-[13px] font-medium transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-60"
          :class="inputMode === 'text' ? 'bg-surface text-primary-dark shadow-sm' : 'text-text-secondary hover:text-text'"
          @click="selectMode('text')"
        >
          <font-awesome-icon :icon="['fas', 'code']" class="mr-1.5" />
          文本
        </button>
        <button
          type="button"
          role="tab"
          :aria-selected="inputMode === 'file'"
          :disabled="currentState === 'progress'"
          class="flex-1 rounded-md px-4 py-2 text-[13px] font-medium transition-all duration-200 disabled:cursor-not-allowed disabled:opacity-60"
          :class="inputMode === 'file' ? 'bg-surface text-primary-dark shadow-sm' : 'text-text-secondary hover:text-text'"
          @click="selectMode('file')"
        >
          <font-awesome-icon :icon="['far', 'file']" class="mr-1.5" />
          文件
        </button>
      </div>

      <div v-if="inputMode === 'text'">
        <label for="qr-text" class="mb-2 block text-[13px] font-medium">文本内容</label>
        <textarea
          id="qr-text"
          v-model="textContent"
          rows="8"
          placeholder="请输入要生成二维码的文本"
          class="w-full resize-y rounded-xl border border-border bg-[#F9F9F6] px-4 py-3 text-[13px] leading-relaxed text-text outline-none transition-colors placeholder:text-text-tertiary focus:border-primary focus:bg-surface disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="currentState === 'progress' || currentState === 'result'"
          :aria-describedby="textTooLong ? 'qr-text-error' : 'qr-text-hint'"
        ></textarea>
        <div class="mt-2 flex justify-between text-[12px] text-text-tertiary">
          <span id="qr-text-hint">支持中文，二维码容量受内容字节数限制</span>
          <span :class="textTooLong ? 'text-error' : ''">
            {{ textByteLength }} / {{ MAX_QR_PAYLOAD_BYTES }} 字节
          </span>
        </div>
        <p v-if="textTooLong" id="qr-text-error" class="mt-1 text-[12px] text-error">
          文本过长，请减少内容后再生成
        </p>
      </div>

      <div v-else>
        <div
          class="rounded-xl border-2 border-dashed border-border py-11 text-center transition-all duration-250 hover:border-primary hover:bg-primary-light"
          @dragover="onDragOver"
          @drop="onDrop"
        >
          <div class="mb-3.5 text-[38px] text-text-tertiary">
            <font-awesome-icon :icon="['fas', 'upload']" />
          </div>
          <h2 class="mb-1.5 text-[15px] font-semibold">将文件拖拽到此处</h2>
          <p class="mb-[18px] text-[13px] text-text-secondary">
            或点击下方按钮选择文件
          </p>
          <button
            type="button"
            class="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-primary px-[22px] py-[9px] font-inherit text-[13px] font-medium text-white transition-all duration-200 hover:bg-primary-dark focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="currentState === 'progress' || currentState === 'result'"
            @click="openFilePicker"
          >
            <font-awesome-icon :icon="['fas', 'upload']" />
            选择文件
          </button>
          <div class="mt-3.5 text-[12px] text-text-tertiary">
            支持常见文件类型，单文件最大 {{ (MAX_FILE_SIZE / 1000).toFixed(1) }}KB
          </div>
          <div class="mt-1 text-[12px] text-text-tertiary">
            文件内容会编码为带文件名和 MIME 类型的 JSON
          </div>
        </div>

        <input
          ref="fileInputRef"
          type="file"
          class="hidden"
          @change="onFileChange"
        />

        <div
          v-if="selectedFile"
          class="mt-4 flex items-center gap-3 rounded-lg bg-[#F9F9F6] px-4 py-2.5 text-[13px]"
        >
          <font-awesome-icon :icon="['far', 'file']" class="text-primary" />
          <span class="flex-1 truncate font-medium">{{ selectedFile.name }}</span>
          <span class="text-text-secondary">{{ formatSize(selectedFile.size) }}</span>
          <button
            v-if="currentState !== 'progress' && currentState !== 'result'"
            type="button"
            class="cursor-pointer text-text-tertiary transition-all duration-200 hover:text-error"
            aria-label="移除文件"
            @click="removeSelectedFile"
          >
            <font-awesome-icon :icon="['fas', 'xmark']" />
          </button>
        </div>
      </div>

      <button
        type="button"
        class="mt-6 inline-flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg bg-primary px-[22px] py-[11px] font-inherit text-[14px] font-medium text-white transition-all duration-200 hover:bg-primary-dark focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="!canGenerate || currentState !== 'input'"
        @click="handleGenerate"
      >
        <font-awesome-icon :icon="['fas', 'wand-magic-sparkles']" />
        生成二维码
      </button>
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
        正在生成二维码...
      </div>
    </section>

    <section
      v-if="currentState === 'result' && qrResult"
      class="mb-5 rounded-2xl border border-border bg-surface p-8"
    >
      <div
        class="mb-[18px] text-[13px] font-semibold uppercase tracking-[0.5px] text-text-secondary"
      >
        <font-awesome-icon :icon="['fas', 'check-circle']" class="mr-1.5" />
        生成完成
      </div>

      <div class="mb-5 flex flex-col items-center rounded-xl bg-[#F9F9F6] p-6">
        <img
          :src="qrResult.image_data_url"
          alt="生成的二维码"
          class="h-auto w-full max-w-[420px] border border-border bg-white p-3"
        />
      </div>

      <div class="mb-5 rounded-lg border border-border bg-[#F9F9F6] px-5 py-3 text-[13px]">
        <font-awesome-icon :icon="['fas', 'qrcode']" class="mr-1.5 text-primary" />
        <span class="font-medium">{{ qrResult.filename }}</span>
        <span class="text-text-secondary">
          （{{ qrResult.payload_size }} 字节）
        </span>
      </div>

      <div class="flex gap-3">
        <button
          type="button"
          class="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-primary px-[22px] py-[9px] font-inherit text-[13px] font-medium text-white transition-all duration-200 hover:bg-primary-dark focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
          @click="handleDownload"
        >
          <font-awesome-icon :icon="['fas', 'download']" />
          下载二维码
        </button>
        <button
          type="button"
          class="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-border bg-transparent px-[22px] py-[9px] font-inherit text-[13px] font-medium text-text-secondary transition-all duration-200 hover:border-[#999] hover:text-text"
          @click="resetUpload"
        >
          <font-awesome-icon :icon="['fas', 'rotate']" />
          重新生成
        </button>
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
        <h4 class="mb-1 text-[14px] font-semibold">生成失败</h4>
        <p class="text-[13px] text-text-secondary">{{ errorMessage }}</p>
      </div>
      <button
        type="button"
        class="cursor-pointer rounded-lg border border-border bg-transparent px-3 py-1.5 font-inherit text-xs text-text-secondary transition-all duration-200 hover:border-[#999] hover:text-text"
        @click="currentState = 'input'"
      >
        返回编辑
      </button>
    </section>

    <footer class="mt-5 text-center text-[12px] text-text-tertiary">
      <font-awesome-icon :icon="['far', 'clock']" class="mr-1" />
      本地处理，文件不会上传；单个二维码有容量限制
    </footer>
  </main>
</template>
