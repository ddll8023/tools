/**
 * 图片格式转换工具页
 * 功能描述：上传图片 → 选择目标格式/质量 → 转换 → 预览(单张)/下载(批量)
 * 依赖组件：无
 */
<script setup lang="ts">
import { ref, computed } from 'vue'
import { convertImages, downloadConvertedFile, downloadAllConverted } from '@/api/tools'
import type { ImageConvertResponse, ImageConvertFileItem } from '@/api/tools'

const MAX_FILE_SIZE = 50 * 1024 * 1024
const MAX_FILE_COUNT = 20

type PageState = 'upload' | 'progress' | 'result' | 'error'

const currentState = ref<PageState>('upload')
const errorMessage = ref('')
const selectedFiles = ref<File[]>([])
const currentTaskId = ref('')
const convertResult = ref<ImageConvertResponse | null>(null)
const previewUrl = ref<string | null>(null)

const targetFormat = ref('png')
const quality = ref(85)

const formats = [
  { value: 'png', label: 'PNG' },
  { value: 'jpeg', label: 'JPEG' },
  { value: 'webp', label: 'WebP' },
  { value: 'bmp', label: 'BMP' },
  { value: 'gif', label: 'GIF' },
  { value: 'tiff', label: 'TIFF' },
]

const showQuality = computed(() =>
  targetFormat.value === 'jpeg' || targetFormat.value === 'webp',
)

/* ── 文件管理 ── */

function removeFile(index: number) {
  selectedFiles.value.splice(index, 1)
}

function validateFile(file: File): string | null {
  const ext = file.name.toLowerCase().split('.').pop()
  const validExts = ['png', 'jpg', 'jpeg', 'webp', 'bmp', 'gif', 'tiff', 'tif']
  if (!ext || !validExts.includes(ext)) {
    return `不支持的文件格式: ${file.name}`
  }
  if (file.size > MAX_FILE_SIZE) {
    return `文件过大: ${file.name}（最大 50MB）`
  }
  return null
}

function addFiles(newFiles: FileList | File[]) {
  for (const file of Array.from(newFiles)) {
    if (selectedFiles.value.length >= MAX_FILE_COUNT) {
      errorMessage.value = `单次最多上传 ${MAX_FILE_COUNT} 张图片`
      return
    }
    const isDuplicate = selectedFiles.value.some(
      (f) => f.name === file.name && f.size === file.size,
    )
    if (isDuplicate) continue

    const err = validateFile(file)
    if (err) {
      errorMessage.value = err
      continue
    }
    selectedFiles.value.push(file)
  }
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  if (!input.files?.length) return
  addFiles(input.files)
  input.value = ''
}

function onDrop(event: DragEvent) {
  event.preventDefault()
  if (!event.dataTransfer?.files?.length) return
  addFiles(event.dataTransfer.files)
}

function onDragOver(event: DragEvent) {
  event.preventDefault()
}

/* ── 转换 ── */

async function handleConvert() {
  if (selectedFiles.value.length === 0) return

  currentState.value = 'progress'
  errorMessage.value = ''

  try {
    const result: ImageConvertResponse = await convertImages(
      selectedFiles.value,
      targetFormat.value,
      quality.value,
    )
    convertResult.value = result
    currentTaskId.value = result.task_id

    // 单张且可预览 → 获取预览
    if (!result.is_batch && result.files.length > 0) {
      await loadPreview(result.task_id, result.files[0].index)
    }

    currentState.value = 'result'
  } catch (e: any) {
    errorMessage.value = e.message || '转换失败，请稍后重试'
    currentState.value = 'error'
  }
}

async function loadPreview(taskId: string, fileIndex: number) {
  const res = await fetch(
    `http://127.0.0.1:4740/api/v1/tools/image-converter/download`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task_id: taskId, file_index: fileIndex }),
    },
  )
  if (!res.ok) return
  const blob = await res.blob()
  previewUrl.value = URL.createObjectURL(blob)
}

/* ── 下载 ── */

async function handleDownload(fileIndex: number) {
  if (!currentTaskId.value) return
  try {
    await downloadConvertedFile(currentTaskId.value, fileIndex)
  } catch (e: any) {
    errorMessage.value = e.message || '下载失败'
    currentState.value = 'error'
  }
}

async function handleDownloadAll() {
  if (!currentTaskId.value) return
  try {
    await downloadAllConverted(currentTaskId.value)
  } catch (e: any) {
    errorMessage.value = e.message || '下载失败'
    currentState.value = 'error'
  }
}

/* ── 重置 ── */

function resetUpload() {
  currentState.value = 'upload'
  errorMessage.value = ''
  selectedFiles.value = []
  currentTaskId.value = ''
  convertResult.value = null
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = null
  }
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}
</script>

<template>
  <main class="mx-auto w-full max-w-[860px] py-7">
    <!-- 选择文件 -->
    <section class="mb-5 rounded-2xl border border-border bg-surface p-8">
      <div
        class="mb-[18px] text-[13px] font-semibold uppercase tracking-[0.5px] text-text-secondary"
      >
        <font-awesome-icon :icon="['far', 'image']" class="mr-1.5" />
        选择文件
      </div>

      <!-- 上传 / 错误状态 → 展示文件选择区 -->
      <div v-if="currentState === 'upload' || currentState === 'error'">
        <div
          class="cursor-pointer rounded-xl border-2 border-dashed border-border py-11 text-center transition-all duration-250 hover:border-primary hover:bg-primary-light"
          @dragover="onDragOver"
          @drop="onDrop"
        >
          <div class="mb-3.5 text-[38px] text-text-tertiary">
            <font-awesome-icon :icon="['fas', 'image']" />
          </div>
          <h2 class="mb-1.5 text-[15px] font-semibold">将图片拖拽到此处</h2>
          <p class="mb-[18px] text-[13px] text-text-secondary">
            或点击下方按钮选择文件
          </p>
          <button
            class="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-primary px-[22px] py-[9px] font-inherit text-[13px] font-medium text-white transition-all duration-200 hover:bg-primary-dark"
            @click="$refs.fileInput.click()"
          >
            <font-awesome-icon :icon="['fas', 'upload']" />
            选择图片
          </button>
          <div class="mt-3.5 text-[12px] text-text-tertiary">
            支持 PNG / JPEG / WebP / BMP / GIF / TIFF，单文件最大 50MB，单次最多 20 张
          </div>
        </div>

        <input
          ref="fileInput"
          type="file"
          multiple
          accept=".png,.jpg,.jpeg,.webp,.bmp,.gif,.tiff,.tif"
          class="hidden"
          @change="onFileChange"
        />
      </div>

      <!-- 文件列表 -->
      <div
        v-if="selectedFiles.length > 0"
        class="mt-4 space-y-2"
      >
        <div
          v-for="(file, index) in selectedFiles"
          :key="index"
          class="flex items-center gap-3 rounded-lg bg-[#F9F9F6] px-4 py-2.5 text-[13px]"
        >
          <font-awesome-icon :icon="['far', 'file-image']" class="text-primary" />
          <span class="flex-1 truncate font-medium">{{ file.name }}</span>
          <span class="text-text-secondary">{{ formatSize(file.size) }}</span>
          <button
            v-if="currentState === 'upload'"
            class="cursor-pointer text-text-tertiary transition-all duration-200 hover:text-error"
            @click="removeFile(index)"
          >
            <font-awesome-icon :icon="['fas', 'xmark']" />
          </button>
        </div>
      </div>
    </section>

    <!-- 转换参数 -->
    <section
      v-if="currentState === 'upload'"
      class="mb-5 rounded-2xl border border-border bg-surface p-8"
    >
      <div
        class="mb-[18px] text-[13px] font-semibold uppercase tracking-[0.5px] text-text-secondary"
      >
        <font-awesome-icon :icon="['fas', 'sliders']" class="mr-1.5" />
        转换参数
      </div>

      <div class="space-y-5">
        <!-- 目标格式 -->
        <div>
          <label class="mb-2 block text-[13px] font-medium">目标格式</label>
          <div class="flex flex-wrap gap-2">
            <button
              v-for="fmt in formats"
              :key="fmt.value"
              class="cursor-pointer rounded-lg border px-4 py-2 text-[13px] font-medium transition-all duration-200"
              :class="
                targetFormat === fmt.value
                  ? 'border-primary bg-primary text-white'
                  : 'border-border bg-transparent text-text-secondary hover:border-[#999] hover:text-text'
              "
              @click="targetFormat = fmt.value"
            >
              {{ fmt.label }}
            </button>
          </div>
        </div>

        <!-- 图片质量 -->
        <div v-if="showQuality">
          <label class="mb-2 block text-[13px] font-medium">
            图片质量：{{ quality }}
          </label>
          <input
            type="range"
            min="1"
            max="100"
            :value="quality"
            class="w-full cursor-pointer accent-primary"
            @input="quality = Number(($event.target as HTMLInputElement).value)"
          />
          <div class="mt-1 flex justify-between text-[11px] text-text-tertiary">
            <span>低质量</span>
            <span>高质量</span>
          </div>
        </div>
        <div v-else class="text-[12px] text-text-tertiary">
          ⓘ 此格式为无损格式，不适用质量参数
        </div>
      </div>

      <!-- 开始转换 -->
      <button
        class="mt-6 inline-flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg bg-primary px-[22px] py-[11px] font-inherit text-[14px] font-medium text-white transition-all duration-200 hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="selectedFiles.length === 0"
        @click="handleConvert"
      >
        <font-awesome-icon :icon="['fas', 'wand-magic-sparkles']" />
        开始转换
        <span v-if="selectedFiles.length > 0">（{{ selectedFiles.length }} 张）</span>
      </button>
    </section>

    <!-- 进度 -->
    <section
      v-if="currentState === 'progress'"
      class="mb-5 rounded-2xl border border-border bg-surface p-8"
    >
      <div
        class="mb-[18px] text-[13px] font-semibold uppercase tracking-[0.5px] text-text-secondary"
      >
        <font-awesome-icon :icon="['far', 'hourglass-half']" class="mr-1.5" />
        正在处理
      </div>

      <div class="mb-5 h-1.5 w-full overflow-hidden rounded-full bg-[#F0F0EC]">
        <div
          class="h-full w-full animate-pulse rounded-full bg-primary transition-all duration-400"
        ></div>
      </div>
      <div class="flex items-center gap-2.5 text-[13px] font-medium">
        <span class="w-5 text-center text-sm text-primary">
          <font-awesome-icon :icon="['fas', 'spinner']" spin />
        </span>
        <span v-if="selectedFiles.length > 1">
          正在转换 {{ selectedFiles.length }} 张图片...
        </span>
        <span v-else>正在转换图片...</span>
      </div>
    </section>

    <!-- 结果 -->
    <section
      v-if="currentState === 'result' && convertResult"
      class="mb-5 rounded-2xl border border-border bg-surface p-8"
    >
      <div
        class="mb-[18px] text-[13px] font-semibold uppercase tracking-[0.5px] text-text-secondary"
      >
        <font-awesome-icon :icon="['fas', 'check-circle']" class="mr-1.5" />
        转换完成
      </div>

      <!-- 单张预览 -->
      <div v-if="!convertResult.is_batch && previewUrl">
        <img
          :src="previewUrl"
          alt="转换后预览"
          class="mb-4 max-h-96 w-full rounded-lg border object-contain"
        />
        <div class="mb-5 flex gap-3">
          <button
            class="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-primary px-[22px] py-[9px] font-inherit text-[13px] font-medium text-white transition-all duration-200 hover:bg-primary-dark"
            @click="handleDownload(convertResult.files[0].index)"
          >
            <font-awesome-icon :icon="['fas', 'download']" />
            下载图片
          </button>
          <button
            class="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-border bg-transparent px-[22px] py-[9px] font-inherit text-[13px] font-medium text-text-secondary transition-all duration-200 hover:border-[#999] hover:text-text"
            @click="resetUpload"
          >
            <font-awesome-icon :icon="['fas', 'rotate']" />
            重新上传
          </button>
        </div>

        <div
          class="rounded-lg border border-border bg-[#F9F9F6] px-5 py-3 text-[13px]"
        >
          <font-awesome-icon :icon="['far', 'file-image']" class="mr-1.5 text-primary" />
          <span class="font-medium">{{ convertResult.files[0].original_name }}</span>
          <span class="text-text-secondary">
            → {{ convertResult.files[0].converted_name }}
            （{{ formatSize(convertResult.files[0].file_size) }}）
          </span>
        </div>
      </div>

      <!-- 批量结果 -->
      <div v-else>
        <div class="mb-4 space-y-2">
          <div
            v-for="file in convertResult.files"
            :key="file.index"
            class="flex items-center gap-3 rounded-lg border border-border bg-[#F9F9F6] px-4 py-2.5 text-[13px]"
          >
            <font-awesome-icon :icon="['far', 'file-image']" class="text-primary" />
            <span class="flex-1 truncate">
              <span class="font-medium">{{ file.original_name }}</span>
              <span class="text-text-secondary">
                → {{ file.converted_name }}
              </span>
            </span>
            <span class="text-text-secondary">{{ formatSize(file.file_size) }}</span>
            <button
              class="cursor-pointer text-primary transition-all duration-200 hover:text-primary-dark"
              @click="handleDownload(file.index)"
            >
              <font-awesome-icon :icon="['fas', 'download']" />
            </button>
          </div>
        </div>

        <div class="flex gap-3">
          <button
            class="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-primary px-[22px] py-[9px] font-inherit text-[13px] font-medium text-white transition-all duration-200 hover:bg-primary-dark"
            @click="handleDownloadAll"
          >
            <font-awesome-icon :icon="['fas', 'file-zipper']" />
            下载全部（ZIP）
          </button>
          <button
            class="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-border bg-transparent px-[22px] py-[9px] font-inherit text-[13px] font-medium text-text-secondary transition-all duration-200 hover:border-[#999] hover:text-text"
            @click="resetUpload"
          >
            <font-awesome-icon :icon="['fas', 'rotate']" />
            重新上传
          </button>
        </div>
      </div>
    </section>

    <!-- 错误 -->
    <section
      v-if="currentState === 'error'"
      class="mt-4 flex items-start gap-3 rounded-lg border border-[#FFD7D7] bg-[#FFF5F5] p-4 pl-5"
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
