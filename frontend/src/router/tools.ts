import type { RouteRecordRaw } from 'vue-router'
import type { ToolConfig } from '@/types/tool'

export const toolConfigs: ToolConfig[] = [
  {
    id: 'pdf-to-markdown',
    path: 'pdf-to-markdown',
    name: 'PdfToMarkdown',
    displayName: 'PDF 转 Markdown',
    description: '将 PDF 文件转换为 Markdown 格式，保留文本、表格与图片',
    icon: ['fas', 'file-pdf'],
    component: () => import('@/views/tools/PdfToMarkdown.vue'),
    sidebarDefaultCollapsed: false
  }
]

export function generateToolRoutes(): RouteRecordRaw[] {
  return toolConfigs.map((tool) => ({
    path: tool.path,
    name: tool.name,
    component: tool.component,
    meta: {
      id: tool.id,
      title: tool.displayName,
      icon: tool.icon,
      description: tool.description,
      sidebarDefaultCollapsed: tool.sidebarDefaultCollapsed ?? true
    }
  }))
}
