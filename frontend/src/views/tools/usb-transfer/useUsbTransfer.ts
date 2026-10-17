/** USB 页面状态：单飞轮询、会话代次、复制草稿及独立任务结果。 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import {
  cancelUsbTask, closeUsbSession, fetchUsbDirectory, fetchUsbStatus, fetchUsbTaskEntries,
  fetchUsbTasks, openUsbSession, prepareUsbCopy, removeUsbRecord, scanUsbDevices,
  submitUsbCopy, usbTaskActive,
} from '@/api/usbTransfer'
import type {
  UsbCopyRequest, UsbDeviceItem, UsbDirectoryEntry, UsbPreparedCopy, UsbRecordError,
  UsbStatus, UsbStorageItem, UsbTaskEntries, UsbTaskList, UsbTaskSummary,
} from '@/api/usbTransfer'

const ROOT = 0xffffffff
const POLL_MS = 2000

function message(error: unknown): string { return error instanceof Error ? error.message : '有线传输操作失败' }
function aborted(error: unknown): boolean { return error instanceof DOMException && error.name === 'AbortError' }

export function useUsbTransfer() {
  const status = ref<UsbStatus | null>(null)
  const loading = ref(true)
  const actionBusy = ref('')
  const errorMessage = ref('')
  const pollError = ref('')
  const devices = ref<UsbDeviceItem[]>([])
  const scanned = ref(false)
  const activeStorageId = ref<number | null>(null)
  const pathStack = ref<Array<{ folderId: number; name: string }>>([])
  const entries = ref<UsbDirectoryEntry[]>([])
  const listing = ref(false)
  const listError = ref('')
  const listingComplete = ref(false)
  const selectedIds = ref<number[]>([])
  const downloadTarget = ref('')
  const uploadPaths = ref<string[]>([])
  const prepared = ref<UsbPreparedCopy | null>(null)
  const draftNote = ref('')
  const tasks = ref<UsbTaskSummary[]>([])
  const recordErrors = ref<UsbRecordError[]>([])
  const taskBusy = ref('')
  const detailTaskId = ref('')
  const detail = ref<UsbTaskEntries | null>(null)
  const detailBusy = ref(false)
  const detailError = ref('')
  const scope = new AbortController()
  let directoryController: AbortController | undefined
  let detailController: AbortController | undefined
  let timer: ReturnType<typeof setTimeout> | undefined
  let alive = false
  let refreshing = false
  let statusToken = 0
  let directoryToken = 0
  let detailToken = 0
  let tasksToken = 0
  let scanId = ''

  const session = computed(() => status.value?.session ?? null)
  const storages = computed<UsbStorageItem[]>(() => session.value?.storages ?? [])
  const storageOptions = computed(() => storages.value.map((storage) => ({ value: String(storage.id), label: storage.description })))
  const currentStorage = computed(() => storages.value.find((item) => item.id === activeStorageId.value) ?? null)
  const currentFolder = computed(() => pathStack.value[pathStack.value.length - 1] ?? null)
  const currentDevicePath = computed(() => pathStack.value.map((item) => item.name).join(' / '))
  const deviceBusy = computed(() => Boolean(status.value?.busy || session.value?.closing))
  const readyForDevices = computed(() => Boolean(status.value?.platform_supported && status.value?.dependency_available))
  const sortedEntries = computed(() => [...entries.value].sort((a, b) => Number(b.is_folder) - Number(a.is_folder) || a.name.localeCompare(b.name, 'zh-Hans-CN')))
  const canPrepareUpload = computed(() => Boolean(session.value && currentFolder.value && uploadPaths.value.length && !session.value.closing))
  const canPrepareDownload = computed(() => Boolean(session.value && selectedIds.value.length && downloadTarget.value && !session.value.closing))

  function discardPrepared() { prepared.value = null }
  function invalidateDirectory() {
    directoryToken += 1
    directoryController?.abort()
    listing.value = false
    listingComplete.value = false
    selectedIds.value = []
    discardPrepared()
  }
  function resetNavigation() {
    invalidateDirectory()
    entries.value = []
    listError.value = ''
    const storage = storages.value[0]
    activeStorageId.value = storage?.id ?? null
    pathStack.value = storage ? [{ folderId: ROOT, name: storage.description }] : []
    if (storage && !deviceBusy.value) void loadDirectory()
  }
  function applyStatus(next: UsbStatus) {
    const previous = status.value
    if (previous?.instance_id === next.instance_id && next.revision < previous.revision) return
    const instanceChanged = previous !== null && previous.instance_id !== next.instance_id
    const sessionChanged = previous?.session?.session_id !== next.session?.session_id || instanceChanged
    status.value = next
    if (instanceChanged) {
      devices.value = []
      scanned.value = false
      scanId = ''
      detailToken += 1
      detailController?.abort()
      detail.value = null
      detailTaskId.value = ''
      tasks.value = []
    }
    if (sessionChanged) resetNavigation()
    if (next.session?.closing) invalidateDirectory()
  }
  function applyTasks(next: UsbTaskList) {
    if (status.value && status.value.instance_id !== next.instance_id) return
    const old = new Map(tasks.value.map((task) => [task.task_id, task]))
    tasks.value = next.tasks.map((task) => {
      const previous = old.get(task.task_id)
      return previous && previous.revision > task.revision ? previous : task
    })
    recordErrors.value = next.record_errors
  }
  function applyTask(task: UsbTaskSummary) {
    const index = tasks.value.findIndex((item) => item.task_id === task.task_id)
    if (index < 0) tasks.value = [task, ...tasks.value]
    else if (task.revision >= (tasks.value[index]?.revision ?? 0)) tasks.value.splice(index, 1, task)
  }

  async function refreshAll() {
    if (!alive || refreshing) return
    if (timer !== undefined) clearTimeout(timer)
    refreshing = true
    try {
      if (actionBusy.value || taskBusy.value) return
      const token = ++statusToken
      const next = await fetchUsbStatus(scope.signal)
      if (!alive || token !== statusToken) return
      applyStatus(next)
      const taskToken = ++tasksToken
      const nextTasks = await fetchUsbTasks(scope.signal)
      if (!alive || taskToken !== tasksToken) return
      applyTasks(nextTasks)
      pollError.value = ''
      const selected = tasks.value.find((task) => task.task_id === detailTaskId.value)
      if (selected && !detailBusy.value && (!detail.value || selected.revision > detail.value.task.revision)) {
        void openDetails(selected.task_id, detail.value?.offset ?? 0)
      }
    } catch (error) {
      if (alive && !aborted(error)) pollError.value = message(error)
    } finally {
      refreshing = false
      if (alive) {
        loading.value = false
        timer = setTimeout(() => { void refreshAll() }, POLL_MS)
      }
    }
  }

  async function runAction(name: string, action: () => Promise<void>) {
    if (actionBusy.value) return
    actionBusy.value = name
    errorMessage.value = ''
    statusToken += 1
    tasksToken += 1
    try { await action() }
    catch (error) { if (alive && !aborted(error)) errorMessage.value = message(error) }
    finally { if (alive) { actionBusy.value = ''; void refreshAll() } }
  }
  async function scan() {
    await runAction('scan', async () => {
      const next = await scanUsbDevices(scope.signal)
      if (!alive || next.instance_id !== status.value?.instance_id) return
      scanId = next.scan_id
      devices.value = next.devices
      scanned.value = true
    })
  }
  async function connect(device: UsbDeviceItem) {
    const instance = status.value?.instance_id
    if (!instance || !scanId) return
    await runAction(`connect:${device.device_id}`, async () => {
      const next = await openUsbSession(instance, scanId, device.device_id, scope.signal)
      if (alive) applyStatus(next)
    })
  }
  async function disconnect() {
    const current = session.value
    const instance = status.value?.instance_id
    if (!current || !instance) return
    if (tasks.value.some((task) => usbTaskActive(task) && task.request.session_id === current.session_id)
      && !window.confirm('断开将停止当前复制，并中断该会话的排队任务。已完成内容不回滚，设备中可能有残留。继续断开？')) return
    await runAction('disconnect', async () => {
      invalidateDirectory()
      const next = await closeUsbSession(instance, current.session_id, scope.signal)
      if (alive) applyStatus(next)
    })
  }
  async function loadDirectory() {
    const instance = status.value?.instance_id
    const current = session.value
    const storage = activeStorageId.value
    const folder = currentFolder.value
    if (!instance || !current || storage === null || !folder || deviceBusy.value) return
    invalidateDirectory()
    const token = directoryToken
    directoryController = new AbortController()
    const controller = directoryController
    listing.value = true
    listError.value = ''
    try {
      const next = await fetchUsbDirectory(instance, current.session_id, storage, folder.folderId, controller.signal)
      if (!alive || token !== directoryToken || status.value?.instance_id !== next.instance_id || session.value?.session_id !== next.session_id) return
      entries.value = next.entries
      listingComplete.value = next.complete
      listError.value = next.message
    } catch (error) {
      if (alive && token === directoryToken && !aborted(error)) {
        listError.value = message(error)
        listingComplete.value = false
      }
    } finally { if (alive && token === directoryToken) listing.value = false }
  }
  function changeStorage(value: string) {
    if (deviceBusy.value) return
    const storage = storages.value.find((item) => item.id === Number(value))
    if (!storage) return
    invalidateDirectory()
    activeStorageId.value = storage.id
    pathStack.value = [{ folderId: ROOT, name: storage.description }]
    entries.value = []
    void loadDirectory()
  }
  function enterFolder(entry: UsbDirectoryEntry) {
    if (!entry.is_folder || deviceBusy.value || listing.value) return
    invalidateDirectory()
    entries.value = []
    pathStack.value.push({ folderId: entry.object_id, name: entry.name })
    void loadDirectory()
  }
  function goToCrumb(index: number) {
    if (deviceBusy.value || listing.value || index >= pathStack.value.length - 1) return
    invalidateDirectory()
    entries.value = []
    pathStack.value = pathStack.value.slice(0, index + 1)
    void loadDirectory()
  }
  function toggleEntry(id: number) {
    discardPrepared()
    if (selectedIds.value.includes(id)) selectedIds.value = selectedIds.value.filter((item) => item !== id)
    else if (selectedIds.value.length < 100) selectedIds.value.push(id)
    else errorMessage.value = '一次最多选择 100 项'
  }
  async function pickLocal(kind: 'files' | 'folder' | 'target') {
    await runAction('picker', async () => {
      const dialog = window.desktopApi?.fileDialog
      if (!dialog) throw new Error('请通过工具盒子桌面应用选择本机路径')
      if (kind === 'files') {
        const picked = await dialog.pickFiles()
        if (alive && picked.length) { uploadPaths.value = picked.map((item) => item.path); discardPrepared() }
      } else {
        const path = await dialog.pickDirectory()
        if (!alive || !path) return
        if (kind === 'target') downloadTarget.value = path
        else uploadPaths.value = [path]
        discardPrepared()
      }
    })
  }
  async function prepare(direction: 'download' | 'upload') {
    const current = session.value
    const instance = status.value?.instance_id
    if (!current || !instance) return
    const request: UsbCopyRequest = {
      instance_id: instance, session_id: current.session_id, direction,
      source_objects: direction === 'download' ? entries.value.filter((entry) => selectedIds.value.includes(entry.object_id)).map((entry) => ({ storage_id: entry.storage_id, object_id: entry.object_id })) : [],
      source_paths: direction === 'upload' ? [...uploadPaths.value] : [],
      local_target: direction === 'download' ? downloadTarget.value : null,
      target_storage_id: direction === 'upload' ? activeStorageId.value : null,
      target_folder_id: direction === 'upload' ? currentFolder.value?.folderId ?? null : null,
    }
    await runAction('prepare', async () => {
      const next = await prepareUsbCopy(request, scope.signal)
      if (alive && session.value?.session_id === current.session_id && status.value?.instance_id === instance) prepared.value = next
    })
  }
  async function submit() {
    const draft = prepared.value
    if (!draft) return
    await runAction('submit', async () => {
      const task = await submitUsbCopy(draft, scope.signal)
      if (!alive) return
      applyTask(task)
      prepared.value = null
      selectedIds.value = []
      draftNote.value = '任务已交给后端；切换页面不会取消。'
    })
  }
  async function cancel(taskId: string) {
    if (taskBusy.value) return
    taskBusy.value = taskId
    tasksToken += 1
    try {
      const next = await cancelUsbTask(taskId, scope.signal)
      if (alive) applyTask(next)
    } catch (error) { if (alive && !aborted(error)) errorMessage.value = message(error) }
    finally { if (alive) { taskBusy.value = ''; void refreshAll() } }
  }
  async function remove(taskId: string) {
    if (taskBusy.value || !window.confirm('仅移除此任务的状态记录，不删除本机文件或设备残留。移除后不再保留这些异常线索，继续？')) return
    taskBusy.value = taskId
    tasksToken += 1
    try {
      const next = await removeUsbRecord(taskId, scope.signal)
      if (!alive) return
      applyTasks(next)
      if (detailTaskId.value === taskId) {
        detailToken += 1
        detailController?.abort()
        detailTaskId.value = ''
        detail.value = null
      }
    } catch (error) { if (alive && !aborted(error)) errorMessage.value = message(error) }
    finally { if (alive) { taskBusy.value = ''; void refreshAll() } }
  }
  async function openDetails(taskId: string, offset = 0) {
    const token = ++detailToken
    detailController?.abort()
    detailController = new AbortController()
    const instance = status.value?.instance_id
    if (detailTaskId.value !== taskId) detail.value = null
    detailTaskId.value = taskId
    detailBusy.value = true
    detailError.value = ''
    try {
      const next = await fetchUsbTaskEntries(taskId, offset, detailController.signal)
      if (alive && token === detailToken && instance === status.value?.instance_id && next.instance_id === instance) detail.value = next
    } catch (error) { if (alive && token === detailToken && !aborted(error)) detailError.value = message(error) }
    finally { if (alive && token === detailToken) detailBusy.value = false }
  }
  function retry(task: UsbTaskSummary) {
    discardPrepared()
    selectedIds.value = []
    if (task.request.direction === 'upload') {
      uploadPaths.value = [...task.request.source_paths]
      draftNote.value = '已恢复本机来源草稿。请在当前会话重新浏览并确认设备目标，再准备新任务；设备残留不会自动清理。'
    } else {
      downloadTarget.value = ''
      draftNote.value = '请重新浏览设备、选择来源和本机目标后准备新任务；未复用历史对象 ID。'
    }
  }

  onMounted(() => { alive = true; void refreshAll() })
  onBeforeUnmount(() => {
    alive = false
    statusToken += 1
    tasksToken += 1
    directoryToken += 1
    detailToken += 1
    scope.abort()
    directoryController?.abort()
    detailController?.abort()
    if (timer !== undefined) clearTimeout(timer)
  })

  return {
    status, loading, actionBusy, errorMessage, pollError, devices, scanned, session,
    storages, storageOptions, activeStorageId, currentStorage, currentFolder, currentDevicePath,
    pathStack, sortedEntries, listing, listError, listingComplete, selectedIds, deviceBusy,
    readyForDevices, downloadTarget, uploadPaths, prepared, draftNote, canPrepareUpload,
    canPrepareDownload, tasks, recordErrors, taskBusy, detailTaskId, detail, detailBusy, detailError,
    refreshAll, scan, connect, disconnect, loadDirectory, changeStorage, enterFolder, goToCrumb,
    toggleEntry, pickLocal, prepare, submit, discardPrepared, cancel, remove, openDetails, retry,
  }
}
