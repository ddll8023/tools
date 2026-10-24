# Markdown 转 Word

模块标识：`markdown-to-word`。返回 [项目结构](../项目结构文档.md)。

## 职责与入口

负责把 Markdown（上传文件、含图片的 ZIP 资源包，或桌面端选择的本地绝对路径）转换为 DOCX，并在需要 `.doc` 时借助 LibreOffice 二次转换。转换过程解析标题、列表、表格、代码块、行内/块级公式与 SVG，并把公式和 SVG 渲染成可嵌入的 PNG。

不负责 Markdown 转 PDF（见 [Markdown 转 PDF](markdown-to-pdf.md)），不负责来源选择器的交互（`frontend/src/features/markdown/` 归公共记录）。

入口：`POST /api/v1/tools/markdown-to-word/{convert,download}`（`backend/src/toolbox_backend/modules/markdown_to_word/router.py`）；前端 `frontend/src/views/tools/MarkdownToWord.vue`，路由 `/tools/markdown-to-word`。

## 专属文件

| 文件 | 当前用途及纳入依据 |
| --- | --- |
| `backend/src/toolbox_backend/modules/markdown_to_word/router.py` | `convert`（multipart，`file`/`source_path` 二选一）与 `download` |
| `backend/src/toolbox_backend/modules/markdown_to_word/service.py` | `convert_markdown_to_word`、`download_word`、`_validate_docx`/`_validate_doc`、`meta.json` 读写、失败时清理任务目录 |
| `backend/src/toolbox_backend/modules/markdown_to_word/schemas.py` | `ConvertResponse`（含 `output_format`、`warnings`）、`DownloadRequest` |
| `backend/src/toolbox_backend/modules/markdown_document/docx.py` | `render_markdown_to_docx`、`MarkdownDocxRenderer`、`DocumentRenderOptions`、math/SVG 解析规则（`_math_inline_rule`、`_math_block_rule`、`_svg_block_rule`） |
| `backend/src/toolbox_backend/modules/markdown_document/source.py` | `prepare_markdown_source`、`read_markdown`、`MarkdownSource`、`MarkdownInputError`；本地目录与 Obsidian 库根图片查找、ZIP 解包与路径校验 |
| `backend/src/toolbox_backend/modules/markdown_document/graphics.py` | `render_formula_png`、`render_svg_png`；matplotlib 与 PyMuPDF 延迟导入 |
| `frontend/src/views/tools/MarkdownToWord.vue` | 来源选择、输出格式选择、转换与下载、警告展示 |

`markdown_document` 的另外两个文件 `tables.py`、`metrics.py` 有多个消费者，归 [公共记录](shared.md) 的 `backend-reusable-packages`。

## 公共与跨模块引用

路径书写：`backend/`、`frontend/`、`electron/` 开头的为仓库根相对路径；本节省略前缀的后端路径默认在 `backend/src/toolbox_backend/` 下，省略前缀的前端路径默认在 `frontend/src/` 下。

| 所属模块／公共记录 | 文件与使用范围 | 本模块为何引用 |
| --- | --- | --- |
| [公共记录](shared.md) `backend-file-storage` | `infrastructure/files.py` 的 `safe_filename`；`task_storage/workspace.py` 的 `get_task_dir`、`ensure_task_path`、`validate_task_id` | 任务目录与文件名净化 |
| [公共记录](shared.md) `backend-integrations` | `integrations/libreoffice.py` 的 `convert_to_doc` | `.doc` 输出 |
| [公共记录](shared.md) `frontend-shared-ui` | `features/markdown/components/MarkdownSourcePicker.vue`、`features/markdown/source.ts` 的 `MarkdownSource` | 上传/本地路径来源选择 |
| [公共记录](shared.md) `frontend-tools-api` | `convertMarkdownToWord`、`convertLocalMarkdownToWord`、`downloadMarkdownToWord` 及 DTO | 前端唯一 HTTP 通道 |
| [桌面外壳](desktop-shell.md) | `desktopApi.fileDialog.pickMarkdown()` | 本地路径来源 |

## 关键调用链

1. `MarkdownToWord.vue` 通过 `MarkdownSourcePicker` 得到 `MarkdownSource`（`upload` 或 `local`）。
2. 上传分支调 `convertMarkdownToWord(file, format)`；本地分支调 `convertLocalMarkdownToWord(path, format)`，后者把绝对路径放进 `source_path` 表单字段。
3. `router.convert` → `service.convert_markdown_to_word`：校验 `output_format` 属于 `docx|doc` → 建任务目录 → `prepare_markdown_source` 决定来源。
4. `prepare_markdown_source`：本地路径时校验扩展名与目录，`_find_vault_root` 识别 Obsidian 库根以扩展图片搜索范围；ZIP 时 `_extract_archive` 校验成员路径（`_archive_destination` 阻断穿越）。
5. `read_markdown` 读 UTF-8 内容 → `render_markdown_to_docx(markdown, search_dirs, docx_path)` 返回 `warnings`（图片缺失等）。
6. 若 `output_format == "doc"`，`convert_to_doc` 调 LibreOffice 把 DOCX 转 DOC，并 `_validate_doc`。
7. `_validate_docx` 检查 ZIP 完整性与 `[Content_Types].xml`、`word/document.xml` 存在；写 `meta.json`（`filename`/`output_filename`/`output_format`/`warnings`）。
8. 返回 `ConvertResponse`；前端展示 `warnings`，下载走 `download_word` 按 `meta.json` 决定文件名与媒体类型。
9. 任一步失败都 `shutil.rmtree(task_dir)` 后抛出对应业务错误（格式不支持、编码非 UTF-8、转换失败）。

## 状态与数据所有者

| 状态／资源 | 所有者 | 副本或消费者 | 生命周期／持久化 |
| --- | --- | --- | --- |
| 任务目录与产物 | `service.convert_markdown_to_word` | `download_word`、启动清理 | `<data_root>/temp/tasks/<task_id>`，含 `output.docx`/`output.doc`、`meta.json` |
| 解包后的资源 | `source._extract_archive` | `render_markdown_to_docx` 的 `search_dirs` | 任务目录内，随任务清理 |
| 转换警告 | `render_markdown_to_docx` 返回值 | `meta.json`、前端提示 | 随任务目录保留 |
| 前端来源与结果 | `MarkdownToWord.vue` 的 ref | 页面渲染 | 内存 |

## 生命周期与约束

- `file` 与 `source_path` 至少提供一个，两者都缺时 `prepare_markdown_source` 抛 `MarkdownInputError`。
- 本地路径读取只在桌面端可用；浏览器环境下前端不展示该入口。
- 图片缺失时，上传来源额外给出一条恢复提示（改用本地 Markdown 或 ZIP 资源包），本地来源不再追加。
- DOC 转换的超时由 `integrations/libreoffice.py` 的 `LIBREOFFICE_CONVERT_TIMEOUT` 控制（见 `core/config.py`）。
- DOCX 有效性通过 ZIP 结构与必需条目校验，不依赖文件大小阈值。

## 当前覆盖边界

- `docx.py` 的渲染覆盖范围由 `MarkdownIt` 规则决定，未逐条穷举所有 Markdown 扩展语法。
- 公式与 SVG 转 PNG 依赖 matplotlib 与 PyMuPDF 的渲染能力，具体失败原因通过 `warnings` 暴露。
