# 工具目录

模块标识：`tool-catalog`。返回 [项目结构](../项目结构文档.md)。

## 职责与入口

负责回答「当前有哪些工具、每个工具是否可用、不可用时为什么」，并把这份清单同时用于首页网格、侧边栏导航和工具路由生成。可用性由启动期探测的本地能力决定，不在前端硬编码。

不负责各工具的具体转换逻辑；不负责模型下载与删除（见 [设置与模型管理](settings-models.md)）。

入口：

- 后端 `POST /api/v1/tools/list`（`backend/src/toolbox_backend/modules/tool_catalog/router.py`）。
- 前端 `initToolConfigs()`（`frontend/src/router/tools.ts`），在 `createAppRouter()` 之前调用。

## 专属文件

| 文件 | 当前用途及纳入依据 |
| --- | --- |
| `backend/src/toolbox_backend/modules/tool_catalog/router.py` | 仅一个 `POST /list`，返回 `GetToolListResponse` |
| `backend/src/toolbox_backend/modules/tool_catalog/schemas.py` | `ToolListItem`、`GetToolListResponse` |
| `backend/src/toolbox_backend/modules/tool_catalog/service.py` | `_TOOLS` 静态清单 + `get_tool_list()` 追加并填充 `id-photo`、`markdown-to-pdf`、`word-to-pdf`、`usb-transfer` 的可用性 |
| `frontend/src/router/tools.ts` | `toolLocalRegistry`（id → 图标 + 动态 import）、`initToolConfigs`、`generateToolRoutes`、`toolConfigs` |
| `frontend/src/router/index.ts` | `createAppRouter` 先取工具清单再生成 `/tools/*` 子路由；`beforeEach` 拦截不可用工具 |
| `frontend/src/views/home/index.vue` | 首页工具卡片网格，显示 `displayName`/`description`，不可用工具置灰 |
| `frontend/src/components/layout/AppSidebar.vue` | 导航列表，`canNavigate` 按 `available !== false` 判定 |

## 公共与跨模块引用

路径书写：`backend/`、`frontend/`、`electron/` 开头的为仓库根相对路径；本节省略前缀的后端路径默认在 `backend/src/toolbox_backend/` 下，省略前缀的前端路径默认在 `frontend/src/` 下。

| 所属模块／公共记录 | 文件与使用范围 | 本模块为何引用 |
| --- | --- | --- |
| [公共记录](shared.md) `backend-runtime-core` | `core/capabilities.py` 的 `capabilities.get`、`CAPABILITY_ID_PHOTO`、`CAPABILITY_LIBREOFFICE`、`CAPABILITY_USB_TRANSFER` | 读取启动期探测结果填充 `available`/`unavailable_reason` |
| [公共记录](shared.md) `backend-api-shell` | `api/v1/router.py` 的 include 顺序 | 工具清单是 `/api/v1/tools/list` |
| [公共记录](shared.md) `frontend-tools-api` | `api/tools.ts` 的 `fetchToolList`、`ToolItem` | 唯一拉取通道 |
| [公共记录](shared.md) `frontend-desktop-contract` | `frontend/src/types/tool.ts` 的 `ToolConfig` | 合并后的前端配置类型 |
| [设置与模型管理](settings-models.md) | `api/v1/settings.py` 的 `_get_id_photo_status` | 模型状态变化后同步刷新 `CAPABILITY_ID_PHOTO`，间接改变本模块输出 |
| [局域网投送](lan-transfer.md)、[有线传输](usb-transfer.md)、[证件照](id-photo.md) | 各自路由页面 | `toolLocalRegistry` 中的 id 必须与后端条目一致 |

## 关键调用链

1. `frontend/src/main.ts` 调 `createAppRouter()`。
2. `createAppRouter` 先 `await initToolConfigs()`：`fetchToolList()` → `POST /api/v1/tools/list`（携带控制面凭据）。
3. 后端 `get_tool_list()` 复制 `_TOOLS`（8 个固定 `available=True` 条目），再追加 `id-photo`、`markdown-to-pdf`、`word-to-pdf`、`usb-transfer` 四个条目；其中 `markdown-to-pdf` 固定可用，其余三个从 `capabilities` 读取状态填充 `available`/`unavailable_reason`。
4. 前端按 `remote.id` 查 `toolLocalRegistry` 取图标与 `component`；未注册的 id 用拒绝加载的占位组件，图标回退为后端 `icon` 字符串拆分。
5. `generateToolRoutes` 生成 `/tools/<path>` 路由，`meta` 带 `id`/`title`/`icon`/`description`/`sidebarDefaultCollapsed`。
6. `router.beforeEach` 按 `meta.id` 在 `toolConfigs` 中查 `available === false`，命中则重定向 `/`。
7. `AppShell` 监听 `route.meta.sidebarDefaultCollapsed` 切换折叠状态；`AppSidebar` 与首页读取 `toolConfigs` 渲染。

`fetchToolList` 失败时 `initToolConfigs` 捕获并置空 `toolConfigs`，此时只有首页、设置与 404 可达。

## 状态与数据所有者

| 状态／资源 | 所有者 | 副本或消费者 | 生命周期／持久化 |
| --- | --- | --- | --- |
| 工具清单（后端） | `tool_catalog/service.py` 的 `_TOOLS`（8 条） | `get_tool_list()` 返回副本并追加 4 条 | 进程内常量，无持久化 |
| 可用性状态 | `core/capabilities.py` 的 `capabilities` | `tool_catalog`、`api/v1/settings.py` | 内存；启动探测写入，设置页操作后刷新 |
| 工具清单（前端） | `frontend/src/router/tools.ts` 的 `toolConfigs` | `AppSidebar`、首页、`router.beforeEach` | 内存，路由创建时初始化一次 |
| 组件映射 | `toolLocalRegistry` | `initToolConfigs` 合并 | 编译期常量，按需动态 import |

## 生命周期与约束

- 后端 `_TOOLS` 里 `available=True` 硬编码的条目（PDF 转 Markdown、PDF 转 Word、Markdown 转 Word、思维导图、图片格式转换、EPUB 转 Markdown、二维码、局域网投送）不参与能力探测；`markdown-to-pdf` 在追加时也固定为可用；仅 `id-photo`、`word-to-pdf`、`usb-transfer` 按能力动态判定。
- `usb-transfer` 只按平台判定：macOS 上即使运行依赖缺失也允许进入页面，由页面自行展示依赖状态。
- 新增工具必须同时改三处：后端 `_TOOLS`/`get_tool_list`、`api/v1/router.py` include、前端 `toolLocalRegistry`；只改其中一处会导致路由缺失或组件加载失败。

## 当前覆盖边界

- 工具清单是后端静态常量，未从模块注册表自动发现；`modules/` 下存在模块但未在 `_TOOLS` 出现时不会报错，也无静态校验。
