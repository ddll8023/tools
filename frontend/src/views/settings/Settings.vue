<!-- 设置页：展示本地模型状态并提供受保护的资源管理操作。 -->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  cancelModelDownload,
  deleteModel,
  fetchModelStatus,
  ID_PHOTO_MODEL_ID,
  MINERU_PIPELINE_MODEL_ID,
  startModelDownload,
} from '@/api/settings'
import type { ModelStatus, ModelStatusItem } from '@/api/settings'
import {
  fetchLanPreferences,
  fetchLanReceiveRecords,
  updateLanPreferences,
} from '@/api/lanTransfer'
import type { LanPreferences, LanReceiveRecord } from '@/api/lanTransfer'

const model = ref<ModelStatusItem | null>(null)
const idPhotoModel = ref<ModelStatusItem | null>(null)
const loading = ref(true)
const actionPending = ref(false)
const errorMessage = ref('')
const pathCopied = ref(false)
const lanPreferences = ref<LanPreferences | null>(null)
const lanDeviceName = ref('')
const lanRecords = ref<LanReceiveRecord[]>([])
const lanLoading = ref(true)
const lanSaving = ref(false)
const lanError = ref('')
const lanSaved = ref(false)
const lanPathCopied = ref('')
let pollTimer: number | undefined
let pathCopyTimer: number | undefined
let lanSaveTimer: number | undefined
let lanCopyTimer: number | undefined

const statusLabels: Record<ModelStatus, string> = {
  not_downloaded: '未下载',
  downloading: '下载中',
  ready: '已就绪',
  failed: '下载失败',
  interrupted: '上次下载中断',
  cancelled: '已取消',
  incomplete: '资源不完整',
  unavailable: '依赖不可用',
}

const statusLabel = computed(() => model.value ? statusLabels[model.value.status] : '读取中')
const isDownloading = computed(() => model.value?.status === 'downloading')
const isIdPhotoDownloading = computed(() => idPhotoModel.value?.status === 'downloading')
const isAnyModelDownloading = computed(() => isDownloading.value || isIdPhotoDownloading.value)
const idPhotoStatusClasses: Record<ModelStatus, { text: string; dot: string }> = {
  not_downloaded: { text: 'text-[#8B6508]', dot: 'bg-[#D99A18]' },
  downloading: { text: 'text-primary-dark', dot: 'bg-primary' },
  ready: { text: 'text-[#4A8B2F]', dot: 'bg-success' },
  failed: { text: 'text-error', dot: 'bg-error' },
  interrupted: { text: 'text-[#8B6508]', dot: 'bg-[#D99A18]' },
  cancelled: { text: 'text-[#8B6508]', dot: 'bg-[#D99A18]' },
  incomplete: { text: 'text-[#8B6508]', dot: 'bg-[#D99A18]' },
  unavailable: { text: 'text-error', dot: 'bg-error' },
}
const idPhotoStatusClass = computed(() => idPhotoModel.value
  ? idPhotoStatusClasses[idPhotoModel.value.status]
  : { text: 'text-text-secondary', dot: 'bg-text-tertiary' })
const idPhotoActionLabel = computed(() => {
  if (idPhotoModel.value?.status === 'failed' || idPhotoModel.value?.status === 'cancelled' || idPhotoModel.value?.status === 'incomplete') {
    return '重试下载'
  }
  return '下载并准备模型'
})
const idPhotoNeedsManualSetup = computed(() => Boolean(
  idPhotoModel.value
  && !idPhotoModel.value.can_download
  && ['not_downloaded', 'incomplete'].includes(idPhotoModel.value.status),
))
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
  if (!isAnyModelDownloading.value) return
  pollTimer = window.setTimeout(async () => {
    await loadStatus(false)
    scheduleStatusPoll()
  }, 1500)
}

async function loadStatus(showError = true) {
  try {
    const models = await fetchModelStatus()
    model.value = models.find((item) => item.model_id === MINERU_PIPELINE_MODEL_ID) ?? null
    idPhotoModel.value = models.find((item) => item.model_id === ID_PHOTO_MODEL_ID) ?? null
    if ((!model.value || !idPhotoModel.value) && showError) errorMessage.value = '部分模型状态未返回。'
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

async function handleIdPhotoDownload() {
  if (actionPending.value || isIdPhotoDownloading.value || !idPhotoModel.value?.can_download) return
  actionPending.value = true
  errorMessage.value = ''
  try {
    idPhotoModel.value = await startModelDownload(ID_PHOTO_MODEL_ID)
    scheduleStatusPoll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '证件照模型下载启动失败，请稍后重试。'
  } finally {
    actionPending.value = false
  }
}

async function handleCancelIdPhotoDownload() {
  if (actionPending.value || !isIdPhotoDownloading.value) return
  actionPending.value = true
  try {
    idPhotoModel.value = await cancelModelDownload(ID_PHOTO_MODEL_ID)
    scheduleStatusPoll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '取消证件照模型下载失败，请稍后重试。'
  } finally {
    actionPending.value = false
  }
}

async function handleCancel() {
  if (actionPending.value || !isDownloading.value || !model.value) return
  actionPending.value = true
  try {
    model.value = await cancelModelDownload(model.value.model_id)
    scheduleStatusPoll()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '取消下载失败，请稍后重试。'
  } finally {
    actionPending.value = false
  }
}

async function copyPhotoModelPath() {
  const path = idPhotoModel.value?.path
  if (!path) return
  try {
    await navigator.clipboard.writeText(path)
    pathCopied.value = true
    if (pathCopyTimer !== undefined) window.clearTimeout(pathCopyTimer)
    pathCopyTimer = window.setTimeout(() => {
      pathCopied.value = false
      pathCopyTimer = undefined
    }, 1500)
  } catch {
    errorMessage.value = '复制路径失败，请手动选择并复制。'
  }
}

async function handleDelete(item: ModelStatusItem) {
  if (actionPending.value || !item.can_delete) return
  const warning = item.model_id === MINERU_PIPELINE_MODEL_ID
    ? '删除 MinerU 模型后，PDF 深度解析需重新下载约 2GB 模型才能使用。确定删除吗？'
    : '删除后证件照工具将暂不可用，可从设置页重新下载或手动准备模型。确定删除吗？'
  if (!window.confirm(warning)) return

  actionPending.value = true
  errorMessage.value = ''
  try {
    const updated = await deleteModel(item.model_id)
    if (updated.model_id === MINERU_PIPELINE_MODEL_ID) model.value = updated
    else idPhotoModel.value = updated
    await loadStatus(false)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '模型删除失败，请稍后重试。'
    await loadStatus(false)
  } finally {
    actionPending.value = false
  }
}

function formatBytes(bytes: number | null): string {
  if (bytes === null) return '未统计'
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`
  if (bytes >= 1024 ** 2) return `${Math.round(bytes / 1024 ** 2)} MB`
  return `${Math.round(bytes / 1024)} KB`
}

/** 读取投送偏好与接收记录；两者任一失败只影响各自区块。 */
async function loadLanSettings() {
  lanLoading.value = true
  try {
    const preferences = await fetchLanPreferences()
    lanPreferences.value = preferences
    lanDeviceName.value = preferences.device_name
  } catch (error) {
    lanError.value = error instanceof Error ? error.message : '读取投送设置失败'
  }
  try {
    lanRecords.value = await fetchLanReceiveRecords()
  } catch (error) {
    lanError.value = error instanceof Error ? error.message : '读取接收记录失败'
  }
  lanLoading.value = false
}

function flashLanSaved() {
  lanSaved.value = true
  if (lanSaveTimer !== undefined) window.clearTimeout(lanSaveTimer)
  lanSaveTimer = window.setTimeout(() => {
    lanSaved.value = false
    lanSaveTimer = undefined
  }, 1500)
}

function reportLanError(error: unknown, fallback: string) {
  lanError.value = error instanceof Error && error.message ? error.message : fallback
}

async function saveLanDeviceName() {
  if (lanSaving.value) return
  lanSaving.value = true
  lanError.value = ''
  try {
    const preferences = await updateLanPreferences({ device_name: lanDeviceName.value })
    lanPreferences.value = preferences
    lanDeviceName.value = preferences.device_name
    flashLanSaved()
  } catch (error) {
    reportLanError(error, '保存设备名失败')
  } finally {
    lanSaving.value = false
  }
}

async function pickLanReceiveDir() {
  if (lanSaving.value) return
  const pickDirectory = window.desktopApi?.fileDialog?.pickDirectory
  if (!pickDirectory) {
    lanError.value = '请通过工具盒子桌面应用选择接收目录'
    return
  }

  lanSaving.value = true
  lanError.value = ''
  try {
    const picked = await pickDirectory()
    if (picked) {
      lanPreferences.value = await updateLanPreferences({ receive_dir: picked })
      flashLanSaved()
    }
  } catch (error) {
    reportLanError(error, '保存接收目录失败')
  } finally {
    lanSaving.value = false
  }
}

/** 清空接收目录设置，回退到默认的下载目录。 */
async function resetLanReceiveDir() {
  if (lanSaving.value) return
  lanSaving.value = true
  lanError.value = ''
  try {
    lanPreferences.value = await updateLanPreferences({ receive_dir: '' })
    flashLanSaved()
  } catch (error) {
    reportLanError(error, '恢复默认接收目录失败')
  } finally {
    lanSaving.value = false
  }
}

async function copyLanPath(path: string) {
  try {
    await navigator.clipboard.writeText(path)
    lanPathCopied.value = path
    if (lanCopyTimer !== undefined) window.clearTimeout(lanCopyTimer)
    lanCopyTimer = window.setTimeout(() => {
      lanPathCopied.value = ''
      lanCopyTimer = undefined
    }, 1500)
  } catch {
    lanError.value = '复制路径失败，请手动选择并复制。'
  }
}

onMounted(async () => {
  await loadStatus()
  scheduleStatusPoll()
  await loadLanSettings()
})

onBeforeUnmount(() => {
  clearPollTimer()
  if (pathCopyTimer !== undefined) window.clearTimeout(pathCopyTimer)
  if (lanSaveTimer !== undefined) window.clearTimeout(lanSaveTimer)
  if (lanCopyTimer !== undefined) window.clearTimeout(lanCopyTimer)
})
</script>

<template>
  <main class="mx-auto w-full max-w-[900px] px-8 py-8">
    <header class="mb-7">
      <p class="mb-2 text-[11px] font-semibold uppercase tracking-[1.5px] text-primary-dark">本地运行环境</p>
      <h1 class="text-[25px] font-bold tracking-[-0.3px]">设置</h1>
      <p class="mt-2 text-[13px] leading-relaxed text-text-secondary">
        可查看并按需准备 MinerU 与证件照模型；仅可删除用户数据目录中的模型资源。
        局域网投送的设备名与接收目录也在这里设置。
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
              <dt class="text-text-tertiary">资源来源</dt>
              <dd class="mt-1 font-medium">{{ model.source }}</dd>
            </div>
            <div v-if="model.approx_size_bytes !== null" class="rounded-xl bg-bg px-4 py-3">
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
              <button
                v-if="model.can_delete"
                type="button"
                class="rounded-lg border border-error px-3 py-2 text-[12px] font-medium text-error transition-colors hover:bg-[#FFF4F4] disabled:cursor-not-allowed disabled:opacity-50"
                :disabled="actionPending"
                @click="handleDelete(model)"
              >
                删除模型
              </button>
            </div>
            <p v-if="!model.can_delete && model.delete_reason" class="basis-full text-right text-[11px] text-text-tertiary">
              {{ model.delete_reason }}
            </p>
          </div>
        </template>
      </div>
    </section>

    <section class="mt-4 overflow-hidden rounded-2xl border border-border bg-surface shadow-sm" aria-labelledby="id-photo-model-title">
      <div class="border-b border-border bg-[#FFFCF6] px-6 py-5">
        <div class="flex items-start justify-between gap-4">
          <div class="flex items-start gap-3">
            <div class="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-xl bg-primary-light text-primary-dark">
              <font-awesome-icon :icon="['fas', 'id-card']" aria-hidden="true" />
            </div>
            <div>
              <div class="flex flex-wrap items-center gap-2">
                <h2 id="id-photo-model-title" class="text-[16px] font-semibold">证件照模型</h2>
                <span class="rounded-full bg-[#F0F5E9] px-2 py-0.5 text-[11px] font-medium text-[#4A8B2F]">人脸检测与抠图</span>
              </div>
              <p class="mt-1 text-[12px] text-text-secondary">显示当前生效的模型位置；应用内置或自定义资源不会被此页删除。</p>
            </div>
          </div>
          <span
            class="flex flex-shrink-0 items-center gap-1.5 rounded-full bg-bg px-2.5 py-1 text-[11px] font-medium"
            :class="idPhotoStatusClass.text"
          >
            <span class="h-1.5 w-1.5 rounded-full" :class="idPhotoStatusClass.dot"></span>
            {{ idPhotoModel ? statusLabels[idPhotoModel.status] : '读取中' }}
          </span>
        </div>
      </div>

      <div class="space-y-5 px-6 py-6">
        <div v-if="loading" class="h-12 animate-pulse rounded-lg bg-hover" aria-label="正在读取证件照模型状态"></div>
        <template v-else-if="idPhotoModel">
          <div v-if="idPhotoModel.status === 'downloading'" class="rounded-xl border border-[#F6D99F] bg-[#FFF9EC] px-4 py-3" role="status" aria-live="polite">
            <div class="mb-2 flex items-center justify-between gap-3 text-[12px]">
              <span class="font-medium text-[#8B6508]">{{ idPhotoModel.stage }}</span>
              <span v-if="idPhotoModel.progress !== null" class="text-[#A77A10]">{{ idPhotoModel.progress }}%</span>
            </div>
            <div class="h-1.5 overflow-hidden rounded-full bg-[#F6E8C5]">
              <div
                v-if="idPhotoModel.progress !== null"
                class="h-full rounded-full bg-primary transition-all duration-300"
                :style="{ width: `${idPhotoModel.progress}%` }"
              ></div>
              <div v-else class="h-full w-1/3 animate-pulse rounded-full bg-primary"></div>
            </div>
          </div>
          <p
            v-else-if="idPhotoModel.error"
            class="rounded-xl px-4 py-3 text-[12px]"
            :class="idPhotoModel.status === 'failed' || idPhotoModel.status === 'unavailable'
              ? 'bg-[#FFF4F4] text-[#B42318]'
              : 'bg-[#FFF9EC] text-[#8B6508]'"
            role="status"
          >
            {{ idPhotoModel.error }}
          </p>
          <dl class="grid gap-3 text-[12px] sm:grid-cols-2">
            <div class="rounded-xl bg-bg px-4 py-3">
              <dt class="text-text-tertiary">资源来源</dt>
              <dd class="mt-1 font-medium">{{ idPhotoModel.source }}</dd>
            </div>
            <div class="rounded-xl bg-bg px-4 py-3">
              <dt class="text-text-tertiary">模型位置</dt>
              <dd class="mt-1 flex items-start gap-2">
                <span class="min-w-0 flex-1 font-medium [overflow-wrap:anywhere]" :title="idPhotoModel.path">{{ idPhotoModel.path }}</span>
                <button
                  type="button"
                  class="flex-shrink-0 rounded-md px-2 py-1 text-[11px] text-primary-dark transition-colors hover:bg-primary-light focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-primary"
                  :aria-label="pathCopied ? '已复制模型路径' : '复制模型路径'"
                  @click="copyPhotoModelPath"
                >
                  {{ pathCopied ? '已复制' : '复制路径' }}
                </button>
              </dd>
            </div>
          </dl>
          <div class="flex flex-wrap items-center justify-between gap-3 border-t border-border pt-5">
            <div class="max-w-[540px] space-y-1 text-[11px] leading-relaxed text-text-tertiary">
              <p v-if="idPhotoModel.status === 'downloading' || idPhotoModel.can_download">
                下载由你主动发起，需要网络；模型写入用户数据目录，不会自动下载。
              </p>
              <p v-else-if="idPhotoNeedsManualSetup">
                当前资源位于应用内置或自定义目录，设置页不会写入该位置；请按当前模型路径手动准备资源。
              </p>
              <p v-else-if="idPhotoModel.status === 'unavailable'">
                模型文件已齐，但运行依赖不可用；下载模型无法修复此问题。
              </p>
              <p v-else>
                应用内置或自定义目录的资源不会被此页删除；仅用户数据目录中的模型可管理。
              </p>
              <p v-if="!idPhotoModel.can_delete && idPhotoModel.delete_reason" role="status">
                {{ idPhotoModel.delete_reason }}
              </p>
            </div>
            <div class="flex flex-shrink-0 flex-wrap gap-2">
              <button
                v-if="idPhotoModel.status === 'downloading'"
                type="button"
                class="rounded-lg border border-border bg-surface px-3 py-2 text-[12px] text-text-secondary transition-colors hover:border-error hover:text-error disabled:cursor-not-allowed disabled:opacity-50"
                :disabled="actionPending"
                @click="handleCancelIdPhotoDownload"
              >
                取消下载
              </button>
              <button
                v-else-if="idPhotoModel.can_download"
                type="button"
                class="rounded-lg bg-primary px-4 py-2 text-[12px] font-medium text-white transition-colors hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-50"
                :disabled="actionPending"
                @click="handleIdPhotoDownload"
              >
                {{ idPhotoActionLabel }}
              </button>
              <button
                v-if="idPhotoModel.can_delete"
                type="button"
                class="rounded-lg border border-error px-3 py-2 text-[12px] font-medium text-error transition-colors hover:bg-[#FFF4F4] disabled:cursor-not-allowed disabled:opacity-50"
                :disabled="actionPending"
                @click="handleDelete(idPhotoModel)"
              >
                删除模型
              </button>
            </div>
          </div>
        </template>
      </div>
    </section>

    <section
      class="mt-4 overflow-hidden rounded-2xl border border-border bg-surface shadow-sm"
      aria-labelledby="lan-transfer-title"
    >
      <div class="border-b border-border px-6 py-4">
        <h2 id="lan-transfer-title" class="text-[16px] font-semibold">局域网投送</h2>
        <p class="mt-1 text-[12px] text-text-secondary">
          设备名与接收目录保存在用户数据目录中，优先级高于环境变量；留空即回退默认值。
        </p>
      </div>

      <div v-if="lanLoading" class="px-6 py-5">
        <div class="h-12 animate-pulse rounded-lg bg-hover" aria-label="正在读取投送设置"></div>
      </div>

      <div v-else class="px-6 py-5">
        <p
          v-if="lanError"
          class="mb-4 rounded-xl border border-[#F1C4C4] bg-[#FFF4F4] px-4 py-3 text-[13px] text-[#B42318]"
          role="alert"
        >
          {{ lanError }}
        </p>

        <label for="lan-device-name" class="mb-2 block text-[13px] font-medium">设备名</label>
        <div class="flex flex-wrap gap-2">
          <input
            id="lan-device-name"
            v-model="lanDeviceName"
            type="text"
            maxlength="60"
            :placeholder="lanPreferences?.default_device_name || '设备名'"
            class="min-w-[220px] flex-1 rounded-xl border border-border bg-[#F9F9F6] px-4 py-2.5 text-[13px] outline-none transition-colors focus:border-primary focus:bg-surface"
          />
          <button
            type="button"
            class="rounded-lg bg-primary px-4 py-2 text-[12px] font-medium text-white transition-colors hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-50"
            :disabled="lanSaving"
            @click="saveLanDeviceName"
          >
            保存设备名
          </button>
        </div>
        <p class="mt-2 text-[12px] text-text-tertiary">
          浏览器页面用它标识这台电脑；留空时使用系统主机名
          {{ lanPreferences?.default_device_name }}。
        </p>
        <p class="mt-1 text-[12px] text-text-tertiary">
          修改后需停止并重新开启投送会话，新名称才会在浏览器页面与工具页生效。
        </p>

        <div class="mt-6 border-t border-border pt-5">
          <p class="mb-2 text-[13px] font-medium">接收目录</p>
          <p class="mb-3 break-all text-[12px] text-text-secondary">{{ lanPreferences?.receive_dir }}</p>
          <div class="flex flex-wrap items-center gap-2">
            <button
              type="button"
              class="rounded-lg border border-border bg-surface px-3 py-2 text-[12px] text-text-secondary transition-colors hover:border-primary hover:text-primary-dark disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="lanSaving"
              @click="pickLanReceiveDir"
            >
              选择目录
            </button>
            <button
              v-if="lanPreferences && lanPreferences.receive_dir !== lanPreferences.default_receive_dir"
              type="button"
              class="rounded-lg border border-border bg-surface px-3 py-2 text-[12px] text-text-secondary transition-colors hover:border-error hover:text-error disabled:cursor-not-allowed disabled:opacity-50"
              :disabled="lanSaving"
              @click="resetLanReceiveDir"
            >
              恢复默认
            </button>
            <span v-if="lanSaved" class="text-[12px] text-success" role="status">已保存</span>
          </div>
          <p class="mt-2 text-[12px] text-text-tertiary">
            确认接收的文件写入该目录，重名时自动避让而不是覆盖；默认位置是下载目录下的「工具盒子」。
          </p>
        </div>

        <div class="mt-6 border-t border-border pt-5">
          <p class="mb-3 text-[13px] font-medium">接收记录（最近 {{ lanRecords.length }} 条）</p>
          <p v-if="lanRecords.length === 0" class="text-[12px] text-text-tertiary">
            还没有接收记录。确认接收的文件会出现在这里。
          </p>
          <ul v-else class="space-y-2">
            <li
              v-for="record in lanRecords"
              :key="`${record.received_at}-${record.destination}`"
              class="rounded-xl border border-border px-4 py-3"
            >
              <div class="flex flex-wrap items-center gap-3 text-[13px]">
                <span class="min-w-0 flex-1 truncate font-medium">{{ record.name }}</span>
                <span class="text-[12px] text-text-secondary">{{ formatBytes(record.size_bytes) }}</span>
                <span class="text-[12px] text-text-tertiary">{{ record.received_at }}</span>
              </div>
              <div class="mt-1 flex items-center gap-2">
                <span class="min-w-0 flex-1 truncate text-[12px] text-text-secondary">
                  {{ record.destination }}
                </span>
                <button
                  type="button"
                  class="flex-shrink-0 rounded p-1 text-text-tertiary transition-colors hover:text-primary-dark"
                  :aria-label="`复制 ${record.name} 的路径`"
                  @click="copyLanPath(record.destination)"
                >
                  <font-awesome-icon :icon="['far', 'copy']" />
                </button>
                <span v-if="lanPathCopied === record.destination" class="text-[11px] text-success" role="status">
                  已复制
                </span>
              </div>
            </li>
          </ul>
        </div>
      </div>
    </section>
  </main>
</template>
