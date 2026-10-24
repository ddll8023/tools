# 公共记录

本页集中登记共享能力、混合职责和全局上下文。源码路径相对仓库根；模块引用本页，不重新认领这些文件。返回 [项目结构](../项目结构文档.md)。

路径书写约定：以 `backend/` 或 `frontend/` 开头的为仓库根相对路径；其余后端路径省略 `backend/src/toolbox_backend/` 前缀，其余前端路径省略 `frontend/src/` 前缀。

## backend-api-shell：控制面装配与响应契约（全局上下文）

| 文件 | 全局作用 | 相关模块需要读取的范围 |
| --- | --- | --- |
| `backend/src/toolbox_backend/main.py` | 创建 FastAPI 应用，注册中间件、v1 路由、异常处理器与 lifespan | 应用对象 `app`；中间件顺序注释（CORS 在外、认证在内） |
| `backend/src/toolbox_backend/lifecycle.py` | 启动期所有权、目录初始化、凭据生成、过期清理、能力探测；关闭时停 USB 与投送会话 | `lifespan`、`request_shutdown(reason)` |
| `backend/src/toolbox_backend/api/router.py` | 聚合 v1 路由 | 无版本前缀 |
| `backend/src/toolbox_backend/api/v1/router.py` | 统一 `/api/v1` 前缀并登记全部模块路由 | 新增工具时必须在此 include |
| `backend/src/toolbox_backend/api/control_auth_middleware.py` | Bearer 凭据校验；豁免 `/api/v1/health`、`/docs`、`/openapi.json`、`/redoc` | `ControlAuthMiddleware`、`_EXEMPT_PATHS` |
| `backend/src/toolbox_backend/api/exception_handlers.py` | 业务异常与未知异常统一转 HTTP 200 + `{code,message,data}` | `register_exception_handlers` |
| `backend/src/toolbox_backend/schemas/response.py` | 统一响应壳 `ApiResponse`、`success`、`error` 与 `ErrorCode` 枚举 | 所有模块的返回与错误码 |
| `backend/src/toolbox_backend/core/errors.py` | `ServiceException(code, message)` | 模块内业务失败抛出点 |

新增工具路由的固定动作是：模块内 `APIRouter(prefix="/tools/<id>")` → `api/v1/router.py` include → `tool_catalog` 增加条目 → 前端 `router/tools.ts` 注册组件。控制面接口一律 POST，局域网数据面例外见 [局域网投送](lan-transfer.md)。

## backend-runtime-core：配置、所有权与凭据（共享）

| 文件 | 共同职责 | 已知消费者与用途 |
| --- | --- | --- |
| `backend/src/toolbox_backend/core/config.py` | `Settings`（pydantic-settings）与全部数据路径属性 | 几乎全部模块：`data_root`、`runtime_dir`、`lan_transfer_root`、`usb_transfer_root`、模型路径、LibreOffice 路径、各类限额 |
| `backend/src/toolbox_backend/core/runtime.py` | 应用级文件锁、`RuntimeIdentity`、运行阶段、worker 所有权传递、更新守卫 | `lifecycle.py`、`api/v1/health.py`、`api/v1/runtime.py`、`core/control_auth.py`、`usb_transfer/supervisor.py`、`usb_transfer/worker.py` |
| `backend/src/toolbox_backend/core/control_auth.py` | 每次启动生成控制面凭据并原子落盘，常量时间比对 | `lifecycle.py` 初始化、`control_auth_middleware.py` 校验、主进程 `electron/backend-runtime.ts` 读取 |
| `backend/src/toolbox_backend/core/logging.py` | `setup_logger` 统一格式；`ProgressLogHandler` 按关键词写任务进度 | 全部后端模块；后者供 PDF 深度解析类流程 |
| `backend/src/toolbox_backend/core/capabilities.py` | 线程安全的能力状态注册表 | `lifecycle.py` 写入、`tool_catalog` 与 `api/v1/settings.py` 读取 |
| `backend/src/toolbox_backend/schemas/runtime.py` | `RuntimeIdentity`、`RuntimeRequest`、`RuntimeStatus` | `core/runtime.py`、`api/v1/runtime.py`、主进程 `BackendRuntime` |

`Settings.ownership_lock_path` 固定在默认数据目录，不随 `TOOLBOX_DATA_DIR` 变化——同一用户下不允许因切换数据根而并行启动两个后端。

## backend-file-storage：文件与任务工作区（共享）

| 文件 | 共同职责 | 已知消费者与用途 |
| --- | --- | --- |
| `backend/src/toolbox_backend/infrastructure/files.py` | `safe_filename` 取 basename 并去控制字符；`save_file` 建目录后写盘 | pdf-to-markdown、markdown-to-word、quick-converters、id-photo、lan-transfer 的上传落盘 |
| `backend/src/toolbox_backend/infrastructure/task_storage/workspace.py` | `TEMP_DIR`/`UPLOADS_DIR`/`get_task_dir`/`validate_task_id`/`ensure_task_path` | 上述转换工具；`ensure_task_path` 用于阻断越出 `TEMP_DIR` 的路径 |
| `backend/src/toolbox_backend/infrastructure/task_storage/cleanup.py` | `cleanup_expired_temp(max_hours=24)` 清理超期目录，跳过 `uploads/`、`tasks/` 根下保留项 | `lifecycle.py` 启动期调用 |

任务 ID 统一为 12 位小写 hex；模块自行决定任务目录内的文件布局（如 `meta.txt`、状态 JSON、输出文件）。

## backend-integrations：外部进程隔离（共享）

| 文件 | 共同职责 | 已知消费者与用途 |
| --- | --- | --- |
| `backend/src/toolbox_backend/integrations/libreoffice.py` | `check_available` 探测、`convert_to_pdf`、`convert_to_doc`、进程树终止 | word-to-pdf、markdown-to-word（`.doc` 输出）、`lifecycle.py` 能力探测 |
| `backend/src/toolbox_backend/integrations/mineru.py` | 模型缓存目录、就绪判定、运行时环境变量、下载/转换可执行入口与命令构造 | pdf-to-markdown 深度引擎、settings-models 模型下载 |

两者都只在调用时构造子进程命令，不在模块导入时探测或加载外部资源。打包后通过 `backend/packaging/server.py` 的 `--toolbox-mineru*` 分支复用同一可执行文件。

## backend-reusable-packages：跨工具复用包（共享）

| 文件 | 共同职责 | 已知消费者与用途 |
| --- | --- | --- |
| `backend/src/toolbox_backend/modules/markdown_document/tables.py` | HTML 表格转管道表格 | pdf-to-markdown 深度结果后处理 |
| `backend/src/toolbox_backend/modules/markdown_document/metrics.py` | `count_tables` 统计表格数 | epub-to-markdown、pdf-to-markdown 的结果统计 |
| `backend/src/toolbox_backend/modules/markdown_document/docx.py` | Markdown → DOCX 渲染（`render_markdown_to_docx`、`MarkdownDocxRenderer`、math/SVG 解析规则） | 仅 markdown-to-word |
| `backend/src/toolbox_backend/modules/markdown_document/source.py` | 本地 `.md` / ZIP 资源包准备、Obsidian 库根图片查找、解包路径校验 | 仅 markdown-to-word |
| `backend/src/toolbox_backend/modules/markdown_document/graphics.py` | LaTeX 公式与 SVG 转 PNG（matplotlib / PyMuPDF 延迟导入） | 仅 markdown-to-word |
| `backend/src/toolbox_backend/modules/model_management/service.py` | MinerU 模型状态、下载任务、使用占用、受限删除 | settings-models（`api/v1/settings.py`）、pdf-to-markdown 深度引擎、`lifecycle.py`（删除时反向调用 `stop_mineru_executor`） |

`markdown_document` 中 `docx.py`、`source.py`、`graphics.py` 目前只有 markdown-to-word 一个消费者，保留在 [Markdown 转 Word](markdown-to-word.md) 归属；只有 `tables.py`、`metrics.py` 是真正的多消费者共享。`model_management` 与 pdf-to-markdown 存在双向引用（删除模型时延迟导入 `deep_service`），此处如实记录，不视为已解耦的公共抽象。

## backend-app-settings：投送偏好（共享）

| 文件 | 共同职责 | 已知消费者与用途 |
| --- | --- | --- |
| `backend/src/toolbox_backend/core/app_settings.py` | `<data_root>/settings.json` 的原子读写，只保存显式设置过的字段 | 仅 `modules/lan_transfer/service.py`：设备名、接收目录 |

## frontend-api-client：控制面 HTTP 客户端（共享）

| 文件 | 共同职责 | 已知消费者与用途 |
| --- | --- | --- |
| `frontend/src/api/client.ts` | 缓存控制面凭据、附带 `Authorization`、401 时丢弃缓存重试一次、解析统一响应壳 | `api/tools.ts`、`api/settings.ts`、`api/lanTransfer.ts`、`api/usbTransfer.ts`、`views/tools/ImageConverter.vue` |

凭据只存在于渲染进程内存；缺失时直接抛错，不退回无凭据请求。

## frontend-tools-api：多工具 HTTP 客户端（混合）

唯一归属文件：`frontend/src/api/tools.ts`。

| 模块 | 使用符号／字段／注册片段 | 用途与边界 |
| --- | --- | --- |
| [PDF 转 Markdown](pdf-to-markdown.md) | `convertPdf`、`getProgress`、`getPreview`、`downloadMd`、`ConvertResponse`、`GetProgressResponse`、`PreviewResponse` | 上传、轮询、预览、下载 |
| [单次转换工具](quick-converters.md) | `convertPdfToWord`、`downloadWord`、`convertWord`、`downloadPdf`、`convertEpub`、`getEpubPreview`、`downloadEpub`、`convertImages`、`downloadConvertedFile`、`downloadAllConverted`、`generateQrCode` 及对应 DTO | PDF↔Word、EPUB、图片、二维码 |
| [Markdown 转 Word](markdown-to-word.md) | `convertMarkdownToWord`、`convertLocalMarkdownToWord`、`downloadMarkdownToWord`、`MarkdownToWordConvertResponse`、`MarkdownToWordOutputFormat` | 上传与本地路径两条转换入口 |
| [证件照](id-photo.md) | `fetchIdPhotoTemplates`、`processIdPhoto`、`renderIdPhoto`、`fetchIdPhotoFile`、`downloadIdPhotoFile`、`IdPhoto*` 类型 | 模板、处理、重渲染、取文件 |
| [工具目录](tool-catalog.md) | `fetchToolList`、`ToolItem` | 拉取后端工具清单 |
| [局域网投送](lan-transfer.md) | 通过 `generateQrCode` 复用二维码能力生成访问入口二维码 | 仅此一处跨用 |

## frontend-settings-page：设置页（混合）

唯一归属文件：`frontend/src/views/settings/Settings.vue`。

| 模块 | 使用符号／字段／注册片段 | 用途与边界 |
| --- | --- | --- |
| [设置与模型管理](settings-models.md) | `model`、`idPhotoModel`、`loadStatus`、`scheduleStatusPoll`、`handleDownload`、`handleIdPhotoDownload`、`handleCancel*`、`handleDelete`、`formatBytes`、`copyPhotoModelPath` | 本地模型状态、下载/取消/删除 |
| [局域网投送](lan-transfer.md) | `lanPreferences`、`lanDeviceName`、`lanRecords`、`loadLanSettings`、`saveLanDeviceName`、`pickLanReceiveDir`、`resetLanReceiveDir`、`copyLanPath`、`fetchLanPreferences`/`fetchLanReceiveRecords`/`updateLanPreferences` | 投送设备名、接收目录、接收记录 |

两段各自持有独立 loading/error 状态，互不阻塞；`onMounted` 依次加载模型状态与投送设置。

## frontend-app-entry：渲染进程装配（全局上下文）

| 文件 | 全局作用 | 相关模块需要读取的范围 |
| --- | --- | --- |
| `frontend/src/main.ts` | 注册 FontAwesome 图标库、`style.css`、Pinia，先 `await createAppRouter()` 再挂载 | 工具图标在此集中注册；新增工具图标需同时加到这里 |
| `frontend/src/App.vue` | 仅渲染 `<router-view />` | 无业务逻辑 |
| `frontend/src/style.css` | Tailwind 引入与 `@theme` 颜色变量（primary/bg/surface/text/border 等） | 全站样式令牌来源 |
| `frontend/src/views/error/404.vue` | 路由未匹配兜底页，路由名 `NotFound` | 仅 `router/index.ts` 的 catch-all 引用 |

## frontend-desktop-contract：桌面能力类型声明（全局上下文）

| 文件 | 全局作用 | 相关模块需要读取的范围 |
| --- | --- | --- |
| `frontend/src/types/electron.d.ts` | 声明 `window.desktopApi` 全部通道 | 与 `electron/preload.ts` 暴露对象一一对应；各页面按需引用子对象 |
| `frontend/src/types/tool.ts` | `ToolConfig`、`ApiResponse<T>` | 路由与导航、所有 api 客户端 |

`electron/preload.ts` 是这两个类型的实现来源；主进程与 preload 共享的通道契约另有 `electron/update-types.ts`、`electron/markdown-to-pdf-types.ts`、`electron/markdown-source-types.ts`，均归 [桌面外壳](desktop-shell.md)。

## frontend-shared-ui：公共组件与公式引擎（共享）

| 文件 | 共同职责 | 已知消费者与用途 |
| --- | --- | --- |
| `frontend/src/components/common/BaseSelect.vue`、`frontend/src/components/common/index.ts`、`frontend/src/components/common/types.ts` | 受控下拉选择组件与 `SelectOption` | `views/tools/MindMap.vue`、`MarkdownToPdf.vue`、`IdPhoto.vue`、`UsbTransfer.vue`、`features/mindmap/components/MindMap.vue` |
| `frontend/src/utils/math/engine.ts` | 公式引擎初始化、有限缓存、`FormulaPaths` 纯 SVG 输出 | `features/markdown-pdf/render.worker.ts`、`features/mindmap/core/utils/formula.ts` |
| `frontend/src/utils/math/mathjax-renderer.ts` | 本地 MathJax 将公式渲染为不含外部资源的 SVG | 仅 `engine.ts` 内部使用 |
| `frontend/src/features/markdown/source.ts`、`frontend/src/features/markdown/components/MarkdownSourcePicker.vue` | Markdown 来源（上传 / 本地路径）选择器 | [Markdown 转 PDF](markdown-to-pdf.md)、[Markdown 转 Word](markdown-to-word.md) |
| `frontend/src/stores/layout.ts` | 侧边栏折叠状态 | `components/layout/AppShell.vue`、`AppSidebar.vue` |

公式引擎被两个独立特性共用，属于真实共享能力；`MarkdownSourcePicker` 只被两个 Markdown 工具页使用，但职责单一且不含转换参数。

## frontend-tests：Playwright 资产（共享）

| 文件 | 共同职责 | 已知消费者与用途 |
| --- | --- | --- |
| `frontend/playwright.config.ts` | 浏览器用例：自动拉起 Vite 与后端，`reuseExistingServer` | 除 `electron.spec.ts` 外的用例 |
| `frontend/playwright-electron.config.ts` | Electron 用例配置：不声明 `webServer`，避免与主进程争用端口与应用锁 | 仅 `frontend/tests/electron.spec.ts` |
| `frontend/tests/support/desktopApi.ts` | 从数据目录读取控制面凭据并注入页面，补齐浏览器环境缺失的 preload 能力 | 依赖后端接口的用例 |

用例按工具页面分布在 `frontend/tests/*.spec.ts`，与模块一一对应，不在各模块重复登记。

## build-and-packaging：构建与分发（全局上下文）

| 文件 | 全局作用 | 相关模块需要读取的范围 |
| --- | --- | --- |
| `package.json` | 根脚本与 electron-builder 配置；`main` 指向 `electron/main.js` | `files`、`extraResources`（`build/backend-runtime` → `Resources/backend`、`update-helper.js`）、`mac.sign`、`win.nsis` |
| `backend/packaging/backend.spec` | PyInstaller 收集规则 | 后端、MinerU/modelscope/mtcnnruntime、`resources/`（排除 `usb`）、局域网 `web/`、macOS USB 原生库 |
| `backend/packaging/server.py` | 打包后多入口分发 | `--toolbox-mineru`、`--toolbox-mineru-models`、`--toolbox-usb-worker`、`--toolbox-update-guard` 与默认 uvicorn 启动 |
| `backend/packaging/usb-native-sources.json`、`usb-notices.txt` | USB 原生依赖固定来源、摘要与分发说明 | 仅 `scripts/build-usb-native.js` 与打包产物 |
| `scripts/build-backend-runtime.js`、`build-usb-native.js`、`sign-macos.js` | 后端运行时构建、USB 原生库构建、macOS ad-hoc 签名 | 由 `npm run build:*` 与 electron-builder 调用 |
| `.github/workflows/desktop-release.yml` | tag 触发的双平台构建、校验和、Release 发布 | 构建顺序：frontend → electron → backend → electron-builder |
| `start-dev.command`、`start-dev.bat` | 开发启动脚本 | 先释放 18740/5173 端口，再调用 `npm run dev` |

`electron/*.js`、`frontend/dist/`、`build/`、`release/` 是产物，不作为源码登记。

## 共同数据与资源边界

| 数据／资源 | 定义与维护者 | 实际访问者 | 约束 |
| --- | --- | --- | --- |
| 用户数据根 | `core/config.py` 的 `Settings.data_root` | 主进程（解析并注入环境变量）、后端全部可写状态 | 由 `electron/main.ts` 单点解析；后端不自行推断 |
| 应用所有权锁 | `core/runtime.py` | 后端主进程、USB 工作子进程（描述符延续）、更新守卫 | 非阻塞；不因数据根变化而允许并行 |
| 控制面凭据 | `core/control_auth.py` | 主进程 `BackendRuntime.readToken`、`ControlAuthMiddleware` | 每次启动更换；文件权限受限；不进入局域网页面 |
| 任务临时目录 | `infrastructure/task_storage/workspace.py` | 各转换工具、启动清理 | 24 小时保留窗口，`ensure_task_path` 限定根目录 |
| 能力状态 | `core/capabilities.py` | `tool_catalog`、`api/v1/settings.py` | 内存态，启动探测 + 设置页操作后刷新 |

## 关系覆盖边界

- 消费者查找覆盖 `backend/src/toolbox_backend/`、`frontend/src/`、`electron/`、`scripts/`、`.github/`；未覆盖 `node_modules/`、`backend/.venv/` 与构建产物。
- `backend/packaging/server.py` 的多入口依赖打包后的 `sys.argv` 分派，源码态由 `integrations/mineru.py` 与 `usb_transfer/supervisor.py` 直接构造命令，两者路径不同。
- 局域网数据面的静态页面（`modules/lan_transfer/web/`）不参与前端构建，其与后端的接口契约只在 `web_app.py` 中可见。
