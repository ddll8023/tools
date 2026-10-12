<!-- 局域网投送工具页：开启会话、展示访问入口与二维码、管理待投送与待接收文件、设置访问口令。 -->
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  acceptPendingFile,
  addOutgoingFiles,
  fetchLanRecovery,
  fetchLanSessionStatus,
  fetchOutgoingFiles,
  fetchPendingFiles,
  rejectPendingFile,
  removeOutgoingFile,
  setLanPassphrase,
  startLanSession,
  stopLanSession,
} from '@/api/lanTransfer'
import type {
  LanAddressItem,
  LanCleanupFailure,
  LanOutgoingItem,
  LanPendingItem,
  LanRecoveryResult,
  LanSessionStatus,
} from '@/api/lanTransfer'
import { generateQrCode } from '@/api/tools'

const POLL_INTERVAL_MS = 15000
const COPY_FEEDBACK_MS = 1500

const session = ref<LanSessionStatus | null>(null)
const recovery = ref<LanRecoveryResult | null>(null)
const recoveryDismissed = ref(false)
const outgoingFiles = ref<LanOutgoingItem[]>([])
const outgoingBusy = ref('')
const outgoingError = ref('')
const pendingFiles = ref<LanPendingItem[]>([])
const pendingBusy = ref('')
const pendingError = ref('')
const loading = ref(true)
const pending = ref(false)
const errorMessage = ref('')
const passphraseInput = ref('')
const qrCodes = ref<Record<string, string>>({})
const copiedAddress = ref('')
let pollTimer: number | undefined
let copyTimer: number | undefined

const state = computed(() => session.value?.state ?? 'idle')
const isActive = computed(() => state.value === 'active')
const addresses = computed<LanAddressItem[]>(() => session.value?.addresses ?? [])
// 关闭时的清理失败残留保留到用户手动关闭或应用重启，不随会话停止而消失。
const cleanupFailures = ref<LanCleanupFailure[]>([])
const outgoingTotalBytes = computed(() =>
  outgoingFiles.value.reduce((total, item) => total + item.size_bytes, 0)
)

/** 平台相关提示：防火墙只能引导用户处理，无法可靠自动检测。 */
const firewallHint = computed(() => {
  const platform = window.desktopApi?.platform ?? ''
  if (platform === 'darwin') {
    return '首次开启时 macOS 可能询问是否允许接受传入连接，需要选择允许，否则对方无法访问。'
  }
  if (platform === 'win32') {
    return '首次开启时 Windows 防火墙可能弹窗，需要勾选专用网络并允许访问，否则对方无法访问。'
  }
  return '如果对方无法访问，请检查系统防火墙是否放行了本应用。'
})

/** 提前提示资源压力，避免用户在传输中途被拒。 */
const spaceWarning = computed(() => {
  const current = session.value
  if (!current || !isActive.value) return ''
  if (current.max_bytes > 0 && current.used_bytes >= current.max_bytes * 0.8) {
    return '隔离区占用已接近本次会话上限，继续接收会被拒绝。'
  }
  if (current.free_disk_bytes !== null && current.free_disk_bytes < 1024 ** 3) {
    return '接收盘可用空间偏低，大文件可能无法完整接收。'
  }
  return ''
})

/** 以 1024 为进制展示文件大小。 */
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let value = bytes / 1024
  let unitIndex = 0
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024
    unitIndex += 1
  }
  return `${value.toFixed(1)} ${units[unitIndex]}`
}

const statusLabel = computed(() => {
  switch (state.value) {
    case 'active':
      return '投送已开启'
    case 'starting':
      return '正在开启'
    case 'closing':
      return '正在关闭'
    case 'failed':
      return '开启失败'
    case 'closed':
      return '已停止'
    default:
      return '未开启'
  }
})

const remainingText = computed(() => {
  if (!isActive.value) return ''
  const seconds = session.value?.remaining_seconds ?? 0
  if (seconds <= 0) return '即将自动关闭'
  const minutes = Math.floor(seconds / 60)
  return minutes > 0 ? `剩余约 ${minutes} 分钟自动关闭` : '剩余不到 1 分钟'
})

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

/** 二维码按地址懒加载；失败只影响二维码，不影响链接展示。 */
async function loadQrCodes(current: LanSessionStatus) {
  const missing = current.addresses.filter((item) => !qrCodes.value[item.address])
  await Promise.all(
    missing.map(async (item) => {
      try {
        const result = await generateQrCode(item.url)
        qrCodes.value = { ...qrCodes.value, [item.address]: result.image_data_url }
      } catch {
        // 保留链接入口即可
      }
    })
  )
}

function applySession(next: LanSessionStatus) {
  session.value = next
  errorMessage.value = next.state === 'failed' ? next.message : ''
  void loadQrCodes(next)
}

async function refreshPending() {
  try {
    pendingFiles.value = await fetchPendingFiles()
  } catch (error) {
    pendingError.value = getErrorMessage(error, '读取待接收列表失败')
  }
}

/** 读取本次启动的遗留回收结果；属提示信息，读取失败不打扰用户。 */
async function loadRecovery() {
  try {
    const result = await fetchLanRecovery()
    if (result.recovered && (result.removed_files > 0 || result.failures.length > 0)) {
      recovery.value = result
    }
  } catch {
    // 忽略：回收提示不影响会话操作
  }
}

async function refreshOutgoing() {
  try {
    outgoingFiles.value = await fetchOutgoingFiles()
  } catch (error) {
    outgoingError.value = getErrorMessage(error, '读取待取件列表失败')
  }
}

/** 逐个登记本机绝对路径；后端不复制文件，下载时直接读取原文件。 */
async function addOutgoingPaths(paths: string[]) {
  if (outgoingBusy.value) return
  outgoingBusy.value = 'add'
  outgoingError.value = ''
  try {
    outgoingFiles.value = await addOutgoingFiles(paths)
    await refreshStatus()
  } catch (error) {
    outgoingError.value = getErrorMessage(error, '添加待投送文件失败')
  } finally {
    outgoingBusy.value = ''
  }
}

/** 桌面端原生多选对话框；浏览器环境下没有该能力。 */
async function pickOutgoingFiles() {
  if (outgoingBusy.value) return
  const dialog = window.desktopApi?.fileDialog
  if (!dialog?.pickFiles) {
    outgoingError.value = '请通过工具盒子桌面应用选择本机文件'
    return
  }

  outgoingBusy.value = 'pick'
  outgoingError.value = ''
  try {
    const picked = await dialog.pickFiles()
    if (picked.length > 0) {
      await addOutgoingPaths(picked.map((item) => item.path))
    }
  } catch (error) {
    outgoingError.value = getErrorMessage(error, '打开文件选择对话框失败')
  } finally {
    outgoingBusy.value = ''
  }
}

/** 拖拽加入：路径由 preload 在拖放事件中预先解析并缓存。 */
function handleOutgoingDrop() {
  if (outgoingBusy.value) return
  const paths = window.desktopApi?.fileDialog?.takeDroppedPaths?.() ?? []
  if (paths.length === 0) {
    outgoingError.value = '请通过「选择文件」按钮添加要投送的文件'
    return
  }
  void addOutgoingPaths(paths)
}

async function removeOutgoing(item: LanOutgoingItem) {
  if (outgoingBusy.value) return
  outgoingBusy.value = item.file_id
  outgoingError.value = ''
  try {
    outgoingFiles.value = await removeOutgoingFile(item.file_id)
    await refreshStatus()
  } catch (error) {
    outgoingError.value = getErrorMessage(error, '移除待投送文件失败')
  } finally {
    outgoingBusy.value = ''
  }
}

async function refreshStatus() {
  try {
    const next = await fetchLanSessionStatus()
    applySession(next)
    if (next.state === 'active') {
      await Promise.all([refreshOutgoing(), refreshPending()])
    } else {
      outgoingFiles.value = []
      pendingFiles.value = []
    }
  } catch (error) {
    errorMessage.value = getErrorMessage(error, '读取投送状态失败')
  }
}

/** 接收或拒绝待接收文件；两者都由后端保证与关闭清理不会同时操作同一文件。 */
async function handlePending(item: LanPendingItem, accept: boolean) {
  if (pendingBusy.value) return
  pendingBusy.value = item.upload_id
  pendingError.value = ''
  try {
    pendingFiles.value = accept
      ? await acceptPendingFile(item.upload_id)
      : await rejectPendingFile(item.upload_id)
    await refreshStatus()
  } catch (error) {
    pendingError.value = getErrorMessage(error, accept ? '接收文件失败' : '拒绝文件失败')
  } finally {
    pendingBusy.value = ''
  }
}

async function startSession() {
  if (pending.value) return
  pending.value = true
  errorMessage.value = ''
  qrCodes.value = {}
  try {
    applySession(await startLanSession())
  } catch (error) {
    errorMessage.value = getErrorMessage(error, '开启投送失败')
  } finally {
    pending.value = false
  }
}

async function stopSession() {
  if (pending.value) return
  pending.value = true
  try {
    const next = await stopLanSession()
    cleanupFailures.value = next.cleanup_failures
    applySession(next)
    qrCodes.value = {}
    outgoingFiles.value = []
    pendingFiles.value = []
  } catch (error) {
    errorMessage.value = getErrorMessage(error, '停止投送失败')
  } finally {
    pending.value = false
  }
}

async function savePassphrase() {
  if (pending.value) return
  pending.value = true
  try {
    applySession(await setLanPassphrase(passphraseInput.value))
    passphraseInput.value = ''
  } catch (error) {
    errorMessage.value = getErrorMessage(error, '设置访问口令失败')
  } finally {
    pending.value = false
  }
}

async function copyAddress(item: LanAddressItem) {
  try {
    await navigator.clipboard.writeText(item.url)
    copiedAddress.value = item.address
    if (copyTimer !== undefined) window.clearTimeout(copyTimer)
    copyTimer = window.setTimeout(() => {
      copiedAddress.value = ''
      copyTimer = undefined
    }, COPY_FEEDBACK_MS)
  } catch {
    errorMessage.value = '复制链接失败，请手动选择并复制。'
  }
}

onMounted(async () => {
  await loadRecovery()
  await refreshStatus()
  loading.value = false
  pollTimer = window.setInterval(() => {
    if (isActive.value) void refreshStatus()
  }, POLL_INTERVAL_MS)
})

onBeforeUnmount(() => {
  if (pollTimer !== undefined) window.clearInterval(pollTimer)
  if (copyTimer !== undefined) window.clearTimeout(copyTimer)
})
</script>

<template>
  <main class="mx-auto w-full max-w-[860px] py-7">
    <section
      v-if="recovery && !recoveryDismissed"
      class="mb-5 rounded-2xl border border-border bg-[#FDF4E3] p-8"
    >
      <div class="mb-3 flex items-start justify-between gap-3">
        <div class="text-[13px] font-semibold text-[#7A5A12]">
          <font-awesome-icon :icon="['fas', 'triangle-exclamation']" class="mr-1.5" />
          上次异常退出留下的投送内容
        </div>
        <button
          type="button"
          class="flex-shrink-0 cursor-pointer text-[12px] text-[#7A5A12] underline"
          @click="recoveryDismissed = true"
        >
          知道了
        </button>
      </div>
      <p class="mb-2 text-[12px] leading-relaxed text-[#7A5A12]">
        本次启动已回收 {{ recovery.removed_files }} 个未确认文件（{{ formatSize(recovery.removed_bytes) }}）。
      </p>
      <ul
        v-if="recovery.failures.length"
        class="list-disc space-y-1.5 pl-5 text-[12px] leading-relaxed text-[#7A5A12]"
      >
        <li v-for="path in recovery.failures" :key="path">回收失败，仍占用磁盘：{{ path }}</li>
      </ul>
    </section>
    <section class="mb-5 rounded-2xl border border-border bg-surface p-8">
      <div
        class="mb-[18px] text-[13px] font-semibold uppercase tracking-[0.5px] text-text-secondary"
      >
        <font-awesome-icon :icon="['fas', 'tower-broadcast']" class="mr-1.5" />
        投送会话
      </div>

      <div v-if="loading" class="text-[13px] text-text-secondary">正在读取投送状态…</div>

      <template v-else>
        <div class="mb-4 flex flex-wrap items-center gap-3">
          <span
            class="rounded-full px-3 py-1 text-[12px] font-medium"
            :class="isActive ? 'bg-primary-light text-primary-dark' : 'bg-[#F3F3F0] text-text-secondary'"
          >
            {{ statusLabel }}
          </span>
          <span v-if="remainingText" class="text-[12px] text-text-tertiary">
            {{ remainingText }}
          </span>
          <span v-if="session?.device_name" class="text-[12px] text-text-tertiary">
            电脑名称：{{ session.device_name }}
          </span>
          <span
            v-if="session && session.free_disk_bytes !== null"
            class="text-[12px] text-text-tertiary"
          >
            接收盘可用 {{ formatSize(session.free_disk_bytes) }}
          </span>
        </div>

        <p class="mb-5 text-[13px] leading-relaxed text-text-secondary">
          开启后电脑会在局域网内监听一个临时端口，其他设备用浏览器打开链接即可参与投送。
          端口只存在于会话期间，停止投送或超时后立即关闭。
        </p>

        <p
          v-if="spaceWarning"
          class="mb-5 rounded-xl border border-[#F2E0BD] bg-[#FDF4E3] px-4 py-3 text-[12px] leading-relaxed text-[#7A5A12]"
        >
          {{ spaceWarning }}
        </p>

        <div class="flex flex-wrap gap-3">
          <button
            v-if="!isActive"
            type="button"
            class="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-primary px-[22px] py-[9px] text-[13px] font-medium text-white transition-all duration-200 hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="pending"
            @click="startSession"
          >
            <font-awesome-icon :icon="['fas', 'tower-broadcast']" />
            开启投送
          </button>
          <button
            v-else
            type="button"
            class="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-border px-[22px] py-[9px] text-[13px] font-medium transition-all duration-200 hover:bg-hover disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="pending"
            @click="stopSession"
          >
            <font-awesome-icon :icon="['fas', 'xmark']" />
            停止投送
          </button>
        </div>

        <div v-if="isActive" class="mt-6 border-t border-border pt-5">
          <label for="lan-passphrase" class="mb-2 block text-[13px] font-medium">
            访问口令（可选）
          </label>
          <div class="flex flex-wrap gap-3">
            <input
              id="lan-passphrase"
              v-model="passphraseInput"
              type="password"
              autocomplete="off"
              placeholder="留空表示不设置口令"
              class="min-w-[220px] flex-1 rounded-xl border border-border bg-[#F9F9F6] px-4 py-2.5 text-[13px] outline-none transition-colors focus:border-primary focus:bg-surface"
            />
            <button
              type="button"
              class="cursor-pointer rounded-lg border border-border px-5 py-2.5 text-[13px] font-medium transition-all duration-200 hover:bg-hover disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="pending"
              @click="savePassphrase"
            >
              保存口令
            </button>
          </div>
          <p class="mt-2 text-[12px] text-text-tertiary">
            当前状态：{{ session?.has_passphrase ? '已设置口令' : '未设置口令' }}。
            设置或清除口令后，已经进入的设备需要重新输入。
          </p>
        </div>

        <p v-if="errorMessage" class="mt-4 text-[12px] text-error">{{ errorMessage }}</p>
      </template>
    </section>

    <section v-if="isActive" class="mb-5 rounded-2xl border border-border bg-surface p-8">
      <div
        class="mb-[18px] text-[13px] font-semibold uppercase tracking-[0.5px] text-text-secondary"
      >
        <font-awesome-icon :icon="['fas', 'qrcode']" class="mr-1.5" />
        访问入口
      </div>

      <p class="mb-3 text-[12px] leading-relaxed text-text-tertiary">
        下面列出的是可用于局域网访问的地址，已排除回环、隧道与虚拟网卡。手机或平板必须与电脑
        处于同一网络，并选择与当前网络对应的那一条；推荐项优先取默认出口地址，其次是私网地址。
        选错地址会导致对方打不开页面。
      </p>

      <p v-if="addresses.length === 0" class="text-[13px] leading-relaxed text-text-secondary">
        未检测到可用的局域网地址。请确认电脑已连接到局域网（有线或无线），
        然后停止并重新开启投送。
      </p>

      <ul v-else class="space-y-4">
        <li
          v-for="item in addresses"
          :key="item.address"
          class="flex flex-col gap-4 rounded-xl border border-border p-5 sm:flex-row sm:items-center"
        >
          <img
            v-if="qrCodes[item.address]"
            :src="qrCodes[item.address]"
            :alt="`访问 ${item.address} 的二维码`"
            class="h-[132px] w-[132px] flex-shrink-0 self-center rounded-lg border border-border"
          />
          <div class="min-w-0 flex-1">
            <div class="mb-1 flex items-center gap-2">
              <span class="text-[14px] font-semibold">{{ item.address }}</span>
              <span
                v-if="item.is_recommended"
                class="rounded-full bg-primary-light px-2 py-0.5 text-[11px] font-medium text-primary-dark"
              >
                推荐
              </span>
            </div>
            <p class="mb-3 break-all text-[12px] leading-relaxed text-text-secondary">
              {{ item.url }}
            </p>
            <button
              type="button"
              class="cursor-pointer rounded-lg border border-border px-4 py-2 text-[12px] font-medium transition-all duration-200 hover:bg-hover"
              @click="copyAddress(item)"
            >
              <font-awesome-icon :icon="['far', 'copy']" class="mr-1.5" />
              {{ copiedAddress === item.address ? '已复制' : '复制链接' }}
            </button>
          </div>
        </li>
      </ul>
    </section>

    <section v-if="isActive" class="mb-5 rounded-2xl border border-border bg-surface p-8">
      <div
        class="mb-[18px] flex items-center justify-between text-[13px] font-semibold uppercase tracking-[0.5px] text-text-secondary"
      >
        <span>
          <font-awesome-icon :icon="['fas', 'arrow-right']" class="mr-1.5" />
          待投送文件
        </span>
        <span
          v-if="outgoingFiles.length"
          class="rounded-full bg-primary-light px-2 py-0.5 text-[11px] font-medium normal-case text-primary-dark"
        >
          {{ outgoingFiles.length }} 个 · {{ formatSize(outgoingTotalBytes) }}
        </span>
      </div>

      <div
        class="rounded-xl border-2 border-dashed border-border py-7 text-center transition-all duration-250 hover:border-primary hover:bg-primary-light"
        @dragover.prevent
        @drop.prevent="handleOutgoingDrop"
      >
        <p class="mb-3 text-[13px] text-text-secondary">把文件拖到这里，或点击下方按钮选择</p>
        <button
          type="button"
          class="inline-flex cursor-pointer items-center gap-2 rounded-lg bg-primary px-[22px] py-[9px] text-[13px] font-medium text-white transition-all duration-200 hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-60"
          :disabled="outgoingBusy !== ''"
          @click="pickOutgoingFiles"
        >
          <font-awesome-icon :icon="['fas', 'folder-open']" />
          选择文件
        </button>
        <p class="mt-3 text-[12px] text-text-tertiary">
          文件不会被复制，对端下载时直接读取本机原文件
        </p>
      </div>

      <p v-if="outgoingFiles.length === 0" class="mt-4 text-[13px] leading-relaxed text-text-secondary">
        还没有待投送的文件。对方打开链接后可以逐个下载这里的文件。
      </p>

      <ul v-else class="mt-4 space-y-3">
        <li
          v-for="item in outgoingFiles"
          :key="item.file_id"
          class="flex flex-wrap items-center gap-3 rounded-xl border border-border px-4 py-3"
        >
          <font-awesome-icon
            :icon="['far', 'file']"
            :class="item.available ? 'text-primary' : 'text-text-tertiary'"
          />
          <span class="min-w-0 flex-1 truncate text-[13px] font-medium">{{ item.name }}</span>
          <span v-if="!item.available" class="text-[12px] text-error">文件已不可用</span>
          <span class="text-[12px] text-text-secondary">{{ formatSize(item.size_bytes) }}</span>
          <button
            type="button"
            class="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-border px-4 py-1.5 text-[12px] font-medium transition-all duration-200 hover:bg-hover disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="outgoingBusy !== ''"
            @click="removeOutgoing(item)"
          >
            <font-awesome-icon :icon="['fas', 'xmark']" />
            移除
          </button>
        </li>
      </ul>

      <p v-if="outgoingError" class="mt-3 text-[12px] text-error">{{ outgoingError }}</p>
    </section>

    <section v-if="isActive" class="mb-5 rounded-2xl border border-border bg-surface p-8">
      <div
        class="mb-[18px] flex items-center justify-between text-[13px] font-semibold uppercase tracking-[0.5px] text-text-secondary"
      >
        <span>
          <font-awesome-icon :icon="['far', 'file']" class="mr-1.5" />
          待接收文件
        </span>
        <span
          v-if="session?.pending_count"
          class="rounded-full bg-primary-light px-2 py-0.5 text-[11px] font-medium normal-case text-primary-dark"
        >
          {{ session.pending_count }} 个
        </span>
      </div>

      <p v-if="pendingFiles.length === 0" class="text-[13px] leading-relaxed text-text-secondary">
        暂无待接收文件。对方上传后文件会先进入隔离区，确认接收后才写入接收目录。
      </p>

      <ul v-else class="space-y-3">
        <li
          v-for="item in pendingFiles"
          :key="item.upload_id"
          class="flex flex-wrap items-center gap-3 rounded-xl border border-border px-4 py-3"
        >
          <font-awesome-icon :icon="['far', 'file']" class="text-primary" />
          <span class="min-w-0 flex-1 truncate text-[13px] font-medium">{{ item.name }}</span>
          <span class="text-[12px] text-text-secondary">{{ formatSize(item.size_bytes) }}</span>
          <div class="flex gap-2">
            <button
              type="button"
              class="inline-flex cursor-pointer items-center gap-1.5 rounded-lg bg-primary px-4 py-1.5 text-[12px] font-medium text-white transition-all duration-200 hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="pendingBusy !== ''"
              @click="handlePending(item, true)"
            >
              <font-awesome-icon :icon="['fas', 'check-circle']" />
              接收
            </button>
            <button
              type="button"
              class="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-border px-4 py-1.5 text-[12px] font-medium transition-all duration-200 hover:bg-hover disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="pendingBusy !== ''"
              @click="handlePending(item, false)"
            >
              <font-awesome-icon :icon="['fas', 'xmark']" />
              拒绝
            </button>
          </div>
        </li>
      </ul>

      <p v-if="pendingError" class="mt-3 text-[12px] text-error">{{ pendingError }}</p>

      <p v-if="session && session.used_bytes > 0" class="mt-4 text-[12px] text-text-tertiary">
        隔离区已占用 {{ formatSize(session.used_bytes) }} / 上限 {{ formatSize(session.max_bytes) }}
      </p>
    </section>

    <section
      v-if="cleanupFailures.length > 0"
      class="mb-5 rounded-2xl border border-border bg-[#FDF4E3] p-8"
    >
      <div class="mb-3 flex items-start justify-between gap-3">
        <div class="text-[13px] font-semibold text-[#7A5A12]">
          <font-awesome-icon :icon="['fas', 'triangle-exclamation']" class="mr-1.5" />
          上次关闭时未能清理的残留
        </div>
        <button
          type="button"
          class="flex-shrink-0 cursor-pointer text-[12px] text-[#7A5A12] underline"
          @click="cleanupFailures = []"
        >
          知道了
        </button>
      </div>
      <p class="mb-2 text-[12px] leading-relaxed text-[#7A5A12]">
        以下内容仍占用磁盘，已从本次会话预算中扣除；重启应用时会再次尝试回收。
      </p>
      <ul class="list-disc space-y-1.5 pl-5 text-[12px] leading-relaxed text-[#7A5A12]">
        <li v-for="failure in cleanupFailures" :key="failure.path">
          {{ failure.path }}（{{ formatSize(failure.size_bytes) }}）
        </li>
      </ul>
    </section>

    <section class="rounded-2xl border border-border bg-[#FDF4E3] p-8">
      <div class="mb-3 text-[13px] font-semibold text-[#7A5A12]">
        <font-awesome-icon :icon="['fas', 'triangle-exclamation']" class="mr-1.5" />
        使用限制
      </div>
      <ul class="list-disc space-y-1.5 pl-5 text-[13px] leading-relaxed text-[#7A5A12]">
        <li>{{ firewallHint }}</li>
        <li>投送内容在局域网中以明文传输，同一网络中的其他人可能看到传输内容。</li>
        <li>链接凭据与访问口令都不能替代传输加密，也无法抵御中间人攻击。</li>
        <li>仅在你信任的局域网内使用，不要在公共 Wi-Fi 或访客网络传输敏感文件。</li>
        <li>部分网络开启了客户端隔离，其他设备可能无法访问电脑，此时只能更换网络。</li>
      </ul>
    </section>
  </main>
</template>
