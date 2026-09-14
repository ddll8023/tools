<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  cancelModelDownload,
  fetchModelStatus,
  MINERU_PIPELINE_MODEL_ID,
  startModelDownload,
} from '@/api/settings'
import type { ModelStatus, ModelStatusItem } from '@/api/settings'

const model = ref<ModelStatusItem | null>(null)
const loading = ref(true)
const actionPending = ref(false)
const errorMessage = ref('')
let pollTimer: number | undefined

const statusLabels: Record<ModelStatus, string> = {
  not_downloaded: '未下载',
  downloading: '下载中',
  ready: '已就绪',
  failed: '下载失败',
  interrupted: '上次下载中断',
  cancelled: '已取消',
}

const statusLabel = computed(() => model.value ? statusLabels[model.value.status] : '读取中')
const isDownloading = computed(() => model.value?.status === 'downloading')
const actionLabel = computed(() => {
  if (isDownloading.value) return '下载中'
  if (model.value?.status === 'ready') return '重新检查'
  if (model.value?.status === 'interrupted') return '继续下载'
  if (model.value?.status === 'failed' || model.value?.status === 'cancelled') return '重试下载'
  return '下载模型'
})

function clearPollTimer() {
  if (pollTimer !== undefined) {
    window.clearTimeout(pollTimer)
    pollTimer = undefined
  }
}

function scheduleStatusPoll() {
  clearPollTimer()
  if (!isDownloading.value) return
  pollTimer = window.setTimeout(async () => {
    await loadStatus(false)
    scheduleStatusPoll()
  }, 1500)
}

async function loadStatus(showError = true) {
  try {
    const models = await fetchModelStatus()
    model.value = models.find((item) => item.model_id === MINERU_PIPELINE_MODEL_ID) ?? null
    if (!model.value && showError) errorMessage.value = '未找到可管理的模型。'
    else if (showError) errorMessage.value = ''
  } catch (error) {
    if (showError) {
      errorMessage.value = error instanceof Error ? error.message : '模型状态读取失败，请稍后重试。'
    }
  } finally {
    loading.value = false
  }
}

async function handleDownload() {
  if (actionPending.value || isDownloading.value || !model.value) return
  actionPending.value = true
  errorMessage.value = ''
  try {
    model.value = await startModelDownload(model.value.model_id)
    scheduleStatusPoll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '模型下载启动失败，请稍后重试。'
  } finally {
    actionPending.value = false
  }
}

async function handleCancel() {
  if (actionPending.value || !isDownloading.value || !model.value) return
  actionPending.value = true
  try {
    model.value = await cancelModelDownload(model.value.model_id)
    clearPollTimer()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '取消下载失败，请稍后重试。'
  } finally {
    actionPending.value = false
  }
}

function formatBytes(bytes: number): string {
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`
  if (bytes >= 1024 ** 2) return `${Math.round(bytes / 1024 ** 2)} MB`
  return `${Math.round(bytes / 1024)} KB`
}

onMounted(async () => {
  await loadStatus()
  scheduleStatusPoll()
})

onBeforeUnmount(clearPollTimer)
</script>

<template>
  <main class="mx-auto w-full max-w-[900px] px-8 py-8">
    <header class="mb-7">
      <p class="mb-2 text-[11px] font-semibold uppercase tracking-[1.5px] text-primary-dark">本地运行环境</p>
      <h1 class="text-[25px] font-bold tracking-[-0.3px]">设置</h1>
      <p class="mt-2 text-[13px] leading-relaxed text-text-secondary">
        模型只在你主动点击下载后准备，下载和处理都在本地完成。
      </p>
    </header>

    <p v-if="errorMessage" class="mb-4 rounded-xl border border-[#F1C4C4] bg-[#FFF4F4] px-4 py-3 text-[13px] text-[#B42318]" role="alert">
      {{ errorMessage }}
    </p>

    <section class="overflow-hidden rounded-2xl border border-border bg-surface shadow-sm" aria-labelledby="model-title">
      <div class="border-b border-border bg-[#FFFCF6] px-6 py-5">
        <div class="flex items-start justify-between gap-4">
          <div class="flex items-start gap-3">
            <div class="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-primary-light text-primary-dark">
              <font-awesome-icon :icon="['fas', 'wand-magic-sparkles']" />
            </div>
            <div>
              <div class="flex flex-wrap items-center gap-2">
                <h2 id="model-title" class="text-[16px] font-semibold">MinerU Pipeline</h2>
                <span class="rounded-full bg-[#F0F5E9] px-2 py-0.5 text-[11px] font-medium text-[#4A8B2F]">PDF 深度解析</span>
              </div>
              <p class="mt-1 text-[12px] text-text-secondary">识别复杂排版、扫描件、多栏布局和表格结构。</p>
            </div>
          </div>
          <span
            class="flex flex-shrink-0 items-center gap-1.5 rounded-full bg-bg px-2.5 py-1 text-[11px] font-medium text-text-secondary"
            :class="model?.status === 'ready' ? 'text-[#4A8B2F]' : model?.status === 'failed' ? 'text-error' : ''"
          >
            <span class="h-1.5 w-1.5 rounded-full bg-text-tertiary" :class="{
              'bg-success': model?.status === 'ready',
              'bg-primary': model?.status === 'downloading',
              'bg-error': model?.status === 'failed',
            }"></span>
            {{ statusLabel }}
          </span>
        </div>
      </div>

      <div class="space-y-5 px-6 py-6">
        <div v-if="loading" class="h-12 animate-pulse rounded-lg bg-hover" aria-label="正在读取模型状态"></div>

        <template v-else-if="model">
          <div v-if="model.status === 'downloading'" class="rounded-xl border border-[#F6D99F] bg-[#FFF9EC] px-4 py-3" role="status" aria-live="polite">
            <div class="mb-2 flex items-center justify-between gap-3 text-[12px]">
              <span class="font-medium text-[#8B6508]">{{ model.stage }}</span>
              <span v-if="model.progress !== null" class="text-[#A77A10]">{{ model.progress }}%</span>
            </div>
            <div class="h-1.5 overflow-hidden rounded-full bg-[#F6E8C5]">
              <div
                v-if="model.progress !== null"
                class="h-full rounded-full bg-primary transition-all duration-300"
                :style="{ width: `${model.progress}%` }"
              ></div>
              <div v-else class="h-full w-1/3 animate-pulse rounded-full bg-primary"></div>
            </div>
          </div>

          <p v-else-if="model.error" class="rounded-xl bg-[#FFF4F4] px-4 py-3 text-[12px] text-[#B42318]" role="status">
            {{ model.error }}
          </p>

          <dl class="grid gap-3 text-[12px] sm:grid-cols-3">
            <div class="rounded-xl bg-bg px-4 py-3">
              <dt class="text-text-tertiary">下载来源</dt>
              <dd class="mt-1 font-medium">{{ model.source }}</dd>
            </div>
            <div class="rounded-xl bg-bg px-4 py-3">
              <dt class="text-text-tertiary">预计占用</dt>
              <dd class="mt-1 font-medium">约 {{ formatBytes(model.approx_size_bytes) }}</dd>
            </div>
            <div class="rounded-xl bg-bg px-4 py-3 sm:col-span-1">
              <dt class="text-text-tertiary">保存位置</dt>
              <dd class="mt-1 break-all font-medium" :title="model.path">{{ model.path }}</dd>
            </div>
          </dl>

          <div class="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-5">
            <p class="max-w-[540px] text-[11px] leading-relaxed text-text-tertiary">
              首次下载需要网络和约 2GB 可用磁盘空间。模型未准备好时，PDF 深度解析不会自动下载。
            </p>
            <div class="flex flex-shrink-0 gap-2">
              <button
                v-if="model.status === 'downloading'"
                type="button"
                class="rounded-lg border border-border bg-surface px-3 py-2 text-[12px] text-text-secondary transition-colors hover:border-error hover:text-error disabled:cursor-not-allowed disabled:opacity-50"
                :disabled="actionPending"
                @click="handleCancel"
              >
                取消下载
              </button>
              <button
                v-else
                type="button"
                class="rounded-lg bg-primary px-4 py-2 text-[12px] font-medium text-white transition-colors hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-50"
                :disabled="actionPending || !model"
                @click="handleDownload"
              >
                {{ actionLabel }}
              </button>
            </div>
          </div>
        </template>
      </div>
    </section>
  </main>
</template>
