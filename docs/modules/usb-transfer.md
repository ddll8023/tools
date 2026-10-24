# 有线传输

模块标识：`usb-transfer`。返回 [项目结构](../项目结构文档.md)。

## 职责与入口

负责通过数据线连接 MTP 设备（仅 macOS 支持），浏览设备目录并在本机与设备之间双向复制文件与文件夹。设计上把「控制面」「后台执行」「原生设备访问」拆成三段：API 进程不加载 libmtp，所有设备读写都在独立工作子进程中完成。

不负责设备清理、覆盖或删除设备文件的策略；不负责应用退出协调（见 [桌面外壳](desktop-shell.md)），但提供停止确认状态供其判断。

入口：`POST /api/v1/tools/usb-transfer/*`（`backend/src/toolbox_backend/modules/usb_transfer/router.py`）；前端 `frontend/src/views/tools/UsbTransfer.vue` + `usb-transfer/` 子目录，路由 `/tools/usb-transfer`。

## 专属文件

### 控制面

| 文件 | 当前用途及纳入依据 |
| --- | --- |
| `backend/src/toolbox_backend/modules/usb_transfer/router.py` | 11 个 POST：`status`、`devices/scan`、`session/open|close`、`directory/list`、`tasks/prepare|submit|list|entries|cancel|remove` |
| `backend/src/toolbox_backend/modules/usb_transfer/service.py` | 控制面编排：`probe_platform`、`initialize`、`scan_devices`、`open_session`、`list_directory`、`prepare_copy`、`submit_copy`、`cancel_task`、`shutdown`、`stop_state`；持有 `_operation_lock` 与 `_state_lock` |
| `backend/src/toolbox_backend/modules/usb_transfer/session.py` | `UsbSession`、对象归属与目录链、`ROOT_FOLDER_ID` |
| `backend/src/toolbox_backend/modules/usb_transfer/schemas.py` | 控制面、任务记录与进程边界的数据契约（`UsbStatus`、`UsbTaskSummary`、`PlanEntry`、`TransferStart`、`TERMINAL_STATES` 等） |

### 任务与记录

| 文件 | 当前用途及纳入依据 |
| --- | --- |
| `backend/src/toolbox_backend/modules/usb_transfer/tasks.py` | `TaskManager`、`TaskRuntime`、单会话 FIFO、实例绑定的有限期幂等提交（`submission_token`）、记录错误聚合 |
| `backend/src/toolbox_backend/modules/usb_transfer/executor.py` | `Executor`：先枚举（`event` 校验条目身份与预算）再逐项复制，写前记录，终态保留真实停止原因 |
| `backend/src/toolbox_backend/modules/usb_transfer/records.py` | `RecordStore`：写前意图、原子摘要、同步条目日志；`count_result` 统计 |

### 工作进程与原生访问

| 文件 | 当前用途及纳入依据 |
| --- | --- |
| `backend/src/toolbox_backend/modules/usb_transfer/supervisor.py` | `UsbWorkerSupervisor`：启动/监管单个 worker、协议代次关联、独立发送取消、`shutdown` |
| `backend/src/toolbox_backend/modules/usb_transfer/worker.py` | 子进程入口 `main()`：单线程执行原生调用，独立读取取消与父通道关闭；`adopt_worker_ownership` 延续应用锁 |
| `backend/src/toolbox_backend/modules/usb_transfer/protocol.py` | 私有 JSON 行协议：严格消息关联、有限帧长，不承载文件内容 |
| `backend/src/toolbox_backend/modules/usb_transfer/mtp.py` | libmtp v1.1.23 公共 ABI 绑定，仅工作进程使用 |
| `backend/src/toolbox_backend/modules/usb_transfer/transfer.py` | 工作进程内的选区枚举与逐项复制 |
| `backend/src/toolbox_backend/modules/usb_transfer/local_files.py` | 本机侧文件操作：目录 FD 锚定、禁止链接、macOS 排他发布 |

### 前端

| 文件 | 当前用途及纳入依据 |
| --- | --- |
| `frontend/src/views/tools/UsbTransfer.vue` | 页面骨架：设备选择、目录浏览、选区、上传/下载确认、任务区 |
| `frontend/src/views/tools/usb-transfer/useUsbTransfer.ts` | 页面状态：单飞轮询、会话代次、复制草稿、任务结果 |
| `frontend/src/views/tools/usb-transfer/UsbTransferTasks.vue` | 任务与分页结果区，不依赖设备是否仍连接 |
| `frontend/src/api/usbTransfer.ts` | 控制面 DTO 与调用函数、`formatUsbSize`、`usbTaskActive` |

## 公共与跨模块引用

路径书写：`backend/`、`frontend/`、`electron/` 开头的为仓库根相对路径；本节省略前缀的后端路径默认在 `backend/src/toolbox_backend/` 下，省略前缀的前端路径默认在 `frontend/src/` 下。

| 所属模块／公共记录 | 文件与使用范围 | 本模块为何引用 |
| --- | --- | --- |
| [公共记录](shared.md) `backend-runtime-core` | `core/runtime.py` 的 `worker_ownership_fd`、`adopt_worker_ownership`；`core/config.py` 的 `usb_transfer_root`、`usb_transfer_library_path` 与 `USB_TRANSFER_*` 限额 | 所有权延续、状态目录、原生库定位与预算 |
| [公共记录](shared.md) `backend-api-shell` | `lifecycle.py` 的 `usb_transfer_service.initialize()`、`probe_platform()`、`shutdown()` 调用点；`api/v1/runtime.py` 的 `stop_state()` | 启动初始化与停止确认上报 |
| [公共记录](shared.md) `build-and-packaging` | `backend/packaging/backend.spec` 的 USB 原生库收集、`server.py --toolbox-usb-worker`、`scripts/build-usb-native.js` | 打包与分发 |
| [工具目录](tool-catalog.md) | `get_tool_list()` 中 `usb-transfer` 条目按平台判定可用性 | 入口可用性 |
| [公共记录](shared.md) `frontend-tools-api` | 无；本模块使用独立的 `api/usbTransfer.ts` | — |
| [桌面外壳](desktop-shell.md) | `desktopApi.fileDialog.pickFiles`/`pickDirectory` | 选择本机上传来源与下载目标 |

## 关键调用链

### 会话与浏览

1. `useUsbTransfer` 轮询 `POST /status` → `service.get_status` 返回 `instance_id`、会话、设备与停止状态。
2. `devices/scan` → `service.scan_devices` → `_call(Operation...)` → `supervisor` 向 worker 发请求 → `mtp` 枚举设备。
3. `session/open` 打开设备会话并记录存储列表；`directory/list` 按对象 ID 列目录，返回分页条目。
4. 会话对象归属由 `session.py` 记录；旧会话引用不用于重连恢复。

### 复制任务

1. `tasks/prepare` → `service.prepare_copy`：规范化并去重来源集合、检查设备归属消息大小预算 → `_manager.prepare` 生成草稿。
2. `tasks/submit` → `service.submit_copy`：先 `_require_instance`，再用 `submission_token` 查是否已提交（幂等）→ `_manager.submit` 入单会话 FIFO。
3. `Executor.execute`：`event` 逐条校验枚举结果（条目数上限、父项必须已出现、身份不可改写）→ 每项写前记录（`records.RecordStore`）→ 通过 `supervisor` 下发到 worker → `worker` 调用 `mtp`（设备侧）与 `local_files`（本机侧）→ 进度回传。
4. 终态写回记录；`tasks/list`、`tasks/entries` 读取内存任务与记录；`cancel` 置取消标志并单独发送取消控制。

### 停止

1. `service.shutdown()`：`_stopping = True` → 中断当前会话队列（`invalidate_session`）→ `_manager.shutdown(deadline)` 等任务确认 → `_acquire_exit_barrier` 等 `_operation_lock` 真正释放 → `_supervisor.shutdown(deadline)` 关工作进程 → `_drop_session`。
2. 三项都确认为真才算 `stopped`，否则 `forced = True`，由 `stop_state()` 上报给 `api/v1/runtime.py` 与主进程。
3. 写前记录是结果不确定时的唯一兜底：崩溃或强杀后不把未确认的条目当作成功。

## 状态与数据所有者

| 状态／资源 | 所有者 | 副本或消费者 | 生命周期／持久化 |
| --- | --- | --- | --- |
| 任务权威状态 | `tasks.py` 的 `TaskManager` | 控制面 `tasks/*`、`stop_state` | 内存；终态摘要与条目日志落盘 |
| 任务记录 | `records.py` 的 `RecordStore` | `TaskManager`、`executor` | `<data_root>/usb_transfer`，写前意图 + 原子摘要 + 条目日志 |
| 设备会话 | `modules/usb_transfer/session.py` 的 `UsbSession` | `service.py`、`executor` | 内存，会话关闭即失效 |
| 工作进程 | `modules/usb_transfer/supervisor.py` 的 `UsbWorkerSupervisor` | `service.py`、`executor` | 子进程；按协议代次严格关联 |
| 应用所有权 | `core/runtime.py` | worker 通过描述符延续持有 | 进程存活期间阻止第二个实例 |
| 前端任务视图 | `useUsbTransfer.ts` | 页面渲染 | 内存，单飞轮询刷新 |

## 生命周期与约束

- 仅 macOS 支持：`probe_platform` 直接返回平台判定，其他平台不访问 USB 状态目录。
- API 进程不 `dlopen` libmtp；库路径由 `settings.usb_transfer_library_path` 解析（显式配置 → 随包资源 → 仅源码态的常见位置），打包产物缺库时明确失败。
- 控制面全部 POST；文件内容不经过 HTTP，只在设备与本机之间由 worker 搬运。
- 单会话 FIFO：同一设备的复制任务串行，避免并发写入设备。
- `submission_token` 提供有限期幂等：重复提交返回既有任务，`USB_TRANSFER_SUBMISSION_TTL` 控制有效期。
- 私有协议严格消息关联与有限帧长，不承载文件内容；worker 独立读取取消信号与父通道关闭。
- 本机侧使用目录 FD 锚定与禁止链接，macOS 上以排他方式发布文件；这是防误操作机制，不是权限沙箱。

## 当前覆盖边界

- `mtp.py` 绑定 libmtp v1.1.23 的公共 ABI，设备行为由该库与具体设备固件决定。
- `local_files.py` 明确不承诺抵御同权限恶意进程，也不把打开目录的移动视作路径快照。
- USB 原生库仅在 macOS 构建产物中随包；Windows 产物不含该能力，`usb-transfer` 在非 macOS 上不可用。
