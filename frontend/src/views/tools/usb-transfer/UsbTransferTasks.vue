<!-- USB 任务及分页结果区：不依赖设备连接是否仍存在。 -->
<script setup lang="ts">
import { formatUsbSize, usbTaskActive } from '@/api/usbTransfer'
import type { UsbRecordError, UsbTaskEntries, UsbTaskState, UsbTaskSummary } from '@/api/usbTransfer'

defineProps<{
  tasks: UsbTaskSummary[]
  recordErrors: UsbRecordError[]
  busy: string
  selectedId: string
  detail: UsbTaskEntries | null
  detailBusy: boolean
  detailError: string
}>()
const emit = defineEmits<{
  cancel: [taskId: string]
  remove: [taskId: string]
  retry: [task: UsbTaskSummary]
  details: [taskId: string, offset: number]
}>()
const labels: Record<UsbTaskState, string> = {
  queued: '排队中', running: '执行中', cancelling: '正在停止', completed: '已完成',
  partial_success: '部分成功', failed: '失败', cancelled: '已取消', interrupted: '已中断',
}
const stages: Record<string, string> = {
  queued: '等待设备', starting: '准备中', stopping: '正在收集停止结果', enumerating: '枚举所选范围', copying: '准备逐项复制',
  checking: '检查来源与目标', downloading: '下载当前文件', uploading: '上传当前文件',
  creating: '创建目录', publishing: '同步并排他发布', checking_result: '核对可获得结果', finished: '处理结束',
}
const resultLabels = { succeeded: '成功', skipped: '跳过', failed: '失败', unexecuted: '未执行', unconfirmed: '未确认' }
function currentPercent(task: UsbTaskSummary): number | null {
  const progress = task.progress
  if (!['uploading', 'downloading'].includes(progress.stage) || !progress.current_total) return null
  return Math.min(99, Math.max(0, Math.floor(progress.current_sent / progress.current_total * 100)))
}
function createdAt(task: UsbTaskSummary): string { return new Date(task.created_at * 1000).toLocaleString() }
</script>

<template>
  <section class="rounded-2xl border border-border bg-surface p-8" aria-labelledby="usb-tasks-title">
    <h2 id="usb-tasks-title" class="mb-[18px] text-[13px] font-semibold uppercase tracking-[0.5px] text-text-secondary">复制任务</h2>
    <p class="mb-5 text-[12px] leading-relaxed text-text-secondary">
      切换页面不会取消任务。取消执行中的任务会释放设备连接，原会话排队任务不会自动继续；排队任务可单独取消。
    </p>
    <div v-for="(error, index) in recordErrors" :key="error.record_id ?? index" role="alert" class="mb-3 rounded-xl border border-[#FFD7D7] bg-[#FFF5F5] px-4 py-3 text-[12px] text-error">
      <p>{{ error.message }}</p>
      <p v-if="error.record_id" class="mt-1 break-all">记录：{{ error.record_id }}</p>
      <button v-if="error.record_id" type="button" class="mt-2 cursor-pointer underline disabled:opacity-50" :disabled="Boolean(busy)" @click="error.record_id && emit('remove', error.record_id)">移除这条损坏记录（不删除传输文件）</button>
    </div>
    <p v-if="tasks.length === 0" class="text-[13px] text-text-tertiary">暂无复制任务。</p>
    <ol v-else class="space-y-4">
      <li v-for="task in tasks" :key="task.task_id" class="rounded-xl border border-border p-4">
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <div class="flex flex-wrap items-center gap-2 text-[13px]">
              <strong class="font-semibold text-text">{{ task.request.direction === 'download' ? '设备 → 本机' : '本机 → 设备' }}</strong>
              <span class="rounded bg-hover px-2 py-0.5 text-text-secondary">{{ labels[task.state] }}</span>
              <span v-if="task.historical" class="text-[11px] text-text-tertiary">历史记录 · 不会恢复执行</span>
            </div>
            <p class="mt-1 text-[11px] text-text-tertiary">{{ createdAt(task) }}</p>
          </div>
          <div class="flex flex-wrap gap-3 text-[12px]">
            <button type="button" class="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-border px-4 py-1.5 text-[12px] font-medium transition-all duration-200 hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50" @click="emit('details', task.task_id, 0)">查看条目</button>
            <button v-if="usbTaskActive(task)" type="button" class="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-error px-4 py-1.5 text-[12px] font-medium text-error transition-all duration-200 hover:bg-[#FFF5F5] disabled:cursor-not-allowed disabled:opacity-50" :disabled="Boolean(busy) || task.state === 'cancelling'" @click="emit('cancel', task.task_id)">{{ task.state === 'cancelling' ? '等待停止确认' : '取消' }}</button>
            <template v-else>
              <button type="button" class="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-border px-4 py-1.5 text-[12px] font-medium transition-all duration-200 hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50" @click="emit('retry', task)">准备新的复制</button>
              <button type="button" class="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-border px-4 py-1.5 text-[12px] font-medium text-text-secondary transition-all duration-200 hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50" :disabled="Boolean(busy)" @click="emit('remove', task.task_id)">移除记录</button>
            </template>
          </div>
        </div>
        <p class="mt-3 break-all text-[12px] text-text-secondary">目标：{{ task.target_label || '历史目标信息不可用' }}</p>
        <p class="mt-1 text-[12px] text-text-secondary">来源 {{ task.request.direction === 'download' ? task.request.source_objects.length : task.request.source_paths.length }} 项；引用仅属于原连接会话。</p>
        <p class="mt-3 text-[12px] text-text-secondary" aria-live="polite">{{ task.message }}</p>
        <template v-if="usbTaskActive(task)">
          <p class="mt-2 text-[12px] text-text-secondary">{{ stages[task.progress.stage] ?? task.progress.stage }}</p>
          <p v-if="task.progress.current_name" class="mt-1 break-all text-[12px] text-text-secondary">{{ task.progress.current_name }}</p>
          <p class="mt-2 text-[12px] text-text-secondary">
            已发现 {{ task.progress.discovered }} 项 · 已记录结果 {{ task.entry_count }} 项 · 已知大小 {{ formatUsbSize(task.progress.known_bytes) }}
            <span v-if="!task.progress.total_known"> · 总量尚不完整</span>
          </p>
          <div v-if="currentPercent(task) !== null" class="mt-3">
            <progress class="h-1.5 w-full overflow-hidden rounded-full bg-[#F0F0EC] accent-primary" :value="currentPercent(task) ?? 0" max="100" aria-label="当前文件的估算进度" />
            <p class="mt-1 text-[11px] text-text-secondary">当前文件约 {{ currentPercent(task) }}%；含协议开销，不是内容字节或整体进度。</p>
          </div>
        </template>
        <p class="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[12px] text-text-secondary">
          <span>复制／新建 {{ task.counts.succeeded }}</span><span>目录复用 {{ task.counts.reused }}</span>
          <span>跳过 {{ task.counts.skipped }}</span><span>失败 {{ task.counts.failed }}</span>
          <span>未执行 {{ task.counts.unexecuted }}</span><span>未确认 {{ task.counts.unconfirmed }}</span>
          <span>成功文件大小 {{ formatUsbSize(task.counts.copied_bytes) }}</span>
        </p>
        <p v-if="task.cancel_requested && task.state === 'interrupted'" class="mt-2 text-[12px] text-error">用户请求过取消，但未能确认正常停止，按中断保留结果。</p>
        <p v-if="task.stop_reason" class="mt-2 break-all text-[11px] text-text-secondary">停止原因：{{ task.stop_reason }}</p>
        <p v-if="task.record_error" role="alert" class="mt-2 text-[12px] text-error">{{ task.record_error }}</p>
        <p v-if="!task.enumeration_complete && !usbTaskActive(task)" class="mt-2 text-[12px] text-text-tertiary">枚举未完整结束，未发现的后代数量未知，以上统计不是完整来源总量。</p>

        <div v-if="selectedId === task.task_id" class="mt-4 border-t border-border pt-4">
          <p v-if="detailBusy" class="text-[12px] text-text-secondary" role="status">正在读取条目…</p>
          <p v-if="detailError" role="alert" class="text-[12px] text-error">{{ detailError }}</p>
          <template v-if="detail && detail.task.task_id === task.task_id">
            <p v-if="detail.entries.length === 0" class="text-[12px] text-text-tertiary">尚无条目结果；枚举期间不会虚构未发现内容。</p>
            <ul v-else class="divide-y divide-border">
              <li v-for="entry in detail.entries" :key="entry.entry_id" class="py-3 text-[12px]">
                <div class="flex items-start justify-between gap-3">
                  <p class="min-w-0 break-all text-text">{{ entry.raw_name || '未命名项目' }}</p>
                  <span class="shrink-0 text-text-secondary">{{ entry.reused ? '目录复用' : resultLabels[entry.status] }}</span>
                </div>
                <p class="mt-1 break-all text-text-secondary">来源：{{ entry.source }}</p>
                <p v-if="entry.destination" class="mt-1 break-all text-text-secondary">目标：{{ entry.destination }}</p>
                <p class="mt-1 break-all text-text-secondary">{{ entry.message }}</p>
                <p v-if="entry.residual" class="mt-2 break-all text-error">残留／未确认：{{ entry.residual }}。不会自动删除或重传。</p>
                <p v-if="entry.status === 'succeeded' && !entry.is_folder" class="mt-1 text-[11px] text-text-secondary">{{ entry.size_checked ? '已做基本大小核对' : '设备未提供可用大小，未作大小核对' }}；未逐字节校验。</p>
              </li>
            </ul>
            <div class="mt-3 flex items-center justify-between gap-2 text-[12px] text-text-secondary">
              <button type="button" class="inline-flex cursor-pointer items-center rounded-lg border border-border px-4 py-1.5 text-[12px] font-medium transition-all duration-200 hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50" :disabled="detailBusy || detail.offset === 0" @click="emit('details', task.task_id, Math.max(0, detail.offset - 50))">上一页</button>
              <span>{{ detail.total ? detail.offset + 1 : 0 }}–{{ detail.offset + detail.entries.length }} / {{ detail.total }}</span>
              <button type="button" class="inline-flex cursor-pointer items-center rounded-lg border border-border px-4 py-1.5 text-[12px] font-medium transition-all duration-200 hover:bg-hover disabled:cursor-not-allowed disabled:opacity-50" :disabled="detailBusy || detail.next_offset === null" @click="detail.next_offset !== null && emit('details', task.task_id, detail.next_offset)">下一页</button>
            </div>
          </template>
        </div>
      </li>
    </ol>
  </section>
</template>
