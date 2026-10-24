/** 本地 Markdown 读取通道的返回契约，主进程与 preload 共用。 */
export interface PreparedMarkdownPayload {
  filename: string
  /** 文件内容使用 camelCase，避免把后端 snake_case DTO 约定带到桌面通道。 */
  markdownContent: string
  /** 图片原始引用路径 → Data URL；渲染进程按原样查表替换。 */
  images: Record<string, string>
  warnings: string[]
  error?: string
}
