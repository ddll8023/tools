# 桌面外壳

模块标识：`desktop-shell`。返回 [项目结构](../项目结构文档.md)。

## 职责与入口

负责 Electron 主进程的单实例约束、窗口创建与窗口控制、所属后端的启动与有序停止、跨业务共享的桌面能力（文件/目录选择、本地 Markdown 读取、Markdown 打印、更新安装），以及渲染进程可见的 `window.desktopApi` 契约。

不负责具体工具的业务逻辑与协议：Markdown 打印的排版内容由前端生成，本地 Markdown 的图片解析归本模块的 `markdown-source`，但 Markdown → PDF 的整体用例见 [Markdown 转 PDF](markdown-to-pdf.md)；工具 API 全部由后端提供。

入口：`package.json` 的 `"main": "electron/main.js"`；开发态由 `electron/dev-runner.js` 先执行 `npm run compile:electron` 再启动 Electron。

## 专属文件

| 文件 | 当前用途及纳入依据 |
| --- | --- |
| `electron/main.ts` | 主进程装配：`resolveDataRoot`、单实例锁、`createWindow`、`registerWindowIpc`、`bootstrap`、`window-all-closed`/`before-quit` |
| `electron/app-lifecycle.ts` | `AppLifecycle`：退出/关闭/安装统一协调，`prepareClose`、`prepareInstall`、`takeAfterStop`、`resetForRestart` |
| `electron/backend-runtime.ts` | `BackendRuntime`：spawn 后端、按 `launch_id` 确认身份、读凭据、`status`/`stop`、进程组终止 |
| `electron/preload.ts` | `contextBridge.exposeInMainWorld('desktopApi', ...)`；拖拽/选择文件的路径捕获（`recordPaths`/`takeDroppedPaths`） |
| `electron/update-types.ts` | `UpdateStatus`、`UpdateCommandResult`，主进程与 preload 共用 |
| `electron/update-state.ts` | 当前更新状态与 `broadcast` 广播 |
| `electron/updater.ts` | `registerUpdaterIpc`、`initializeUpdater`、`checkForUpdates`；按平台分流到 `mac-updater` 或 `electron-updater` |
| `electron/mac-updater.ts` | macOS 免签名更新：GitHub Releases 检查、HTTPS 流式下载、SHA-512 校验、调用 helper |
| `electron/update-helper.ts` | 独立安装脚本（打包为 `Resources/update-helper.js`）：等主进程退出、校验 ZIP、启动更新守卫、替换 `.app`、写结果、重启 |
| `electron/dev-runner.js` | 唯一手写 JS：编译主进程后启动 Electron，信号只转发给 Electron |
| `electron/tsconfig.json` | `commonjs`、`outDir: "."`，编译产物与源码同目录 |
| `frontend/src/components/layout/AppShell.vue` | 无边框窗口的自绘标题栏、窗口控制按钮、侧边栏容器、更新提示条 |
| `backend/src/toolbox_backend/api/v1/health.py` | `POST /api/v1/health`，返回 `instance_id`/`launch_id`/`pid`/`phase` |
| `backend/src/toolbox_backend/api/v1/runtime.py` | `POST /runtime/status`、`POST /runtime/stop`，按 `expected_instance_id` 校验实例 |
| `backend/src/toolbox_backend/schemas/runtime.py` | 上述两接口的请求与状态契约 |

`electron/*.js`（除 `dev-runner.js`）是 `npm run compile:electron` 的产物，被 `.gitignore` 排除，不作为源码登记。`package.json` 的 `main` 与 electron-builder 的 `files` 都指向 `.js`，因此开发启动与打包都必须先执行编译；`.js` 与 `.ts` 不一致时，运行行为以 `.js` 为准。

## 公共与跨模块引用

路径书写：`backend/`、`frontend/`、`electron/` 开头的为仓库根相对路径；本节省略前缀的后端路径默认在 `backend/src/toolbox_backend/` 下，省略前缀的前端路径默认在 `frontend/src/` 下。

| 所属模块／公共记录 | 文件与使用范围 | 本模块为何引用 |
| --- | --- | --- |
| [公共记录](shared.md) `backend-runtime-core` | `core/runtime.py` 的 `RuntimeIdentity`、`acquire_ownership`、`run_update_guard`；`core/control_auth.py` 的凭据文件格式 | 主进程读凭据、更新守卫持锁；`RuntimeSnapshot` 的字段与 `schemas/runtime.py` 对应 |
| [公共记录](shared.md) `backend-api-shell` | `api/v1/router.py` 的 `/api/v1` 前缀 | `backend-runtime.ts` 的 `API_PREFIX` 必须与之保持一致 |
| [公共记录](shared.md) `build-and-packaging` | `package.json` 的 `extraResources`（`update-helper.js`）、`files`（`electron/**/*.js`） | 决定哪些 `.js` 会进入安装包 |
| [公共记录](shared.md) `frontend-desktop-contract` | `frontend/src/types/electron.d.ts` | 与 `preload.ts` 暴露对象一一对应 |
| [工具目录](tool-catalog.md) | `frontend/src/router/tools.ts` 的 `toolConfigs`；`frontend/src/components/layout/AppSidebar.vue` | `AppShell` 把 `AppSidebar` 作为侧边栏内容；该组件由工具目录模块拥有，因其职责是渲染工具导航 |
| [Markdown 转 PDF](markdown-to-pdf.md) | `electron/markdown-to-pdf.ts`、`electron/markdown-source.ts` | 在 `bootstrap` 中注册 IPC，并在 `before-quit` 调用 `cancelMarkdownPdf` |

## 关键调用链

### 启动

1. `electron/dev-runner.js` 编译并 `spawn` Electron（开发态），或用户直接启动安装包。
2. `main.ts` 先 `app.setName('toolbox-desktop')`、固定 `userAgentFallback`、解析 `DATA_ROOT` 并 `app.setPath('userData')`。
3. `app.requestSingleInstanceLock()` 失败直接 `app.exit(0)`；成功才注册信号处理与 `second-instance`。
4. `bootstrap()` 依次 `registerWindowIpc`、`registerUpdaterIpc`、`registerMarkdownPdfIpc`、`registerMarkdownSourceIpc`、`setLifecycle`。
5. `backend.start()` → `BackendRuntime.waitForIdentity()` 轮询 `POST /api/v1/health`，只有 `launch_id` 与本次生成值一致才认领。
6. 开发态再 `startVite()` 并等待 `127.0.0.1:5173` 可达；随后 `createWindow()` 与 `initializeUpdater()`。
7. 后端启动失败时 `lifecycle.stopWithoutPrompt()`、弹错误框、`app.quit()`，不进入业务界面。

### 退出／关闭

1. 窗口 `close` 事件或 `before-quit` 触发。
2. `lifecycle.stopped` 为真则放行；`lifecycle.stopping` 为真则忽略重复请求。
3. `AppLifecycle.prepareClose` 先 `backend.status()` 读取 `usb_active_tasks`/`usb_busy`。
4. 有活动任务或状态未知时 `dialog.showMessageBox`，默认按钮是「留在应用」；无可用窗口时不弹窗、按状态未知继续。
5. 用户确认后 `runStop()` → `backend.stop(45000)` → `POST /runtime/stop`。
6. 后端报告 `usb_stopped && !usb_forced` 时主进程 `terminate()`（SIGTERM 到进程组）并等待退出；否则 `forceKill()` 并记录未确认。
7. macOS 关闭全部窗口后不退出：`lifecycle.resetForRestart()` + `backend.reset()`，`activate` 时 `ensureBackendAndWindow()` 重新启动后端并建窗。

### 更新

1. 打包态 `initializeUpdater()` 后 5 秒异步 `checkForUpdates()`。
2. macOS 走 `mac-updater`：GitHub Releases API → 只接受 HTTPS ZIP → 流式下载 → 校验 `latest-mac.yml` 中的 SHA-512 → 状态 `downloaded`。
3. 用户点击安装 → `updater:quit-and-install` → `lifecycle.prepareInstall`（同样先停传输）→ `macUpdater.installOnQuit()` 启动 helper → `app.quit()`。
4. helper 等主进程 PID 退出 → 启动 `--toolbox-update-guard` 取得应用锁 → `ditto` 解压 → 校验 BundleId/版本/最低系统版本 → 顺序替换（失败尽力回滚）→ 写 `update-result.json` → 重启应用并带 `--toolbox-data-dir=`。
5. Windows/Linux 走 `electron-updater` 的 `autoUpdater`，`quitAndInstall` 同样先经 `prepareInstall`。

## 状态与数据所有者

| 状态／资源 | 所有者 | 副本或消费者 | 生命周期／持久化 |
| --- | --- | --- | --- |
| 数据根路径 | `main.ts` 的 `DATA_ROOT` | `BackendRuntime`（环境变量注入）、`mac-updater`/`update-helper`（结果与下载目录） | 进程级常量，启动解析一次 |
| 后端进程与身份 | `BackendRuntime` 的 `process`/`identity`/`token` | `AppLifecycle`、`main.ts` | 随窗口/应用结束；`reset()` 后可由 `activate` 重启 |
| 退出决策 | `AppLifecycle` 的 `decision`/`stopPromise`/`afterStop` | `main.ts` 的 `close`/`before-quit`、`updater.ts` | 单次运行内缓存，`resetForRestart` 清空 |
| 更新状态 | `update-state.ts` 的 `currentStatus` | 所有窗口（`updater:status`）、`preload` 的 `onStatus` | 内存；`notifyUpdaterWindowReady` 在新窗口加载后补发 |
| 拖拽路径暂存 | `preload.ts` 的 `pendingPaths` | `fileDialog.takeDroppedPaths()` 调用方（局域网投送、USB 传输） | 一次性取走即清空 |
| 更新下载产物与结果 | `mac-updater.ts` 的 `UPDATE_DIR()`/`RESULT_FILE()` | `update-helper` 写结果，`mac-updater` 启动时 `consumeResultFile` 读取 | `<userData>/update`、`<userData>/update-result.json`，7 天保留清理 |

## 生命周期与约束

- 单实例锁先于任何后端启动；第二个实例不生成凭据、不读取恢复记录。
- 就绪判定绑定本次 `launch_id`：端口上有其他后端响应时既不认领也不终止，避免误连或误杀。
- 主进程只结束本次启动的进程组（`detached: true` + `process.kill(-pid)`；Windows 用 `taskkill /T`）。
- 停止超时 `STOP_TIMEOUT_MS = 45000`，须长于后端 `APP_SHUTDOWN_TIMEOUT_SECONDS`（默认 30s）及其收尾。
- 开发态后端用 `uv run uvicorn ... --port 18740`，打包态直接执行 `Resources/backend/toolbox-backend`，cwd 为数据根。
- `SAFE_USER_AGENT` 固定为 ASCII，避免中文应用名进入 UA。

## 当前覆盖边界

- `mac-updater` 与 `update-helper` 的实际发布与替换行为依赖 GitHub Release 资产与 macOS `ditto`，静态阅读只能确认校验与顺序替换逻辑，不能确认特定版本产物的可安装性。
- Windows 更新链路由 `electron-updater` 实现，其行为在第三方库内，本文只登记调用点。
