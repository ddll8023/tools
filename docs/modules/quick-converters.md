# 单次转换工具

模块标识：`quick-converters`。返回 [项目结构](../项目结构文档.md)。

## 职责与入口

汇集五个「一次请求、同步完成」的转换工具。它们的共同特征是：上传后在同一个请求内完成转换并返回 `task_id`，随后用另一个 POST 下载结果；没有后台任务、进度轮询或跨请求状态机。因此按能力合并为一个模块，而不是五份近乎相同的文档。

包含的工具：

| 工具 | 页面 | 后端路由前缀 |
| --- | --- | --- |
| PDF 转 Word | `frontend/src/views/tools/PdfToWord.vue` | `/api/v1/tools/pdf-to-word` |
| Word 转 PDF | `frontend/src/views/tools/WordToPdf.vue` | `/api/v1/tools/word-to-pdf` |
| EPUB 转 Markdown | `frontend/src/views/tools/EpubToMarkdown.vue` | `/api/v1/tools/epub-to-markdown` |
| 图片格式转换 | `frontend/src/views/tools/ImageConverter.vue` | `/api/v1/tools/image-converter` |
| 文本/文件转二维码 | `frontend/src/views/tools/QrCode.vue` | `/api/v1/tools/qr-code` |

不负责 PDF 转 Markdown（有双引擎与异步进度，见 [PDF 转 Markdown](pdf-to-markdown.md)）、Markdown 转 Word（有本地路径与资源包来源，见 [Markdown 转 Word](markdown-to-word.md)）。

## 专属文件

### PDF 转 Word

| 文件 | 当前用途及纳入依据 |
| --- | --- |
| `backend/src/toolbox_backend/modules/pdf_to_word/router.py` | `POST /convert`、`POST /download` |
| `backend/src/toolbox_backend/modules/pdf_to_word/service.py` | `_inspect_pdf`（页数/文字层页数）、`_convert_with_pdf2docx`、`_validate_docx`、`convert_pdf_to_word`、`download_docx`；`DOCX_MEDIA_TYPE` |
| `backend/src/toolbox_backend/modules/pdf_to_word/schemas.py` | `ConvertResponse`、`DownloadRequest` |
| `frontend/src/views/tools/PdfToWord.vue` | 上传、转换、下载；50MB 上限 |
| `frontend/tests/pdf-to-word.spec.ts` | 该页用例 |

文字层不足时 `PdfInspection.warnings` 给出「部分页面未检测到文字层，转换结果可能需要人工校对」。

### Word 转 PDF

| 文件 | 当前用途及纳入依据 |
| --- | --- |
| `backend/src/toolbox_backend/modules/word_to_pdf/router.py` | `POST /convert`、`POST /download` |
| `backend/src/toolbox_backend/modules/word_to_pdf/service.py` | `convert_word`、`download_pdf`；`SUPPORTED_EXTENSIONS = (".docx", ".doc")`；转换前对 `.docx` 调 `sanitize_office_document` 剔除宏、ActiveX 与外部关系 |
| `backend/src/toolbox_backend/modules/word_to_pdf/schemas.py` | `ConvertResponse`、`DownloadRequest` |
| `frontend/src/views/tools/WordToPdf.vue` | 上传、转换、下载；50MB 上限 |

依赖 LibreOffice；未检测到时该工具在工具目录中 `available=false`，前端路由守卫会重定向首页。

### EPUB 转 Markdown

| 文件 | 当前用途及纳入依据 |
| --- | --- |
| `backend/src/toolbox_backend/modules/epub_to_markdown/router.py` | `POST /convert`、`/preview`、`/download`（返回 ZIP） |
| `backend/src/toolbox_backend/modules/epub_to_markdown/service.py` | `convert_epub_file`、`download_epub_markdown`；50MB 上限 |
| `backend/src/toolbox_backend/modules/epub_to_markdown/helpers.py` | `validate_and_extract_epub`、`_parse_package`、`_ordered_spine`、`convert_epub`、`_replace_image_links`、`get_preview_detail`、`create_download_zip`；`_safe_member_name` 阻断 ZIP 路径穿越 |
| `backend/src/toolbox_backend/modules/epub_to_markdown/schemas.py` | `ConvertResponse`、`GetPreviewRequest`、`GetPreviewResponse` |
| `frontend/src/views/tools/EpubToMarkdown.vue` | 上传、转换、Markdown 预览（`marked` + `highlight.js`）、ZIP 下载 |

章节顺序按 OPF spine 与 nav/NCX 解析，图片链接重写为本地 `images/` 相对路径。

### 图片格式转换

| 文件 | 当前用途及纳入依据 |
| --- | --- |
| `backend/src/toolbox_backend/modules/image_converter/router.py` | `POST /convert`（多文件）、`/download`（按 `file_index`）、`/download-all` |
| `backend/src/toolbox_backend/modules/image_converter/service.py` | `convert_images`、`download_file`、`_normalize_mode`、`_save_single`、`_process_tiff_multi_page`、`_process_animated_gif`、`_check_pixel_limit`；`MAX_FILE_SIZE`/`MAX_BATCH_COUNT`/`MAX_PIXEL_COUNT` |
| `backend/src/toolbox_backend/modules/image_converter/schemas.py` | `ConvertResponse`、`ConvertFileItem`、`DownloadRequest`、`DownloadAllRequest` |
| `frontend/src/views/tools/ImageConverter.vue` | 多文件选择、目标格式与质量、单张预览、单张/全部下载 |

支持 `png/jpeg/webp/bmp/gif/tiff`；TIFF 多页与动态 GIF 拆分为多个输出文件。

### 二维码

| 文件 | 当前用途及纳入依据 |
| --- | --- |
| `backend/src/toolbox_backend/modules/qr_code/router.py` | `POST /generate`（`content` 与 `file` 二选一） |
| `backend/src/toolbox_backend/modules/qr_code/service.py` | `generate_qr_code`、`_validate_payload`、`_build_file_payload`、`_render_qr_png`；`MAX_QR_PAYLOAD_BYTES=2500`、`MAX_FILE_SIZE=1500` |
| `backend/src/toolbox_backend/modules/qr_code/schemas.py` | `GenerateResponse` |
| `frontend/src/views/tools/QrCode.vue` | 文本/文件两种输入、预览、下载 |

使用 `reportlab.graphics.barcode.qrencoder` 编码、Pillow 绘制，返回 `image_data_url`。

## 公共与跨模块引用

路径书写：`backend/`、`frontend/`、`electron/` 开头的为仓库根相对路径；本节省略前缀的后端路径默认在 `backend/src/toolbox_backend/` 下，省略前缀的前端路径默认在 `frontend/src/` 下。

| 所属模块／公共记录 | 文件与使用范围 | 本模块为何引用 |
| --- | --- | --- |
| [公共记录](shared.md) `backend-file-storage` | `infrastructure/files.py` 的 `safe_filename`/`save_file`；`task_storage/workspace.py` 的 `get_task_dir`、`ensure_task_path`、`validate_task_id`、`UPLOADS_DIR` | 全部五个工具的任务目录与文件名净化 |
| [公共记录](shared.md) `backend-integrations` | `integrations/libreoffice.py` 的 `convert_to_pdf` | Word 转 PDF |
| [公共记录](shared.md) `backend-reusable-packages` | `modules/markdown_document/metrics.py` 的 `count_tables` | EPUB 预览的表格统计 |
| [公共记录](shared.md) `frontend-tools-api` | `convertPdfToWord`、`downloadWord`、`convertWord`、`downloadPdf`、`convertEpub`、`getEpubPreview`、`downloadEpub`、`convertImages`、`downloadConvertedFile`、`downloadAllConverted`、`generateQrCode` | 前端唯一 HTTP 通道 |
| [公共记录](shared.md) `frontend-api-client` | `api/client.ts` 的 `apiFetch` | `ImageConverter.vue` 直接调用下载接口时使用 |
| [工具目录](tool-catalog.md) | `_TOOLS` 中对应五个条目 | 页面入口；Word 转 PDF 的可用性随 LibreOffice 探测 |
| [局域网投送](lan-transfer.md) | `generateQrCode` | 该模块借用二维码能力生成访问入口，不复制实现 |

## 关键调用链

五者结构一致，以 PDF 转 Word 为例：

1. 页面校验扩展名与大小 → `convertPdfToWord(file)` → `POST /tools/pdf-to-word/convert`。
2. `convert_pdf_to_word`：`safe_filename` → 生成 12 位 `task_id` → 写 `meta.json` → `_inspect_pdf` 记录页数与文字层页数 → `_convert_with_pdf2docx` 生成 `output.docx` → `_validate_docx` 校验 ZIP 结构与必需条目。
3. 返回 `ConvertResponse`（含 `warnings`）；前端展示警告。
4. 下载 → `downloadWord(task_id)` → `POST /download` → `download_docx` 校验 `task_id` 与 `ensure_task_path` 后 `FileResponse`。

差异点：

- Word 转 PDF：`convert_word` 落盘后调 `convert_to_pdf`（LibreOffice 子进程），再 `download_pdf` 返回。
- EPUB 转 Markdown：`convert_epub_file` 解包并 `convert_epub` 产出 Markdown 与 `images/`；`preview` 读回 Markdown，`download` 由 `create_download_zip` 打包为 ZIP。
- 图片格式转换：`convert_images` 逐个文件处理，记录 `ConvertFileItem` 列表；下载按 `file_index` 或全部打包。
- 二维码：不建任务目录，直接把 PNG 编码为 Data URL 返回。

## 状态与数据所有者

| 状态／资源 | 所有者 | 副本或消费者 | 生命周期／持久化 |
| --- | --- | --- | --- |
| 任务目录与产物 | 各 `service.py` 的转换函数 | 对应 `download_*` 函数、启动清理 | `<data_root>/temp/tasks/<task_id>`；二维码无任务目录 |
| 上传原件 | `UPLOADS_DIR`（PDF 转 Word、Word 转 PDF、EPUB） | 转换函数 | 随任务清理 |
| 前端页面状态 | 各 `.vue` 的 ref | 页面渲染 | 内存 |
| 二维码结果 | `qr_code/service.py` 返回值 | 页面直接展示 | 不落盘 |

## 生命周期与约束

- 五个工具都在单次请求内完成转换，前端不需要轮询；失败直接以 `{code,message}` 返回。
- 上传上限：PDF 转 Word、Word 转 PDF、EPUB 均 50MB；图片转换单文件 50MB、批量 20 张、总像素 4000 万；二维码内容 2500 字节、文件 1500 字节。
- ZIP 解包（EPUB）与任务路径（全部）都做穿越校验，落点限定在任务目录或 `TEMP_DIR` 内。
- Word 转 PDF 依赖外部 LibreOffice，其可用性由启动探测决定，不在本模块内检测。
- LibreOffice 转换受 `LIBREOFFICE_MAX_CONCURRENCY` 并发额度约束，排队超时直接报错而非无限等待；`.docx` 在转换前经 `sanitize_office_document` 剔除宏、ActiveX 与外部关系；输出文件名偏离预期时回落到输出目录内唯一的同扩展名文件。

## 当前覆盖边界

- `pdf2docx` 与 LibreOffice 的实际转换质量由第三方实现决定，本模块只做输入校验与产物有效性检查。
- 图片转换的多页 TIFF 与动态 GIF 拆分逻辑只在源码中体现，未覆盖所有厂商变体。
