import { ref } from 'vue'
import type { RouteRecordRaw } from 'vue-router'
import type { ToolConfig } from '@/types/tool'
import { fetchToolList } from '@/api/tools'

const toolConfigs = ref<ToolConfig[]>([])

/** 本地注册表：仅存储组件导入等前端特有字段 */
const toolLocalRegistry: Record<string, Pick<ToolConfig, 'icon' | 'component'>> = {
  'pdf-to-markdown': {
    icon: ['fas', 'file-pdf'],
    component: () => import('@/views/tools/PdfToMarkdown.vue'),
  },
  'pdf-to-word': {
    icon: ['fas', 'file-word'],
    component: () => import('@/views/tools/PdfToWord.vue'),
  },
  'word-to-pdf': {
    icon: ['fas', 'file-word'],
    component: () => import('@/views/tools/WordToPdf.vue'),
  },
  'epub-to-markdown': {
    icon: ['fas', 'book'],
    component: () => import('@/views/tools/EpubToMarkdown.vue'),
  },
  'image-converter': {
    icon: ['fas', 'image'],
    component: () => import('@/views/tools/ImageConverter.vue'),
  },
  'qr-code': {
    icon: ['fas', 'qrcode'],
    component: () => import('@/views/tools/QrCode.vue'),
  },
}

/** 从后端获取工具列表并与本地注册表合并 */
export async function initToolConfigs(): Promise<ToolConfig[]> {
  try {
    const remoteList = await fetchToolList()

    const merged: ToolConfig[] = remoteList.map((remote) => {
      const local = toolLocalRegistry[remote.id]
      return {
        id: remote.id,
        path: remote.path,
        name: remote.name,
        displayName: remote.display_name,
        description: remote.description,
        icon: local?.icon ?? (remote.icon as string).split(' ') as unknown as string[],
        component: local?.component ?? (() => Promise.reject(new Error(`未知工具: ${remote.id}`))),
        sidebarDefaultCollapsed: false,
        available: remote.available,
      }
    })

    toolConfigs.value = merged
    return merged
  } catch {
    toolConfigs.value = []
    return []
  }
}

export { toolConfigs }

export function generateToolRoutes(configs: ToolConfig[]): RouteRecordRaw[] {
  return configs.map((tool) => ({
    path: tool.path,
    name: tool.name,
    component: tool.component,
    meta: {
      id: tool.id,
      title: tool.displayName,
      icon: tool.icon,
      description: tool.description,
      sidebarDefaultCollapsed: tool.sidebarDefaultCollapsed ?? true,
    },
  }))
}
