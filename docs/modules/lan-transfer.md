# 局域网投送

模块标识：`lan-transfer`。返回 [项目结构](../项目结构文档.md)。

## 职责与入口

负责在同一局域网内，用浏览器在电脑与手机/平板之间双向投送文件。它是全仓库唯一由两个独立运行单元组成的模块：桌面端控制面（`127.0.0.1:18740`，带凭据）负责会话生命周期、待确认队列、待取件清单与偏好；数据面（独立线程 + 独立端口，默认 `0.0.0.0:18751`）只服务浏览器页面与文件收发。

不负责二维码生成本身（借用 [单次转换工具](quick-converters.md) 的 `generateQrCode`），不负责应用级退出协调（见 [桌面外壳](desktop-shell.md)）。

入口：

- 控制面 `POST /api/v1/tools/lan-transfer/*`（`backend/src/toolbox_backend/modules/lan_transfer/router.py`）。
- 数据面浏览器路由 `GET /s/{token}`、`/unlock`、`/`、`/api/session`、`/api/files`、`/download/{file_id}`、`POST /upload`（`web_app.py`）。
- 前端 `frontend/src/views/tools/LanTransfer.vue`，路由 `/tools/lan-transfer`；设置页的投送偏好区块见 [公共记录](shared.md) 的 `frontend-settings-page`。

## 专属文件

| 文件 | 当前用途及纳入依据 |
| --- | --- |
| `backend/src/toolbox_backend/modules/lan_transfer/router.py` | 控制面 13 个 POST：会话启停、口令、待确认、待取件、偏好、接收记录、恢复信息 |
| `backend/src/toolbox_backend/modules/lan_transfer/service.py` | 控制面用例编排：`start_session`、`get_status`、`stop_session`、`set_passphrase`、`accept_pending`、`reject_pending`、`add_outgoing`、`remove_outgoing`、偏好读写、`recover_on_startup`、`shutdown_session`；关闭序列在此 |
| `backend/src/toolbox_backend/modules/lan_transfer/session.py` | `LanSession`、`SessionState`、`sessions` 单例、URL token/cookie 密钥、`InFlightRegistry` |
| `backend/src/toolbox_backend/modules/lan_transfer/server.py` | `LanWebServer`：绑定首选端口失败回退系统端口、独立线程运行 uvicorn、`should_exit` 关闭 |
| `backend/src/toolbox_backend/modules/lan_transfer/web_app.py` | 数据面 FastAPI 应用：cookie 授权、页面、上传、下载、口令校验；`register_exception_handlers` 复用控制面壳 |
| `backend/src/toolbox_backend/modules/lan_transfer/web/` | 浏览器静态页面：`index.html`、`unlock.html`、`app.js`、`style.css`；由 `StaticFiles` 挂载在 `/assets` |
| `backend/src/toolbox_backend/modules/lan_transfer/isolation.py` | 隔离区路径与文件名净化、遗留回收 |
| `backend/src/toolbox_backend/modules/lan_transfer/budget.py` | 会话预算：并发上传额度、字节预留、磁盘余量 |
| `backend/src/toolbox_backend/modules/lan_transfer/pending.py` | 待确认接收队列（已完整写入隔离区的内容） |
| `backend/src/toolbox_backend/modules/lan_transfer/outgoing.py` | 待取件清单：只登记用户选中的路径，不复制内容 |
| `backend/src/toolbox_backend/modules/lan_transfer/receive_log.py` | 已成功移入接收目录的条目记录 |
| `backend/src/toolbox_backend/modules/lan_transfer/addresses.py` | 枚举可用 IPv4 地址与推荐地址（psutil + UDP 出口探测） |
| `backend/src/toolbox_backend/modules/lan_transfer/schemas.py` | 控制面全部请求/响应契约 |
| `frontend/src/views/tools/LanTransfer.vue` | 开启/停止会话、访问地址与二维码、口令、待投送与待接收文件、接收记录 |
| `frontend/src/api/lanTransfer.ts` | 控制面 DTO 与调用函数 |

## 公共与跨模块引用

路径书写：`backend/`、`frontend/`、`electron/` 开头的为仓库根相对路径；本节省略前缀的后端路径默认在 `backend/src/toolbox_backend/` 下，省略前缀的前端路径默认在 `frontend/src/` 下。

| 所属模块／公共记录 | 文件与使用范围 | 本模块为何引用 |
| --- | --- | --- |
| [公共记录](shared.md) `backend-app-settings` | `core/app_settings.py` 的 `device_name`、`receive_dir`、`update`、`customized_fields` | 设备名与接收目录偏好 |
| [公共记录](shared.md) `backend-runtime-core` | `core/config.py` 的 `lan_transfer_root`、`lan_transfer_receive_dir` 与全部 `LAN_TRANSFER_*` 限额 | 目录与预算参数 |
| [公共记录](shared.md) `backend-file-storage` | `infrastructure/files.py` 的 `safe_filename` | 上传文件名净化 |
| [公共记录](shared.md) `backend-api-shell` | `api/exception_handlers.py` 的 `register_exception_handlers` | 数据面复用统一错误壳 |
| [公共记录](shared.md) `backend-runtime-core` | `lifecycle.py` 的 `recover_on_startup`、`shutdown_session` 调用点 | 启动回收与退出关闭 |
| [单次转换工具](quick-converters.md) | `api/tools.ts` 的 `generateQrCode` | 生成访问入口二维码 |
| [公共记录](shared.md) `frontend-tools-api` | `generateQrCode` | 同上 |
| [桌面外壳](desktop-shell.md) | `desktopApi.fileDialog.pickFiles`/`takeDroppedPaths` | 选择待投送文件与拖拽路径 |
| [设置与模型管理](settings-models.md) | `api/lanTransfer.ts` 的 `fetchLanPreferences`/`updateLanPreferences`/`fetchLanReceiveRecords` | 设置页投送区块 |

## 关键调用链

### 开启会话

1. `LanTransfer.vue` 调 `POST /session/start` → `service.start_session`。
2. 若已有 `STARTING`/`ACTIVE`/`CLOSING` 会话，直接返回当前快照。
3. `create_session(设备名, TTL, 最大顺延)` 生成会话（含 URL token、cookie 密钥）并 `sessions.install`。
4. `_server.start(host, preferred_port)`：先绑定首选端口，失败回退系统分配端口；随后在后台线程启动 `create_web_app()`。
5. 成功则 `state = ACTIVE`，`_watch_expiry` 启动到期观察；失败则 `state = FAILED`、`sessions.clear()` 并抛出。
6. 前端展示 `addresses`（含 `is_recommended`）与二维码。

### 接收（浏览器 → 电脑）

1. 浏览器打开 `/s/{token}`：`matches_url_token` 校验；设置了口令则 303 到 `/unlock`，否则下发 cookie 到 `/`。
2. `POST /upload`：`_resolve_session` 校验 cookie → `isolation.sanitize_name` 净化文件名 → `budget.acquire_upload_slot()` → `in_flight.register(cancelled.set)` → 预留字节 → 流式写入隔离区。
3. 写完后上传占用转为待确认占用，条目进入 `pending` 队列；请求结束不释放预算。
4. 桌面端 `POST /pending/list` 查看，`POST /pending/accept` 由 `service.accept_pending` 把文件移入接收目录并写 `receive_log`；`reject` 删除隔离区内容。
5. 关闭会话时未确认内容由 `_cleanup_pending` 清理，已接收文件不受影响。

### 发送（电脑 → 浏览器）

1. `POST /send/add` → `service.add_outgoing` 只登记路径与元信息，不复制文件。
2. 浏览器 `/api/files` 读取清单，`/download/{file_id}` 由 `_iter_download` 流式返回。
3. 源文件被移动或删除时按 404 处理，不伪造内容。

### 关闭

1. `stop_session(message)` 在 `_close_lock` 内按固定序列执行：`state = CLOSING` → `in_flight.cancel_all()` → `_server.stop()` → `_wait_for_uploads` → `_cleanup_pending` → `outgoing.clear()` → `state = CLOSED` → `sessions.clear()`。
2. 返回带 `cleanup_failures` 的快照，如实报告未能删除的隔离区条目。
3. 应用退出路径由 `lifecycle.request_shutdown` → `shutdown_session()` 触发，异常只记录类型不阻塞退出。

## 状态与数据所有者

| 状态／资源 | 所有者 | 副本或消费者 | 生命周期／持久化 |
| --- | --- | --- | --- |
| 当前会话 | `modules/lan_transfer/session.py` 的 `sessions` | `service.py`、`web_app.py` | 内存；应用重启不恢复，凭据不复用 |
| 会话预算 | `budget.py` 的 `SessionBudget` | 上传与待确认队列 | 会话内，随会话释放 |
| 待确认队列 | `pending.py` 的 `PendingQueue` | 控制面 `pending/*`、数据面 `/upload` | 会话内内存 + 隔离区文件 |
| 待取件清单 | `outgoing.py` 的 `OutgoingList` | 数据面 `/api/files`、`/download` | 会话内内存，只存路径 |
| 接收记录 | `receive_log.py` | 控制面 `/records/list`、设置页 | 持久化在数据目录，保留最近 `LAN_TRANSFER_MAX_RECEIVE_RECORDS` 条 |
| 隔离区 | `isolation.py` 的 `lan_transfer_root` | 上传与清理流程 | `<data_root>/lan_transfer`，会话关闭时清理未确认内容 |
| 接收目录 | `core/config.py` 的 `lan_transfer_receive_dir` | `accept_pending` 写入 | 默认用户下载目录下的 `工具盒子` 子目录，可由偏好覆盖 |
| 偏好 | `core/app_settings.py` | `service._device_name`、`_receive_dir` | `<data_root>/settings.json` |

## 生命周期与约束

- 会话只存在于内存：应用重启后不恢复旧会话，也不复用旧 URL token 或 cookie 密钥。
- 数据面与控制面分离监听：控制面只绑 `127.0.0.1`，数据面绑 `0.0.0.0` 且仅在会话期间存在。
- 数据面接口使用 GET/POST 是浏览器导航、表单提交、上传下载的必需形式，不适用控制面「全部 POST」约定；这是代码注释中明确写出的例外。
- 会话有效期 `LAN_TRANSFER_TTL_SECONDS` 到期时：无在途传输则自动关闭，有在途则顺延，但不超过 `LAN_TRANSFER_MAX_EXTEND_SECONDS`。
- 接收方向预算由上传中与待确认内容共同占用；发送方向只约束清单条数，不占字节预算。
- 口令变更会轮换 cookie 密钥，已进入的浏览器需要重新验证。
- 控制面凭据不进入局域网链接、二维码或浏览器页面。

## 当前覆盖边界

- 浏览器页面（`web/`）是独立静态前端，不参与 `frontend/` 的构建与类型检查；其接口契约只在 `web_app.py` 与 `app.js` 中体现。
- 地址枚举依赖 psutil 与 UDP 出口探测，多网卡或虚拟网卡环境下的推荐地址由实现规则决定。
