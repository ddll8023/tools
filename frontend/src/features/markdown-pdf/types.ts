/** Markdown PDF 资源、渲染结果与打印选项的前端契约。 */
export interface PreparedMarkdown {
  filename: string
  markdown_content: string
  images: Record<string, string>
  warnings: string[]
}

export interface PdfOptions {
  landscape: boolean
  marginMm: number
  fontSize: number
  pageNumbers: boolean
}

export interface RenderedMarkdown {
  html: string
  warnings: string[]
}

export interface PdfDocument extends RenderedMarkdown {
  previewHtml: string
}
