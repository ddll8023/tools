# 工具盒子 - 项目指南

## 前端测试

### 技术栈

Playwright + Chromium，测试文件位于 `frontend/tests/`。

### 运行测试

```bash
cd frontend

# 运行全部测试（自动启动 Vite dev server）
npx playwright test

# 有头模式（可见浏览器窗口）
npx playwright test --headed

# 交互式 UI 模式
npx playwright test --ui

# 运行单个文件
npx playwright test tests/home.spec.ts

# 查看 HTML 报告
npx playwright show-report
```

### 测试文件

| 文件 | 覆盖内容 |
|---|---|
| `tests/home.spec.ts` | 首页渲染、工具卡片、导航跳转、页脚 |
| `tests/sidebar.spec.ts` | 侧边栏收起/展开、默认状态、当前工具高亮、返回首页 |
| `tests/tool-page.spec.ts` | 工具页四种状态切换（上传/进度/结果/错误） |
| `tests/not-found.spec.ts` | 404 页面渲染、返回首页按钮 |
| `tests/electron.spec.ts` | Electron 窗口、导航、侧边栏、preload |

## Electron 测试

### 运行 Electron 测试

```bash
cd frontend

# 运行 Electron 测试（自动启动 Vite + Electron）
npx playwright test --config=playwright-electron.config.ts

# 有头模式
npx playwright test --config=playwright-electron.config.ts --headed
```

### 前置步骤

Electron 主进程 TypeScript 编译：

```bash
# 在项目根目录
npm run compile:electron

# 或
cd electron && npx tsc -p tsconfig.json
```

### 注意事项

- 项目使用 Vite + hash 路由，测试中访问工具页路径需加 `/#/` 前缀
- Vite dev server 端口为 5173，由 Playwright 配置自动管理
- 仅安装了 Chromium，未安装 Firefox/WebKit
- 测试无需手动启动 dev server（webServer 配置自动处理）
- 首页侧边栏默认收起，工具页侧边栏默认展开
- 21 个测试预计耗时约 9 秒，Electron 5 个测试约 3 秒
- 有头模式默认无 slowMo，如需观察操作过程可临时添加 `launchOptions: { slowMo: 500 }`
- Electron 测试通过 `BACKEND_MANAGED=1` 环境变量让主进程跳过 Vite 启动，由 Playwright webServer 统一管理

## 后端开发

### 技术栈

FastAPI + Uvicorn + Python 3.12，包管理使用 uv。

### 目录结构

```
backend/
├── app/
│   ├── main.py              # FastAPI 入口 + 全局异常处理器
│   ├── core/config.py       # Settings（pydantic-settings）
│   ├── utils/
│   │   ├── exception.py     # ServiceException
│   │   └── logger_config.py # 统一日志
│   ├── schemas/response.py  # 统一响应 success()/error() + ApiResponse
│   └── api/v1/
│       ├── health.py        # POST /api/v1/health
│       └── tools.py         # POST /api/v1/tools/list
├── pyproject.toml
├── .env
└── .python-version
```

### 启动方式

```bash
# 从项目根目录
npm run dev:backend

# 或直接使用 uv
cd backend
uv run uvicorn app.main:app --reload
```

### 验证

```bash
curl -X POST http://127.0.0.1:4740/api/v1/health
# 返回：{"code":0,"message":"success","data":{"status":"ok"}}
```

### 依赖管理

```bash
cd backend
uv add 包名     # 新增依赖
uv sync         # 同步依赖
```
