<!-- USB 有线传输：会话浏览、双向复制确认和独立任务结果，不提供覆盖或设备清扫。 -->
<script setup lang="ts">
import { BaseSelect } from '@/components/common'
import { formatUsbSize } from '@/api/usbTransfer'
import UsbTransferTasks from './usb-transfer/UsbTransferTasks.vue'
import { useUsbTransfer } from './usb-transfer/useUsbTransfer'

const {
  status, loading, actionBusy, errorMessage, pollError, devices, scanned, session,
  storageOptions, activeStorageId, currentStorage, currentDevicePath, pathStack, sortedEntries,
  listing, listError, listingComplete, selectedIds, deviceBusy, downloadTarget, uploadPaths,
  prepared, draftNote, canPrepareUpload, canPrepareDownload, tasks, recordErrors, taskBusy,
  detailTaskId, detail, detailBusy, detailError, refreshAll, scan, connect, disconnect,
  loadDirectory, changeStorage, enterFolder, goToCrumb, toggleEntry, pickLocal, prepare,
  submit, discardPrepared, cancel, remove, openDetails, retry,
} = useUsbTransfer()
const secondaryButton = 'inline-flex cursor-pointer items-center justify-center rounded-lg border border-border px-3 py-2 text-[12px] text-text-secondary transition-colors hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50'
const primaryButton = 'inline-flex cursor-pointer items-center justify-center rounded-lg bg-primary px-4 py-2 text-[12px] font-medium text-white transition-colors hover:bg-primary-dark disabled:cursor-not-allowed disabled:opacity-50'
</script>

<template>
  <main class="mx-auto w-full max-w-[960px] space-y-5 py-7">
    <section class="rounded-2xl border border-border bg-surface p-6 sm:p-8">
      <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1 class="text-[15px] font-semibold text-text"><font-awesome-icon :icon="['fas', 'plug']" class="mr-2" />有线传输</h1>
        <button type="button" :class="secondaryButton" @click="refreshAll">刷新状态</button>
      </div>
      <p v-if="loading" role="status" class="text-[13px] text-text-secondary">正在读取模块状态和任务记录…</p>
      <template v-else>
        <div class="flex flex-wrap items-center gap-3 text-[12px] text-text-secondary">
          <span class="rounded-full bg-hover px-3 py-1">{{ session ? (session.closing ? '连接停止中' : '设备会话已建立') : '未连接设备' }}</span>
          <span v-if="session">{{ session.device.name }}</span>
          <span v-if="status">工作进程{{ status.worker_running ? '运行中' : '未运行' }}</span>
        </div>
        <p v-if="status && !status.platform_supported" class="mt-4 text-[13px] text-[#7A5A12]">{{ status.platform_reason }}</p>
        <p v-else-if="status && !status.dependency_available" class="mt-4 text-[13px] leading-relaxed text-[#7A5A12]">{{ status.dependency_reason }}。本模块不会自动安装系统组件：开发运行需本机提供 MTP 运行库，随应用分发时由应用自带资源提供；也可通过配置项 USB_TRANSFER_LIBRARY_PATH 指定路径。修复后点“刷新状态”重新检查。</p>
        <p v-else-if="status?.dependency_state === 'located'" class="mt-4 text-[12px] text-text-tertiary">已找到运行库路径，尚未加载；这不代表原生运行环境或设备兼容性已确认。</p>
        <p class="mt-4 text-[13px] leading-relaxed text-text-secondary">用数据线连接支持 MTP 的设备，解锁并选择文件传输模式。只复制，不移动、不覆盖、不删除源文件。</p>
        <p v-if="session" class="mt-2 text-[12px] leading-relaxed text-text-tertiary">最近确认的设备应答：{{ session.last_device_response_at }}。空闲时不主动访问 USB，不能据此确认设备仍物理连接。</p>
        <button v-if="session" type="button" :class="`${secondaryButton} mt-4`" :disabled="Boolean(actionBusy) || session.closing" @click="disconnect">{{ session.closing ? '等待释放连接…' : '断开设备' }}</button>
      </template>
      <p v-if="errorMessage" role="alert" class="mt-4 rounded-xl border border-[#F0D5D5] bg-[#FDF1F1] p-3 text-[12px] text-[#8C3B3B]">{{ errorMessage }}</p>
      <p v-if="pollError" role="alert" class="mt-3 text-[12px] text-[#8C3B3B]">状态暂不可用：{{ pollError }}。保留已有结果，不据此认定任务已停止。</p>
    </section>

    <section v-if="!loading && status?.platform_supported && !session" class="rounded-2xl border border-border bg-surface p-6 sm:p-8" aria-labelledby="usb-devices-title">
      <div class="mb-4 flex items-center justify-between gap-3">
        <h2 id="usb-devices-title" class="text-[14px] font-semibold text-text">设备</h2>
        <button type="button" :class="primaryButton" :disabled="Boolean(actionBusy) || !status?.dependency_available" @click="scan">{{ actionBusy === 'scan' ? '正在扫描…' : '扫描／重试扫描' }}</button>
      </div>
      <p v-if="status && !status.dependency_available" class="mb-4 text-[12px] leading-relaxed text-[#7A5A12]">当前缺少运行库，扫描不可用；修复依赖后刷新状态即可重试。</p>
      <p class="mb-4 text-[12px] leading-relaxed text-text-tertiary">扫描会进行 USB 描述符探测，可能短暂打开设备；无法保证完全不影响其他应用。无法访问时请检查连接、传输模式和占用情况，不能据通用错误精确判断原因。</p>
      <p v-if="!scanned" class="text-[13px] text-text-secondary">尚未取得扫描结果。</p>
      <p v-else-if="!devices.length" class="text-[13px] text-text-secondary">未发现可用 MTP 设备；非 iPhone 设备不一定支持 MTP。</p>
      <ul v-else class="space-y-2">
        <li v-for="device in devices" :key="device.device_id" class="flex items-center justify-between gap-4 rounded-xl border border-border p-4">
          <div class="min-w-0"><p class="break-all text-[13px] text-text">{{ device.name }}</p><p class="mt-1 text-[11px] text-text-tertiary">{{ device.device_id }}</p></div>
          <button type="button" :class="primaryButton" :disabled="Boolean(actionBusy)" @click="connect(device)">{{ actionBusy === `connect:${device.device_id}` ? '连接中…' : '连接' }}</button>
        </li>
      </ul>
    </section>

    <section v-if="session" class="rounded-2xl border border-border bg-surface p-6 sm:p-8" aria-labelledby="usb-browser-title">
      <div class="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h2 id="usb-browser-title" class="text-[14px] font-semibold text-text">设备目录</h2>
        <div class="flex items-center gap-3">
          <BaseSelect v-if="storageOptions.length > 1" :model-value="activeStorageId === null ? '' : String(activeStorageId)" :options="storageOptions" :disabled="deviceBusy || listing" size="sm" aria-label="选择设备存储" @change="changeStorage" />
          <button type="button" :class="secondaryButton" :disabled="listing || deviceBusy" @click="loadDirectory">刷新目录</button>
        </div>
      </div>
      <nav aria-label="设备目录路径" class="mb-3 flex flex-wrap items-center gap-1 text-[12px] text-text-secondary">
        <template v-for="(crumb, index) in pathStack" :key="`${crumb.folderId}-${index}`">
          <span v-if="index">/</span>
          <button type="button" class="max-w-[220px] cursor-pointer truncate rounded px-1 py-1 hover:bg-hover disabled:cursor-default" :disabled="deviceBusy || listing || index === pathStack.length - 1" :aria-current="index === pathStack.length - 1 ? 'page' : undefined" @click="goToCrumb(index)">{{ crumb.name }}</button>
        </template>
      </nav>
      <p v-if="currentStorage" class="mb-4 flex flex-wrap gap-4 text-[12px] text-text-tertiary">
        <span>可用空间 {{ formatUsbSize(currentStorage.free_bytes) }}</span><span>总容量 {{ formatUsbSize(currentStorage.capacity_bytes) }}</span>
        <span>{{ !currentStorage.information_complete ? '访问能力未知' : currentStorage.access_capability === 0 ? '设备报告可读写' : '存储不可上传' }}</span>
      </p>
      <p v-if="deviceBusy" role="status" class="mb-3 text-[12px] text-text-secondary">设备正忙，暂停浏览；可以查看、提交或取消任务。传输结束后可手动刷新目录。</p>
      <p v-if="listing" role="status" class="text-[13px] text-text-secondary">正在读取目录；大目录没有底层分页，可能需要较长时间…</p>
      <p v-if="listError" role="alert" class="mb-3 text-[12px] text-[#8C3B3B]">{{ listError }}</p>
      <p v-if="!listing && !listError && listingComplete && !sortedEntries.length" class="text-[13px] text-text-tertiary">该目录为空。</p>
      <ul v-if="!listing && sortedEntries.length" class="max-h-[420px] divide-y divide-border overflow-y-auto">
        <li v-for="entry in sortedEntries" :key="entry.object_id" class="flex items-center gap-3 py-3">
          <input type="checkbox" class="h-4 w-4 shrink-0 accent-primary" :checked="selectedIds.includes(entry.object_id)" :disabled="session.closing || Boolean(actionBusy)" :aria-label="`选择${entry.name}`" @change="toggleEntry(entry.object_id)" />
          <button v-if="entry.is_folder" type="button" class="flex min-w-0 flex-1 cursor-pointer items-center gap-2 text-left text-[13px] text-text disabled:cursor-default" :disabled="deviceBusy" @click="enterFolder(entry)"><font-awesome-icon :icon="['fas', 'folder']" class="text-[#C9A227]" /><span class="truncate">{{ entry.name }}</span></button>
          <span v-else class="flex min-w-0 flex-1 items-center gap-2 text-[13px] text-text"><font-awesome-icon :icon="['fas', 'file']" class="text-text-tertiary" /><span class="truncate">{{ entry.name }}</span></span>
          <span class="shrink-0 text-[12px] text-text-tertiary">{{ entry.is_folder ? '目录' : formatUsbSize(entry.size_bytes) }}</span>
        </li>
      </ul>
      <div class="mt-5 border-t border-border pt-5">
        <h3 class="text-[13px] font-semibold text-text">设备 → 本机</h3>
        <p class="mt-2 break-all text-[12px] text-text-secondary">已选 {{ selectedIds.length }} 项；目标：{{ downloadTarget || '尚未选择本机目录' }}</p>
        <div class="mt-3 flex flex-wrap gap-3">
          <button type="button" :class="secondaryButton" :disabled="Boolean(actionBusy) || session.closing" @click="pickLocal('target')">选择本机目标目录</button>
          <button type="button" :class="primaryButton" :disabled="!canPrepareDownload || Boolean(actionBusy)" @click="prepare('download')">准备下载任务</button>
        </div>
      </div>
      <div class="mt-5 border-t border-border pt-5">
        <h3 class="text-[13px] font-semibold text-text">本机 → 设备</h3>
        <p class="mt-2 break-all text-[12px] text-text-secondary">设备目标：{{ currentDevicePath }}</p>
        <p class="mt-2 text-[12px] text-text-tertiary">一个任务支持多文件或一个目录；多个目录请分任务排队。不跟随符号链接。</p>
        <ul v-if="uploadPaths.length" class="mt-2 max-h-32 overflow-y-auto text-[12px] text-text-secondary"><li v-for="path in uploadPaths" :key="path" class="break-all py-0.5">{{ path }}</li></ul>
        <div class="mt-3 flex flex-wrap gap-3">
          <button type="button" :class="secondaryButton" :disabled="Boolean(actionBusy) || session.closing" @click="pickLocal('files')">选择本机文件</button>
          <button type="button" :class="secondaryButton" :disabled="Boolean(actionBusy) || session.closing" @click="pickLocal('folder')">选择一个本机目录</button>
          <button type="button" :class="primaryButton" :disabled="!canPrepareUpload || Boolean(actionBusy) || !currentStorage?.information_complete || currentStorage.access_capability !== 0" @click="prepare('upload')">准备上传任务</button>
        </div>
      </div>
    </section>

    <p v-if="draftNote" role="status" class="rounded-xl border border-border bg-surface px-5 py-3 text-[12px] leading-relaxed text-text-secondary">{{ draftNote }}</p>
    <section v-if="prepared" class="rounded-2xl border border-primary bg-surface p-6" aria-labelledby="usb-confirm-title">
      <h2 id="usb-confirm-title" class="text-[14px] font-semibold text-text">确认加入队列</h2>
      <p class="mt-3 text-[13px] text-text">{{ prepared.request.direction === 'download' ? '设备 → 本机' : '本机 → 设备' }} · {{ prepared.request.direction === 'download' ? prepared.request.source_objects.length : prepared.request.source_paths.length }} 个来源</p>
      <p class="mt-2 break-all text-[12px] text-text-secondary">目标：{{ prepared.request.local_target ?? currentDevicePath }}</p>
      <p class="mt-3 text-[12px] leading-relaxed text-text-secondary">重名文件跳过；仅复用可确认的同名普通目录。不保证来源快照；本机落盘会净化设备名称，碰撞不会静默合并。已完成内容不会回滚。</p>
      <p v-if="prepared.request.direction === 'upload'" class="mt-2 text-[12px] leading-relaxed text-[#8C3B3B]">设备上传没有原子排他保证；只能跳过已知重名，不能保证外部并发或异常设备下绝不重复或覆盖。失败可能留下残留，只记录，不自动删除。</p>
      <p class="mt-2 text-[11px] text-text-tertiary">提交凭据有效至 {{ new Date(prepared.expires_at * 1000).toLocaleString() }}。请求结果不明时保留本草稿，重复提交不会在有效期内重做同一任务。</p>
      <div class="mt-4 flex gap-3">
        <button type="button" :class="primaryButton" :disabled="Boolean(actionBusy) || !session || session.closing" @click="submit">{{ actionBusy === 'submit' ? '正在提交…' : '确认加入队列' }}</button>
        <button type="button" :class="secondaryButton" :disabled="Boolean(actionBusy)" @click="discardPrepared">放弃草稿</button>
      </div>
    </section>

    <UsbTransferTasks :tasks="tasks" :record-errors="recordErrors" :busy="taskBusy" :selected-id="detailTaskId" :detail="detail" :detail-busy="detailBusy" :detail-error="detailError" @cancel="cancel" @remove="remove" @retry="retry" @details="openDetails" />
  </main>
</template>
