# Markdown 转 PDF

模块标识：`markdown-to-pdf`。返回 [项目结构](../项目结构文档.md)。

## 职责与入口

负责把 Markdown 转成 PDF，且整条链路不经过后端：前端在可终止 Worker 中解析 Markdown、代码高亮与公式并生成 HTML，主进程用独立的隐藏沙箱窗口 `printToPDF`，只把结果写到用户选择的路径。

这是全仓库唯一没有对应后端模块的工具；其数据面是 `window.desktopApi.markdownPdf` 与 `window.desktopApi.markdownSource` 两条 IPC 通道。

不负责 Markdown 转 Word（见 [Markdown 转 Word](markdown-to-word.md)），不负责通用窗口与退出协调（见 [桌面外壳](desktop-shell.md)）。

入口：前端 `frontend/src/views/tools/MarkdownToPdf.vue`，路由 `/tools/markdown-to-pdf`；主进程 `electron/markdown-to-pdf.ts`、`electron/markdown-source.ts`。

## 专属文件

| 文件 | 当前用途及纳入依据 |
| --- | --- |
| `frontend/src/views/tools/MarkdownToPdf.vue` | 页面状态机 `idle|ready|progress|preview|error`、选项（横向/页边距/字号/页码）、预览、导出与取消 |
| `frontend/src/features/markdown-pdf/prepare.ts` | `prepareMarkdownSource`：桌面端走 IPC 读取本地文件与图片，浏览器端解析上传的 `.md` 或 ZIP；图片等比缩小与 Data URL 预算 |
| `frontend/src/features/markdown-pdf/render.ts` | `renderMarkdown`（启动 Worker、超时与取消、DOMPurify 清洗）、`buildPdfHtml`（内联 `print.css` 与 CSS 变量） |
| `frontend/src/features/markdown-pdf/render.worker.ts` | Worker 内 `Marked` 解析、`highlight.js` 高亮、行内/块级公式与 SVG 围栏处理、图片与公式预算 |
| `frontend/src/features/markdown-pdf/print.css` | 打印样式，被 `buildPdfHtml` 以 `?raw` 内联 |
| `frontend/src/features/markdown-pdf/types.ts` | `PreparedMarkdown`、`PdfOptions`、`RenderedMarkdown`、`PdfDocument` |
| `electron/markdown-to-pdf.ts` | `registerMarkdownPdfIpc`、`exportDocument`、`cancelMarkdownPdf`；独立 `session.fromPartition('markdown-pdf-print')`、自定义 `https` 协议与请求白名单、CSP |
| `electron/markdown-to-pdf-types.ts` | `MarkdownPdfOptions`、`PrintRequest`、`MarkdownPdfResult`，主进程与 preload 共用 |
| `electron/markdown-source.ts` | `registerMarkdownSourceIpc`：读取本地 `.md` 或 ZIP，解析同目录与 Obsidian 库根图片并转 Data URL |
| `electron/markdown-source-types.ts` | `PreparedMarkdownPayload`，主进程与 preload 共用 |

`frontend/src/features/markdown/`（`source.ts`、`MarkdownSourcePicker.vue`）由两个 Markdown 工具共用，归 [公共记录](shared.md) 的 `frontend-shared-ui`。

## 公共与跨模块引用

路径书写：`backend/`、`frontend/`、`electron/` 开头的为仓库根相对路径；本节省略前缀的后端路径默认在 `backend/src/toolbox_backend/` 下，省略前缀的前端路径默认在 `frontend/src/` 下。

| 所属模块／公共记录 | 文件与使用范围 | 本模块为何引用 |
| --- | --- | --- |
| [公共记录](shared.md) `frontend-shared-ui` | `features/markdown/components/MarkdownSourcePicker.vue`、`features/markdown/source.ts` 的 `MarkdownSource` | 来源选择 |
| [公共记录](shared.md) `frontend-shared-ui` | `utils/math/engine.ts` 的 `initFormulaEngine`、`requireFormula` | Worker 内的公式渲染 |
| [公共记录](shared.md) `frontend-desktop-contract` | `frontend/src/types/electron.d.ts` 的 `markdownPdf`、`markdownSource` | 通道类型 |
| [桌面外壳](desktop-shell.md) | `main.ts` 的 `registerMarkdownPdfIpc`/`registerMarkdownSourceIpc` 注册点、`before-quit` 的 `cancelMarkdownPdf()` | 通道装配与退出清理 |
| [工具目录](tool-catalog.md) | `_TOOLS` 中 `markdown-to-pdf` 条目（固定 `available=True`） | 页面入口 |

## 关键调用链

1. `MarkdownSourcePicker` 产出 `MarkdownSource`；本地来源需要 `desktopApi.fileDialog.pickMarkdown()`。
2. `convert()` → `prepareMarkdownSource(selected)`：
   - `local`：`desktopApi.markdownSource.prepare(path)` → `markdown-source.ts` 读取文件、`_find_vault_root` 扩展图片搜索、超长边等比缩小后转 Data URL。
   - `upload` 且为 ZIP：`readUploadedArchive` 在页面内用 `inflateRaw` 解包，要求恰好一个 `.md`。
   - `upload` 且为 `.md`：直读文本，并给出「图片需改用桌面端」的警告。
3. `renderMarkdown(prepared, signal)` 新建模块化 Worker，180 秒超时；Worker 内 `initFormulaEngine` 后解析 Markdown，公式转 SVG、SVG 围栏按 `toSvgFigure` 白名单判断，图片与公式分别计预算。
4. 主线程收到结果后两次 `DOMPurify.sanitize`：一次生成 PDF 用 HTML（保留链接），一次生成预览用 HTML（禁止 `href`/`xlink:href`）。
5. `exportPdf()` → `buildPdfHtml(rendered.html, options)` 拼出完整文档 → `desktopApi.markdownPdf.export({requestId, filename, html, options})`。
6. 主进程 `exportDocument`：`isPrintRequest` 字段校验 → `requireOwner` 校验调用来源与页面 URL → `dialog.showSaveDialog` → 注册仅允许 `https://markdown-pdf.invalid/document` 主框架与 `data:image/*` 图片的请求白名单 → 新建隐藏 `BrowserWindow`（沙箱、独立 session、禁用权限）→ `printToPDF` → 写临时文件后 `rename` 到用户路径。
7. 取消：页面 `cancelExport()` → `markdown-pdf:cancel` → `cancelMarkdownPdf()` 中止当前 job 并关闭隐藏窗口；`before-quit` 也会中止，避免残留隐藏窗口。

## 状态与数据所有者

| 状态／资源 | 所有者 | 副本或消费者 | 生命周期／持久化 |
| --- | --- | --- | --- |
| 页面渲染状态 | `MarkdownToPdf.vue` 的 `phase`/`renderedDoc`/`controller`/`requestVersion` | 页面渲染 | 内存；`reset()` 会中止 Worker 与进行中的导出 |
| 打印作业 | `markdown-to-pdf.ts` 的 `activeJob` | `cancelMarkdownPdf`、`before-quit` | 单作业串行，结束或取消即释放 |
| 打印 session | `session.fromPartition('markdown-pdf-print', { cache: false })` | 每次导出复用的独立分区 | 进程内，不写缓存 |
| 输出 PDF | 用户通过保存对话框选择 | — | 磁盘，由用户管理 |
| 本地 Markdown 读取结果 | `markdown-source.ts` 返回值 | 前端 `PreparedMarkdown` | 单次调用，不落盘 |

## 生命周期与约束

- 渲染 Worker 可终止：`AbortController` 与 180 秒超时都会 `worker.terminate()`，避免复杂文档卡住页面。
- 图片 Data URL 与公式 SVG 分别设字符/字节预算，任一超限整篇失败而不是静默截断。
- 打印窗口完全离线：自定义 `https` 源 + CSP `default-src 'none'`，`webRequest` 只放行主框架与 `data:image/*`。
- 保存路径在用户确认后不再改写，避免绕过覆盖确认；写入用临时文件 + `rename`。
- 打包态页面走 `file://`，`registerMarkdownPdfIpc`/`registerMarkdownSourceIpc` 接收的 `trustedPageUrl` 由 `main.ts` 按 `isDev` 分别传入。
- 浏览器环境（Playwright 非 Electron 用例）没有 `desktopApi`，页面只能预览、不能导出。

## 当前覆盖边界

- `printToPDF` 的最终排版由 Electron/Chromium 决定，`print.css` 只控制页面内的样式与分页提示。
- `markdown-source.ts` 的图片解析范围限于同目录与可识别的 Obsidian 库根，远程图片不在此通道内解析。
