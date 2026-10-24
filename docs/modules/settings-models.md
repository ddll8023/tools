# 设置与模型管理

模块标识：`settings-models`。返回 [项目结构](../项目结构文档.md)。

## 职责与入口

负责设置页上的两类能力：本地模型资源（MinerU 深度解析模型、证件照模型）的状态查询、下载、取消与删除；以及局域网投送偏好与接收记录在设置页中的展示入口。

模型资源只在用户数据目录内管理，删除前必须无下载任务、无使用占用；随应用包分发的只读模型不允许通过本模块删除。

不负责模型的实际推理使用（见 [PDF 转 Markdown](pdf-to-markdown.md)、[证件照](id-photo.md)），也不负责投送会话本身（见 [局域网投送](lan-transfer.md)）。

入口：`POST /api/v1/settings/models/{status,download,progress,cancel,delete}`（`backend/src/toolbox_backend/api/v1/settings.py`）；前端 `frontend/src/views/settings/Settings.vue`，路由 `/settings`。

## 专属文件

| 文件 | 当前用途及纳入依据 |
| --- | --- |
| `backend/src/toolbox_backend/api/v1/settings.py` | 五个 POST 接口；`_get_model_status`/`_action_model` 按 `model_id` 分派到 MinerU 或证件照；证件照状态查询同时刷新 `CAPABILITY_ID_PHOTO` |
| `backend/src/toolbox_backend/schemas/settings.py` | `ModelId`、`ModelStatus`、`ModelRequest`、`ModelStatusItem`、`ModelStatusResponse`、`ModelActionResponse` |
| `backend/src/toolbox_backend/modules/model_management/service.py` | MinerU 模型：`get_mineru_model_status`、`start_mineru_download`、`cancel_mineru_download`、`delete_mineru_model`、`require_mineru_model`、`acquire_mineru_model_use`/`release_mineru_model_use`、下载子进程与 `.download-state.json` |
| `frontend/src/api/settings.ts` | `MINERU_PIPELINE_MODEL_ID`/`ID_PHOTO_MODEL_ID`、`ModelStatus`、`ModelStatusItem`、`fetchModelStatus`、`startModelDownload`、`cancelModelDownload`、`deleteModel` |

证件照模型管理的实现文件 `backend/src/toolbox_backend/modules/id_photo/model_management.py`、`model_resources.py` 归 [证件照](id-photo.md)，本模块只通过 `api/v1/settings.py` 调用其公开函数。设置页文件归 [公共记录](shared.md) 的 `frontend-settings-page` 混合记录。

## 公共与跨模块引用

路径书写：`backend/`、`frontend/`、`electron/` 开头的为仓库根相对路径；本节省略前缀的后端路径默认在 `backend/src/toolbox_backend/` 下，省略前缀的前端路径默认在 `frontend/src/` 下。

| 所属模块／公共记录 | 文件与使用范围 | 本模块为何引用 |
| --- | --- | --- |
| [公共记录](shared.md) `backend-runtime-core` | `core/config.py` 的 `mineru_model_path`、`id_photo_model_path`；`core/capabilities.py` 的 `CAPABILITY_ID_PHOTO` | 决定模型目录与可用性状态 |
| [公共记录](shared.md) `backend-integrations` | `integrations/mineru.py` 的 `build_download_command`、`get_runtime_env`、`get_model_cache_dir` | 构造下载子进程命令与缓存环境 |
| [公共记录](shared.md) `frontend-api-client` | `api/client.ts` 的 `apiFetch`、`readApiResponse` | 统一凭据与响应壳解析 |
| [证件照](id-photo.md) | `id_photo/model_management.py` 的 `get_model_management_status`、`start_id_photo_download`、`cancel_id_photo_download`、`delete_id_photo_model` | 证件照模型的四类操作 |
| [PDF 转 Markdown](pdf-to-markdown.md) | `pdf_to_markdown/deep_service.py` 的 `stop_mineru_executor` | 删除 MinerU 模型前停止执行器（延迟导入） |
| [局域网投送](lan-transfer.md) | `api/lanTransfer.ts` 的 `fetchLanPreferences`、`fetchLanReceiveRecords`、`updateLanPreferences` | 设置页的投送偏好区块 |

## 关键调用链

### 模型状态与下载

1. `Settings.vue` 的 `loadStatus` → `fetchModelStatus()` → `POST /settings/models/status`。
2. 后端 `get_models_status()` 返回 `[get_mineru_model_status(), _get_id_photo_status()]`；后者在读取时顺带 `capabilities.set(CAPABILITY_ID_PHOTO, ...)`。
3. 用户点击下载 → `startModelDownload(model_id)` → `POST /settings/models/download` → `_action_model`。
4. MinerU 分支 `start_mineru_download()` 复用已有任务，启动 `subprocess.Popen` 执行 `build_download_command()`，逐行读 stdout 更新进度并写 `.download-state.json`。
5. 证件照分支 `start_id_photo_download()` 下载 matting 模型并复制 MTCNN 权重到受管目录。
6. 前端 `scheduleStatusPoll` 在状态为 `downloading` 时轮询 `POST /settings/models/progress`。

### 删除

1. `handleDelete(item)` → `deleteModel(model_id)` → `POST /settings/models/delete`。
2. MinerU：`delete_mineru_model()` 校验无下载任务、无使用占用、目录位于受管用户数据目录；满足条件时延迟导入 `stop_mineru_executor()` 停止执行器后 `shutil.rmtree`。
3. 证件照：`delete_id_photo_model()` 校验下载中/使用中/删除中状态后删除受管目录。
4. 随包只读模型不满足「位于受管用户数据目录」条件，接口返回不可删除原因，由页面展示 `delete_reason`。

## 状态与数据所有者

| 状态／资源 | 所有者 | 副本或消费者 | 生命周期／持久化 |
| --- | --- | --- | --- |
| MinerU 下载任务 | `model_management/service.py` 的 `_ACTIVE_JOB`/`_LAST_JOB` 与 `_MODEL_USE_CONDITION` | `api/v1/settings.py`、`pdf_to_markdown/deep_service.py`（占用计数） | 内存 + `.download-state.json` 记录最近状态 |
| MinerU 模型文件 | `model_management/service.py` 的 `_model_cache_dir` | `integrations/mineru.py` 的 `is_model_ready`、MinerU CLI | `<data_root>/resources/mineru` |
| 证件照下载任务 | `id_photo/model_management.py` 的 `_ACTIVE_DOWNLOAD`/`_LAST_DOWNLOAD`、`_ACTIVE_MODEL_USES` | 同上接口、`id_photo/service.py` 的 `_guard_model_use` | 内存；模型文件落在受管目录 |
| 模型可用性 | `core/capabilities.py` 的 `CAPABILITY_ID_PHOTO` | `tool_catalog`、`api/v1/settings.py` | 内存，本模块在状态查询后刷新 |
| 前端模型状态 | `Settings.vue` 的 `model`/`idPhotoModel` | 页面渲染 | 内存，轮询刷新 |

## 生命周期与约束

- 两个模型管理系统各自维护独立的下载锁与使用占用计数，互不影响；共用 `ModelStatusItem` 契约，因此字段必须保持兼容。
- MinerU 下载子进程在打包态经 `--toolbox-mineru-models` 复用同一可执行文件；源码态用 `mineru-models-download` 入口。
- 删除操作只在模型目录属于受管用户数据目录时允许；随包资源路径直接返回不可删除。
- 状态枚举 `not_downloaded | downloading | ready | failed | interrupted | cancelled | incomplete | unavailable` 是两套实现共同遵守的取值。

## 当前覆盖边界

- `delete_mineru_model` 与 `pdf_to_markdown/deep_service.py` 存在反向延迟导入，删除路径的实际副作用取决于该执行器是否已启动；本文只登记调用关系。
- 模型下载依赖外部模型源（modelscope / HuggingFace 兼容布局），其可用性不由本仓库控制。
