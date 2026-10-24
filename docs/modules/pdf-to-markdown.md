# PDF 转 Markdown

模块标识：`pdf-to-markdown`。返回 [项目结构](../项目结构文档.md)。

## 职责与入口

负责把一个 PDF 转成 Markdown，提供两条引擎：标准模式（PyMuPDF 逐页抽文本、图片与表格，同步完成）和深度模式（MinerU CLI 后台解析，异步轮询进度）。两条模式共用同一套任务目录约定、预览与下载实现。

不负责 MinerU 模型的下载与删除（见 [设置与模型管理](settings-models.md)），不负责 Markdown 的后续排版（见 [Markdown 转 Word](markdown-to-word.md)、[Markdown 转 PDF](markdown-to-pdf.md)）。

入口：`POST /api/v1/tools/pdf-to-markdown/{convert,progress,preview,download}`（`backend/src/toolbox_backend/modules/pdf_to_markdown/router.py`）；前端 `frontend/src/views/tools/PdfToMarkdown.vue`，路由 `/tools/pdf-to-markdown`。

## 专属文件

| 文件 | 当前用途及纳入依据 |
| --- | --- |
| `backend/src/toolbox_backend/modules/pdf_to_markdown/router.py` | 四个 POST 接口；`convert` 按 `deep_parse` 表单字段分流到标准或深度服务 |
| `backend/src/toolbox_backend/modules/pdf_to_markdown/service.py` | 标准模式 `convert_pdf`：逐页 `get_text`、`get_images`、`find_tables` 拼 Markdown |
| `backend/src/toolbox_backend/modules/pdf_to_markdown/deep_service.py` | 深度模式：`convert_pdf_deep`、单 worker `ProcessPoolExecutor`、`_run_mineru_convert`、进度关键词匹配、`stop_mineru_executor` |
| `backend/src/toolbox_backend/modules/pdf_to_markdown/result.py` | 共用的任务目录读写：`get_preview_detail`、`download_md`、`read_deep_status`、`write_status_atomic`、`normalize_output`、资源打包为 ZIP |
| `backend/src/toolbox_backend/modules/pdf_to_markdown/schemas.py` | `ConvertResponse`、`GetProgress*`、`GetPreview*`、`DownloadRequest` |
| `frontend/src/views/tools/PdfToMarkdown.vue` | 上传/拖拽、模式切换、进度条、左右对照预览、下载与告警展示 |
| `frontend/tests/pdf-integration.spec.ts`、`frontend/tests/tool-page.spec.ts` | 该页的浏览器用例 |

`frontend/src/api/tools.ts` 中本模块使用的函数归 [公共记录](shared.md) 的混合记录 `frontend-tools-api`。

## 公共与跨模块引用

路径书写：`backend/`、`frontend/`、`electron/` 开头的为仓库根相对路径；本节省略前缀的后端路径默认在 `backend/src/toolbox_backend/` 下，省略前缀的前端路径默认在 `frontend/src/` 下。

| 所属模块／公共记录 | 文件与使用范围 | 本模块为何引用 |
| --- | --- | --- |
| [公共记录](shared.md) `backend-file-storage` | `infrastructure/files.py` 的 `save_file`/`safe_filename`；`task_storage/workspace.py` 的 `UPLOADS_DIR`、`get_task_dir`、`ensure_task_path`、`validate_task_id` | 上传落盘与任务目录边界 |
| [公共记录](shared.md) `backend-integrations` | `integrations/mineru.py` 的 `build_convert_command`、`get_runtime_env` | 构造 MinerU 子进程命令 |
| [公共记录](shared.md) `backend-reusable-packages` | `modules/markdown_document/tables.py` 的 `html_tables_to_markdown`、`metrics.py` 的 `count_tables` | 深度结果后处理与表格统计 |
| [设置与模型管理](settings-models.md) | `modules/model_management/service.py` 的 `acquire_mineru_model_use`、`release_mineru_model_use`、`require_mineru_model` | 深度模式使用模型前后的占用登记 |
| [公共记录](shared.md) `frontend-tools-api` | `convertPdf`、`getProgress`、`getPreview`、`downloadMd` | 前端唯一 HTTP 通道 |
| [工具目录](tool-catalog.md) | `_TOOLS` 中 `pdf-to-markdown` 条目 | 页面入口与图标 |

## 关键调用链

### 标准模式

1. `handleFile` → `convertPdf(file, false)` → `POST /convert`（multipart）。
2. `service.convert_pdf`：校验扩展名与 50MB 上限 → 生成 12 位 `task_id` → 写 `meta.txt` → 存 `uploads/<task_id>-<name>` 并复制为任务目录 `input.pdf`。
3. `fitz.open` 逐页处理：`get_text`、`get_images`/`extract_image` 写 `images/pageN_M.ext`、`find_tables` 转管道表格；遇到加密 PDF 或解析异常转成 `UNSUPPORTED_FILE_FORMAT`/`CONVERSION_FAILED`。
4. 写 `output.md`，返回 `{task_id, filename, page_count}`。
5. 前端 `getPreview(taskId)` → `POST /preview` → `result.get_preview_detail` 读取 Markdown 与引用资源；下载时 `downloadMd` 由 `result.download_md` 返回单文件或含资源的 ZIP。

### 深度模式

1. `deepParse` 勾选后同一 `/convert` 进入 `deep_service.convert_pdf_deep`。
2. `acquire_mineru_model_use()` → `require_mineru_model()`（未就绪直接报错，不隐式下载）→ 落盘同上 → `write_status_atomic(task_dir, 0, "排队等待中...")`。
3. `_submit_mineru_task` 提交到单 worker `ProcessPoolExecutor`；工作进程崩溃（`BrokenProcessPool`）时重建执行器并重试一次。
4. `_run_mineru_convert` 在工作进程内 `subprocess.Popen` 启动 MinerU CLI，两个线程分别读 stdout/stderr，`_match_stage` 命中关键词即更新状态文件进度。
5. 完成或失败后 `_collect_output`/`_discard_partial_output` 整理输出，`future.add_done_callback` 释放模型占用。
6. 前端 `pollProgress` 轮询 `POST /progress` → `get_progress_detail` 读状态文件；成功后进入预览。

## 状态与数据所有者

| 状态／资源 | 所有者 | 副本或消费者 | 生命周期／持久化 |
| --- | --- | --- | --- |
| 任务目录 | `task_storage/workspace.py` 的 `get_task_dir` | 本模块全部读写 | `<data_root>/temp/tasks/<task_id>`，由启动清理按 24 小时窗口回收 |
| 上传原件 | `UPLOADS_DIR` | `convert_pdf`/`convert_pdf_deep` | `<data_root>/temp/uploads/<task_id>-<name>` |
| 深度解析进度 | `result.write_status_atomic` | `get_progress_detail`、前端轮询 | 任务目录内状态文件，原子写 |
| MinerU 执行器 | `deep_service._executor`（模块级单例） | `_submit_mineru_task`、`stop_mineru_executor` | 进程内单 worker，删除模型时被关闭 |
| 前端页面状态 | `PdfToMarkdown.vue` 的 `currentState`/`preview`/`progressValue` | 页面渲染 | 内存，切换文件时重置 |

## 生命周期与约束

- 深度解析必须串行：`max_workers=1`，避免每个任务各加载一份大模型。
- 深度解析不会隐式下载模型；模型未就绪时直接返回业务错误。
- 取消与超时通过 `_kill_process` 结束子进程，`MINERU_CONVERT_TIMEOUT` 控制上限（见 `core/config.py`）。
- 标准模式与深度模式产出的任务目录结构一致，因此预览与下载实现可共用。
- 上传体积上限 50MB 在两处独立校验（扩展名与大小），前端 `validateFile` 也做同样限制。

## 当前覆盖边界

- 深度模式的进度依赖 MinerU CLI 的 stdout/stderr 文本关键词，具体阶段文案由第三方 CLI 决定。
- 打包态 MinerU 入口为 `--toolbox-mineru`，源码态为 `mineru` 可执行文件，两者行为差异未在本模块内适配，由 `integrations/mineru.py` 承担。
