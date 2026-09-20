/** Markdown 工具共用的文件来源，不包含转换参数或页面状态。 */
export type MarkdownSource =
  | { kind: 'upload'; name: string; size: number; file: File }
  | { kind: 'local'; name: string; size: number; path: string }
