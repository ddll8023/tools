<!--
  证件照工具页
  功能描述：上传单人照片 → 选择规格和背景 → 本地处理 → 微调与下载
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import {
  downloadIdPhotoFile,
  fetchIdPhotoFile,
  processIdPhoto,
  renderIdPhoto,
} from '@/api/tools'
import type { IdPhotoFileItem, IdPhotoResponse } from '@/api/tools'

type PageState = 'upload' | 'processing' | 'result' | 'error'

type TemplateOption = {
  id: string
  label: string
  description: string
  width?: number
  height?: number
}

type BackgroundOption = {
  value: string
  label: string
  swatch: string
}

const MAX_FILE_SIZE = 20 * 1024 * 1024
const ACCEPTED_EXTENSIONS = ['jpg', 'jpeg', 'png', 'webp']

const templates: TemplateOption[] = [
  {
    id: 'one-inch',
    label: '一寸',
    description: '25×35 mm · 295×413 px',
    width: 295,
    height: 413,
  },
  {
    id: 'small-two-inch',
    label: '小二寸',
    description: '35×45 mm · 413×531 px',
    width: 413,
    height: 531,
  },
  {
    id: 'two-inch',
    label: '二寸',
    description: '35×49 mm · 413×579 px',
    width: 413,
    height: 579,
  },
  {
    id: 'custom',
    label: '自定义',
    description: '输入目标像素尺寸',
  },
]

const backgrounds: BackgroundOption[] = [
  { value: 'white', label: '白色', swatch: '#FFFFFF' },
  { value: 'blue', label: '蓝色', swatch: '#438EDB' },
  { value: 'red', label: '红色', swatch: '#D9001B' },
  { value: 'custom', label: '自定义', swatch: '#8B8B86' },
]

const fileInput = ref<HTMLInputElement | null>(null)
const currentState = ref<PageState>('upload')
const errorMessage = ref('')
const renderError = ref('')
const selectedFile = ref<File | null>(null)
const templateId = ref('one-inch')
const customWidth = ref(295)
const customHeight = ref(413)
const backgroundSelection = ref('white')
const customColor = ref('#438EDB')
const includeLayout = ref(true)
const quality = ref(95)
const dpi = ref(300)
const maxFileSizeKb = ref(0)
const cropScale = ref(1)
const offsetX = ref(0)
const offsetY = ref(0)
const taskId = ref('')
const result = ref<IdPhotoResponse | null>(null)
const previewUrl = ref<string | null>(null)
const isRendering = ref(false)
let operationId = 0

const selectedBackground = computed(() =>
  backgroundSelection.value === 'custom'
    ? customColor.value.toUpperCase()
    : backgroundSelection.value,
)
const maxFileSizeLimit = computed(() =>
  maxFileSizeKb.value > 0 ? maxFileSizeKb.value : undefined,
)
const canProcess = computed(() => {
  if (!selectedFile.value || currentState.value === 'processing') return false
  if (templateId.value !== 'custom') return true
  return (
    Number.isInteger(customWidth.value) &&
    Number.isInteger(customHeight.value) &&
    customWidth.value >= 80 &&
    customHeight.value >= 80 &&
    customWidth.value < customHeight.value
  )
})

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function validateFile(file: File): string | null {
  const extension = file.name.toLowerCase().split('.').pop()
  if (!extension || !ACCEPTED_EXTENSIONS.includes(extension)) {
    return '仅支持 JPG、PNG 和 WebP 图片'
  }
  if (file.size > MAX_FILE_SIZE) {
    return '文件过大，单张图片不能超过 20MB'
  }
  if (file.size === 0) return '不能选择空文件'
  return null
}

function chooseFile(file: File) {
  const validationError = validateFile(file)
  if (validationError) {
    errorMessage.value = validationError
    currentState.value = 'error'
    return
  }
  selectedFile.value = file
  errorMessage.value = ''
  renderError.value = ''
  currentState.value = 'upload'
}

function onFileChange(event: Event) {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (file) chooseFile(file)
  input.value = ''
}

function onDrop(event: DragEvent) {
  event.preventDefault()
  const file = event.dataTransfer?.files?.[0]
  if (file) chooseFile(file)
}

function onDragOver(event: DragEvent) {
  event.preventDefault()
}

async function loadPreview(response: IdPhotoResponse, currentOperation: number) {
  const standardFile = response.files.find((file) => file.kind === 'standard')
  if (!standardFile) throw new Error('标准证件照结果不存在')

  const blob = await fetchIdPhotoFile(response.task_id, standardFile.index)
  if (currentOperation !== operationId) return

  const nextUrl = URL.createObjectURL(blob)
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = nextUrl
}

async function handleProcess() {
  if (!canProcess.value || !selectedFile.value) return

  const currentOperation = ++operationId
  currentState.value = 'processing'
  errorMessage.value = ''
  renderError.value = ''

  try {
    const processed = await processIdPhoto(
      selectedFile.value,
      templateId.value,
      templateId.value === 'custom' ? customWidth.value : undefined,
      templateId.value === 'custom' ? customHeight.value : undefined,
      selectedBackground.value,
      includeLayout.value,
      quality.value,
      dpi.value,
      maxFileSizeLimit.value,
    )
    if (currentOperation !== operationId) return

    result.value = processed
    taskId.value = processed.task_id
    await loadPreview(processed, currentOperation)
    if (currentOperation === operationId) currentState.value = 'result'
  } catch (error) {
    if (currentOperation !== operationId) return
    errorMessage.value = getErrorMessage(error, '证件照处理失败，请重试')
    currentState.value = 'error'
  }
}

async function handleRender() {
  if (!taskId.value || !result.value || isRendering.value) return

  const currentOperation = ++operationId
  isRendering.value = true
  renderError.value = ''

  try {
    const rendered = await renderIdPhoto({
      task_id: taskId.value,
      background_color: selectedBackground.value,
      crop_scale: cropScale.value,
      offset_x: offsetX.value,
      offset_y: offsetY.value,
      include_layout: includeLayout.value,
      quality: quality.value,
      dpi: dpi.value,
      max_file_size_kb: maxFileSizeLimit.value ?? null,
    })
    if (currentOperation !== operationId) return

    result.value = rendered
    await loadPreview(rendered, currentOperation)
  } catch (error) {
    if (currentOperation === operationId) {
      renderError.value = getErrorMessage(error, '重新渲染失败，请重试')
    }
  } finally {
    if (currentOperation === operationId) isRendering.value = false
  }
}

function fileLabel(file: IdPhotoFileItem): string {
  if (file.kind === 'standard') return '标准电子照'
  if (file.kind === 'hd') return '高清电子照'
  return '六寸排版照'
}

async function handleDownload(file: IdPhotoFileItem) {
  if (!taskId.value) return
  try {
    await downloadIdPhotoFile(taskId.value, file.index, file.filename)
  } catch (error) {
    renderError.value = getErrorMessage(error, '下载失败，请重试')
  }
}

function resetUpload() {
  operationId += 1
  currentState.value = 'upload'
  errorMessage.value = ''
  renderError.value = ''
  selectedFile.value = null
  taskId.value = ''
  result.value = null
  isRendering.value = false
  quality.value = 95
  dpi.value = 300
  maxFileSizeKb.value = 0
  cropScale.value = 1
  offsetX.value = 0
  offsetY.value = 0
  if (previewUrl.value) {
    URL.revokeObjectURL(previewUrl.value)
    previewUrl.value = null
  }
}

onBeforeUnmount(() => {
  operationId += 1
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
})
</script>

<template>
  <main class="mx-auto w-full max-w-[900px] py-7">
    <section class="mb-5 rounded-2xl border border-border bg-surface p-8">
      <div class="mb-[18px] text-[13px] font-semibold uppercase tracking-[0.5px] text-text-secondary">
        <font-awesome-icon :icon="['fas', 'id-card']" class="mr-1.5" />
        选择照片
      </div>

      <label
        class="block cursor-pointer rounded-xl border-2 border-dashed border-border py-10 text-center transition-all duration-250 hover:border-primary hover:bg-primary-light"
        @dragover="onDragOver"
        @drop="onDrop"
      >
        <div class="mb-3 text-[38px] text-text-tertiary">
          <font-awesome-icon :icon="['fas', 'id-card']" />
        </div>
        <h1 class="mb-1.5 text-[15px] font-semibold">将单人照片拖拽到此处</h1>
        <p class="mb-4 text-[13px] text-text-secondary">或点击选择本地图片</p>
        <span class="inline-flex items-center gap-2 rounded-lg bg-primary px-[22px] py-[9px] text-[13px] font-medium text-white">
          <font-awesome-icon :icon="['fas', 'upload']" />
          选择图片
        </span>
        <input
          ref="fileInput"
          type="file"
          accept=".jpg,.jpeg,.png,.webp"
          class="sr-only"
          @change="onFileChange"
        />
        <div class="mt-3.5 text-[12px] text-text-tertiary">
          支持 JPG / PNG / WebP，单张最大 20MB；照片仅在本地处理
        </div>
      </label>

      <div
        v-if="selectedFile"
        class="mt-4 flex items-center gap-3 rounded-lg bg-[#F9F9F6] px-4 py-3 text-[13px]"
      >
        <font-awesome-icon :icon="['far', 'file-image']" class="text-primary" />
        <span class="flex-1 truncate font-medium">{{ selectedFile.name }}</span>
        <span class="text-text-secondary">{{ formatSize(selectedFile.size) }}</span>
        <button
          type="button"
          class="cursor-pointer text-text-tertiary transition-all duration-200 hover:text-error"
          aria-label="移除已选照片"
          @click="resetUpload"
        >
          <font-awesome-icon :icon="['fas', 'xmark']" />
        </button>
      </div>
    </section>

    <form
      v-if="currentState === 'upload' || currentState === 'error'"
      class="mb-5 rounded-2xl border border-border bg-surface p-8"
      @submit.prevent="handleProcess"
    >
      <div class="mb-[18px] text-[13px] font-semibold uppercase tracking-[0.5px] text-text-secondary">
        <font-awesome-icon :icon="['fas', 'sliders']" class="mr-1.5" />
        输出设置
      </div>

      <fieldset>
        <legend class="mb-2 text-[13px] font-medium">照片规格</legend>
        <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <button
            v-for="template in templates"
            :key="template.id"
            type="button"
            class="rounded-lg border px-3 py-2.5 text-left transition-all duration-200"
            :class="templateId === template.id
              ? 'border-primary bg-primary text-white'
              : 'border-border text-text-secondary hover:border-[#999] hover:text-text'"
            :aria-pressed="templateId === template.id"
            @click="templateId = template.id"
          >
            <span class="block text-[13px] font-medium">{{ template.label }}</span>
            <span class="mt-0.5 block text-[11px] opacity-75">{{ template.description }}</span>
          </button>
        </div>
      </fieldset>

      <div v-if="templateId === 'custom'" class="mt-4 grid grid-cols-2 gap-3">
        <label class="text-[13px] font-medium">
          宽度（px）
          <input
            v-model.number="customWidth"
            type="number"
            min="80"
            max="3000"
            class="mt-2 w-full rounded-lg border border-border bg-transparent px-3 py-2 font-normal outline-none focus:border-primary"
          />
        </label>
        <label class="text-[13px] font-medium">
          高度（px）
          <input
            v-model.number="customHeight"
            type="number"
            min="80"
            max="3000"
            class="mt-2 w-full rounded-lg border border-border bg-transparent px-3 py-2 font-normal outline-none focus:border-primary"
          />
        </label>
      </div>

      <fieldset class="mt-5">
        <legend class="mb-2 text-[13px] font-medium">背景色</legend>
        <div class="flex flex-wrap gap-2">
          <button
            v-for="background in backgrounds"
            :key="background.value"
            type="button"
            class="inline-flex items-center gap-2 rounded-lg border px-3.5 py-2 text-[13px] transition-all duration-200"
            :class="backgroundSelection === background.value
              ? 'border-primary bg-primary-light text-primary-dark'
              : 'border-border text-text-secondary hover:border-[#999] hover:text-text'"
            :aria-pressed="backgroundSelection === background.value"
            @click="backgroundSelection = background.value"
          >
            <span
              class="h-4 w-4 rounded-full border border-black/10"
              :style="{ backgroundColor: background.swatch }"
              aria-hidden="true"
            ></span>
            {{ background.label }}
          </button>
        </div>
        <div v-if="backgroundSelection === 'custom'" class="mt-3 flex items-center gap-3">
          <label class="text-[13px] font-medium" for="custom-background">自定义颜色</label>
          <input id="custom-background" v-model="customColor" type="color" class="h-8 w-12 cursor-pointer rounded border-0 p-0" />
          <code class="text-[12px] text-text-secondary">{{ customColor.toUpperCase() }}</code>
        </div>
      </fieldset>

      <div class="mt-5 grid gap-4 sm:grid-cols-3">
        <label class="text-[13px] font-medium">
          JPEG 质量：{{ quality }}
          <input
            v-model.number="quality"
            type="range"
            min="60"
            max="100"
            class="mt-2 w-full cursor-pointer accent-primary"
          />
        </label>
        <label class="text-[13px] font-medium">
          DPI
          <input
            v-model.number="dpi"
            type="number"
            min="72"
            max="600"
            class="mt-2 w-full rounded-lg border border-border bg-transparent px-3 py-2 font-normal outline-none focus:border-primary"
          />
        </label>
        <label class="text-[13px] font-medium">
          单文件上限（KB）
          <input
            v-model.number="maxFileSizeKb"
            type="number"
            min="0"
            max="2048"
            placeholder="0 表示不限"
            class="mt-2 w-full rounded-lg border border-border bg-transparent px-3 py-2 font-normal outline-none focus:border-primary"
          />
        </label>
      </div>
      <p class="mt-2 text-[11px] text-text-tertiary">文件大小上限为可选压缩目标，0 表示不限制。</p>

      <label class="mt-5 flex cursor-pointer items-center gap-2 text-[13px] text-text-secondary">
        <input v-model="includeLayout" type="checkbox" class="h-4 w-4 accent-primary" />
        同时生成六寸排版照
      </label>

      <button
        type="submit"
        class="mt-6 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-primary px-[22px] py-[11px] text-[14px] font-medium text-white transition-all duration-200 hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-50"
        :disabled="!canProcess"
      >
        <font-awesome-icon :icon="['fas', 'wand-magic-sparkles']" />
        开始生成证件照
      </button>
    </form>

    <section
      v-if="currentState === 'processing'"
      class="mb-5 rounded-2xl border border-border bg-surface p-8"
      aria-busy="true"
    >
      <div class="mb-[18px] text-[13px] font-semibold uppercase tracking-[0.5px] text-text-secondary">
        <font-awesome-icon :icon="['far', 'hourglass-half']" class="mr-1.5" />
        正在本地处理
      </div>
      <div class="mb-5 h-1.5 w-full overflow-hidden rounded-full bg-[#F0F0EC]">
        <div class="h-full w-full animate-pulse rounded-full bg-primary"></div>
      </div>
      <div class="flex items-center gap-2.5 text-[13px] font-medium" role="status">
        <span class="w-5 text-center text-sm text-primary">
          <font-awesome-icon :icon="['fas', 'spinner']" spin />
        </span>
        正在检测人脸并生成抠图，首次处理可能需要一些时间……
      </div>
    </section>

    <section
      v-if="currentState === 'result' && result"
      class="mb-5 rounded-2xl border border-border bg-surface p-8"
    >
      <div class="mb-[18px] text-[13px] font-semibold uppercase tracking-[0.5px] text-text-secondary">
        <font-awesome-icon :icon="['fas', 'check-circle']" class="mr-1.5" />
        生成完成
      </div>

      <div class="grid gap-6 md:grid-cols-[minmax(0,1fr)_280px]">
        <div>
          <div class="flex min-h-[360px] items-center justify-center rounded-xl bg-[#F4F4F0] p-5">
            <img
              v-if="previewUrl"
              :src="previewUrl"
              :alt="`${result.template_name} ${result.background_color} 背景预览`"
              class="max-h-[520px] max-w-full rounded-md border border-border object-contain shadow-sm"
            />
            <span v-else class="text-sm text-text-tertiary">预览加载中……</span>
          </div>
          <p class="mt-3 text-[12px] leading-relaxed text-text-tertiary">
            当前输出：{{ result.template_name }}，{{ result.width }}×{{ result.height }} px，背景 {{ result.background_color }}。结果仅按所选模板生成，不代表目标机构的最终合规结论。
          </p>
        </div>

        <div class="space-y-4">
          <div>
            <h2 class="mb-2 text-[13px] font-semibold">结果微调</h2>
            <label class="block text-[12px] text-text-secondary">
              裁切范围：{{ Math.round(cropScale * 100) }}%
              <input
                type="range"
                min="0.85"
                max="1.25"
                step="0.01"
                :value="cropScale"
                class="mt-2 w-full cursor-pointer accent-primary"
                @input="cropScale = Number(($event.target as HTMLInputElement).value)"
              />
            </label>
            <label class="mt-3 block text-[12px] text-text-secondary">
              水平位置：{{ Math.round(offsetX * 100) }}%
              <input
                type="range"
                min="-0.15"
                max="0.15"
                step="0.01"
                :value="offsetX"
                class="mt-2 w-full cursor-pointer accent-primary"
                @input="offsetX = Number(($event.target as HTMLInputElement).value)"
              />
            </label>
            <label class="mt-3 block text-[12px] text-text-secondary">
              垂直位置：{{ Math.round(offsetY * 100) }}%
              <input
                type="range"
                min="-0.15"
                max="0.15"
                step="0.01"
                :value="offsetY"
                class="mt-2 w-full cursor-pointer accent-primary"
                @input="offsetY = Number(($event.target as HTMLInputElement).value)"
              />
            </label>
          </div>

          <div>
            <label class="mb-2 block text-[12px] font-medium" for="result-background">重新选择背景色</label>
            <select
              id="result-background"
              v-model="backgroundSelection"
              class="w-full rounded-lg border border-border bg-transparent px-3 py-2 text-[13px] outline-none focus:border-primary"
            >
              <option v-for="background in backgrounds" :key="background.value" :value="background.value">
                {{ background.label }}
              </option>
            </select>
            <input
              v-if="backgroundSelection === 'custom'"
              v-model="customColor"
              type="color"
              class="mt-2 h-8 w-full cursor-pointer rounded border-0 p-0"
              aria-label="选择结果背景色"
            />
          </div>

          <div class="mt-4 grid grid-cols-2 gap-3">
            <label class="text-[12px] text-text-secondary">
              JPEG 质量：{{ quality }}
              <input v-model.number="quality" type="range" min="60" max="100" class="mt-2 w-full cursor-pointer accent-primary" />
            </label>
            <label class="text-[12px] text-text-secondary">
              DPI
              <input v-model.number="dpi" type="number" min="72" max="600" class="mt-1.5 w-full rounded-lg border border-border bg-transparent px-2.5 py-1.5 text-[13px] outline-none focus:border-primary" />
            </label>
            <label class="col-span-2 text-[12px] text-text-secondary">
              单文件上限（KB，0 表示不限）
              <input v-model.number="maxFileSizeKb" type="number" min="0" max="2048" class="mt-1.5 w-full rounded-lg border border-border bg-transparent px-2.5 py-1.5 text-[13px] outline-none focus:border-primary" />
            </label>
          </div>

          <button
            type="button"
            class="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-primary px-4 py-2 text-[13px] font-medium text-primary transition-all duration-200 hover:bg-primary-light disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="isRendering"
            @click="handleRender"
          >
            <font-awesome-icon :icon="['fas', 'rotate']" :spin="isRendering" />
            {{ isRendering ? '正在更新结果……' : '应用调整' }}
          </button>
        </div>
      </div>

      <div v-if="renderError" class="mt-4 rounded-lg border border-[#FFD7D7] bg-[#FFF5F5] p-3 text-[13px] text-error" role="alert">
        {{ renderError }}
      </div>

      <div class="mt-6 space-y-2">
        <div
          v-for="file in result.files"
          :key="file.index"
          class="flex items-center gap-3 rounded-lg border border-border bg-[#F9F9F6] px-4 py-3 text-[13px]"
        >
          <font-awesome-icon :icon="['far', 'file-image']" class="text-primary" />
          <span class="flex-1 min-w-0">
            <span class="font-medium">{{ fileLabel(file) }}</span>
            <span class="ml-2 truncate text-text-secondary">{{ file.filename }}</span>
          </span>
          <span class="text-text-secondary">{{ formatSize(file.file_size) }}</span>
          <button
            type="button"
            class="cursor-pointer text-primary transition-all duration-200 hover:text-primary-dark"
            :disabled="isRendering"
            :aria-label="`下载${fileLabel(file)}`"
            @click="handleDownload(file)"
          >
            <font-awesome-icon :icon="['fas', 'download']" />
          </button>
        </div>
      </div>

      <div class="mt-5 flex gap-3">
        <button
          type="button"
          class="inline-flex items-center gap-2 rounded-lg border border-border bg-transparent px-[22px] py-[9px] text-[13px] font-medium text-text-secondary transition-all duration-200 hover:border-[#999] hover:text-text"
          @click="resetUpload"
        >
          <font-awesome-icon :icon="['fas', 'rotate']" />
          重新上传
        </button>
      </div>
    </section>

    <section
      v-if="currentState === 'error'"
      class="mt-4 flex items-start gap-3 rounded-lg border border-[#FFD7D7] bg-[#FFF5F5] p-4 pl-5"
      role="alert"
    >
      <font-awesome-icon :icon="['far', 'circle-xmark']" class="mt-0.5 text-lg text-error" />
      <div class="flex-1">
        <h2 class="mb-1 text-[14px] font-semibold">处理失败</h2>
        <p class="text-[13px] text-text-secondary">{{ errorMessage }}</p>
      </div>
      <button
        type="button"
        class="cursor-pointer rounded-lg border border-border bg-transparent px-3 py-1.5 text-xs text-text-secondary transition-all duration-200 hover:border-[#999] hover:text-text"
        @click="resetUpload"
      >
        重新上传
      </button>
    </section>

    <footer class="mt-5 text-center text-[12px] text-text-tertiary">
      <font-awesome-icon :icon="['far', 'clock']" class="mr-1" />
      本地处理，照片不会上传云端
    </footer>
  </main>
</template>
