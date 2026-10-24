# 证件照

模块标识：`id-photo`。返回 [项目结构](../项目结构文档.md)。

## 职责与入口

负责单张人像照片的本地证件照生成：人脸检测、人像抠图、按规格裁切、换背景、可选的六寸排版，以及基于已抠图结果的参数化重渲染与结果下载。模型推理全部在本机完成，不上传任何图像到外部服务。

不负责模型下载与删除（见 [设置与模型管理](settings-models.md)），但本模块提供模型可用性判定与使用占用计数。

入口：`POST /api/v1/tools/id-photo/{templates,process,render,download}`（`backend/src/toolbox_backend/modules/id_photo/router.py`）；前端 `frontend/src/views/tools/IdPhoto.vue`，路由 `/tools/id-photo`。

## 专属文件

| 文件 | 当前用途及纳入依据 |
| --- | --- |
| `backend/src/toolbox_backend/modules/id_photo/router.py` | 四个 POST 接口；`process` 收 multipart 与渲染参数，`render` 收 JSON，`download` 按 `file_index` 返回 JPEG |
| `backend/src/toolbox_backend/modules/id_photo/service.py` | `process_id_photo`、`render_id_photo`、`download_file`、`SUPPORTED_EXTENSIONS`、`MAX_FILE_SIZE`（20MB） |
| `backend/src/toolbox_backend/modules/id_photo/inference.py` | `_get_matting_session`、`_get_mtcnn`、`_load_image`、`_limit_processing_size`、`_detect_face`、`_matting`、`reset_model_sessions`；延迟加载 ONNX 会话 |
| `backend/src/toolbox_backend/modules/id_photo/rendering.py` | `_render_task`、`_find_head_top`、`_crop_with_padding`、`_resize_rgba_on_background`、`_generate_layout`、`_save_jpeg` |
| `backend/src/toolbox_backend/modules/id_photo/templates.py` | `TEMPLATES`（一寸/小二寸/二寸）、`BACKGROUND_PRESETS`、`list_templates`、`_resolve_template`、`_resolve_background`、`_validate_render_settings`、`_calculate_crop`；`MAX_OUTPUT_DIMENSION`/`MAX_OUTPUT_PIXEL_COUNT`/`STANDARD_QUALITY` |
| `backend/src/toolbox_backend/modules/id_photo/task_metadata.py` | `_task_dir_checked`、`_read_metadata`、`_face_from_metadata`、`_write_json` |
| `backend/src/toolbox_backend/modules/id_photo/model_resources.py` | `_model_directory`、`_find_matte_model`、`_mtcnn_weight_paths`；只定位资源，不管理状态 |
| `backend/src/toolbox_backend/modules/id_photo/model_management.py` | `get_model_status`、`get_model_management_status`、`start_id_photo_download`、`cancel_id_photo_download`、`delete_id_photo_model`、`_guard_model_use`、`_ACTIVE_MODEL_USES`；同时被设置页与启动探测调用 |
| `backend/src/toolbox_backend/modules/id_photo/schemas.py` | `IdPhotoTemplate`、`IdPhotoTemplateItem`、`IdPhotoFileItem`、`IdPhotoResponse`、`IdPhotoRenderRequest`、`IdPhotoDownloadRequest` |
| `backend/src/toolbox_backend/modules/id_photo/types.py` | `TemplateConfig`、`FaceDetection` |
| `frontend/src/views/tools/IdPhoto.vue` | 上传、原图/成片对照、规格切换、微调（`crop_scale`/`offset_x`/`offset_y`）、质量与 DPI、下载 |

`backend/scripts/download_id_photo_models.py` 是准备随包模型资源的脚本，产物写入 `backend/resources/id_photo/`（被 `.gitignore` 排除）。

## 公共与跨模块引用

路径书写：`backend/`、`frontend/`、`electron/` 开头的为仓库根相对路径；本节省略前缀的后端路径默认在 `backend/src/toolbox_backend/` 下，省略前缀的前端路径默认在 `frontend/src/` 下。

| 所属模块／公共记录 | 文件与使用范围 | 本模块为何引用 |
| --- | --- | --- |
| [公共记录](shared.md) `backend-file-storage` | `infrastructure/files.py` 的 `safe_filename`；`task_storage/workspace.py` 的 `get_task_dir` | 文件名净化与任务目录 |
| [公共记录](shared.md) `backend-runtime-core` | `core/config.py` 的 `id_photo_model_path`、`core/capabilities.py` 的 `CAPABILITY_ID_PHOTO` | 模型目录与可用性状态 |
| [公共记录](shared.md) `backend-reusable-packages` | 无直接引用；`model_management.py` 位于本模块但被设置页复用 | 见下方说明 |
| [设置与模型管理](settings-models.md) | `api/v1/settings.py` 调用 `get_model_management_status`、`start_id_photo_download`、`cancel_id_photo_download`、`delete_id_photo_model` | 设置页的证件照模型操作 |
| [公共记录](shared.md) `frontend-tools-api` | `fetchIdPhotoTemplates`、`processIdPhoto`、`renderIdPhoto`、`fetchIdPhotoFile`、`downloadIdPhotoFile` 及 DTO | 前端唯一 HTTP 通道 |
| [工具目录](tool-catalog.md) | `get_tool_list()` 中 `id-photo` 条目的 `available`/`unavailable_reason` | 入口可用性 |
| [公共记录](shared.md) `backend-api-shell` | `lifecycle.py` 调用 `get_model_status()` 写入能力状态 | 启动期探测 |

`model_management.py` 物理上属于本模块，但职责是「模型资源状态与下载」，被设置页与启动探测共同使用；这是真实的混合归属，已在 [公共记录](shared.md) 中标注。

## 关键调用链

### 首次处理

1. `IdPhoto.vue` 选择照片 → `processIdPhoto(file, params)` → `POST /process`（multipart）。
2. `process_id_photo` 由 `_guard_model_use` 包裹：先 `get_model_status()`，不可用直接 `SERVICE_UNAVAILABLE`。
3. `_resolve_template` 校验规格（预设或自定义宽高）→ `_validate_render_settings` 校验质量/DPI/文件大小上限 → 扩展名与 20MB 校验。
4. `_limit_processing_size` 限制处理分辨率 → `_load_image` → `_detect_face`（MTCNN）→ `_matting`（MODNet ONNX）得到前景与模型名。
5. 建任务目录：写 `matting.png`（临时文件 + `os.replace` 原子落盘）与 `metadata.json`（人脸框、landmarks、源尺寸、模型名、原始文件名）。
6. `_render_task` 按模板裁切、换底、可选六寸排版，`_save_jpeg` 按质量与大小上限输出，文件名以 `<index>_` 前缀区分类型。
7. 返回 `IdPhotoResponse`（含 `files` 列表，每项带 `index`）；任一步失败都删除任务目录。

### 重新渲染

1. 用户调整规格/裁切/背景 → `renderIdPhoto(params)` → `POST /render`。
2. `render_id_photo` 只复用任务目录中已有的 `matting.png` 与 `metadata.json`，不重新推理；`_task_dir_checked` 校验任务 ID。
3. `_render_task` 以新的 `crop_scale`/`offset_*`/背景/质量参数重写结果文件。

### 下载

`downloadIdPhotoFile(taskId, fileIndex)` → `POST /download` → `download_file` 按 `<file_index>_*.jpg` 匹配返回 `FileResponse`。

## 状态与数据所有者

| 状态／资源 | 所有者 | 副本或消费者 | 生命周期／持久化 |
| --- | --- | --- | --- |
| 模型会话 | `inference.py` 的模块级会话缓存 | `_detect_face`、`_matting` | 进程内；`reset_model_sessions` 可释放 |
| 模型文件 | `model_resources.py` 定位 | `inference.py`、`model_management.py` | 随包 `resources/id_photo`（只读）或 `<data_root>/resources/id_photo` |
| 模型使用占用 | `model_management.py` 的 `_ACTIVE_MODEL_USES` + `_MODEL_USE_CONDITION` | `_guard_model_use`、删除流程 | 内存；占用期间禁止删除 |
| 任务目录 | `backend/src/toolbox_backend/modules/id_photo/service.py` | `render_id_photo`、`download_file`、启动清理 | `<data_root>/temp/tasks/<task_id>`，含 `matting.png`、`metadata.json`、结果 JPEG |
| 前端结果状态 | `IdPhoto.vue` 的 ref | 页面渲染 | 内存 |

## 生命周期与约束

- 抠图与检测模型首次使用时才加载，避免启动即占用大量内存。
- `process` 与 `render` 的差异是前者做推理、后者只重排；因此重渲染必须使用仍存在的任务目录，过期清理后不可重渲染。
- 输出尺寸受 `MAX_OUTPUT_DIMENSION`（3000px）与 `MAX_OUTPUT_PIXEL_COUNT`（900 万）约束。
- 背景预设以 OpenCV BGR 存储，接口与界面使用可读名称（`white`/`blue`/`red`）。
- 模型不可用时工具目录把 `id-photo` 标为不可用，路由守卫会阻止直接进入。

## 当前覆盖边界

- 推理精度与人脸检测边界由 `hivision_modnet.onnx` 与 MTCNN 权重决定，本仓库只负责调用。
- 随包模型资源未纳入版本控制，缺失时依赖 `backend/scripts/download_id_photo_models.py` 或设置页下载；两种来源的优先级由 `core/config.py` 的 `id_photo_model_path` 决定。
- `backend/packaging/backend.spec` 从磁盘收集 `backend/resources/`（排除 `usb`），而 `.github/workflows/desktop-release.yml` 没有准备模型文件的步骤，因此发布产物是否带证件照模型取决于构建机本地状态；缺失时工具目录会把 `id-photo` 标为不可用，需用户自行在设置页下载。
