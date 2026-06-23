# 工具盒子 - 项目指南

## 前端测试

### 测试策略

| 类型 | 说明 | 后端依赖 |
|------|------|---------|
| 纯 UI 测试 | 验证组件渲染、交互逻辑，不上传真实文件 | ❌ 无需后端 |
| 联调测试 | 前后端集成验证，上传真实文件校验完整数据流 | ✅ Playwright 自动启动后端 |

Playwright + Chromium，测试文件位于 `frontend/tests/`。

### webServer 管理

Playwright 通过 `webServer` 配置自动管理服务进程，开发者无需手动启动：

- **纯 UI 测试**：仅启动 Vite（端口 5173）
- **联调测试**：自动启动 Vite + 后端 Uvicorn（端口 4740）
- 若对应端口已有进程，`reuseExistingServer: true` 会复用现有服务

### 编写测试

**纯 UI 测试**：在 `test.describe` 中直接验证 DOM 状态，无需后端。

**联调测试**：

```ts
import { test, expect } from '@playwright/test'

test('上传 PDF 并验证转换结果', async ({ page }) => {
  await page.goto('/#/tools/pdf-to-markdown')

  // 文件路径从项目根目录的数据/ 下选取
  const testFile = 'path/to/test.pdf'
  await page.locator('input[type="file"]').setInputFiles(testFile)

  // 等待进度 → 等待结果 → 验证预览
  await expect(page.getByText('正在解析 PDF 文件...')).toBeVisible({ timeout: 10000 })
  await expect(page.getByText('转换结果')).toBeVisible({ timeout: 60000 })

  // 验证统计和内容
  await expect(page.getByText(/\d+ 页/).nth(1)).toBeVisible()
  await expect(page.getByText(/\d+ 张图片/)).toBeVisible()
  const preview = page.locator('.whitespace-pre-wrap')
  await expect(preview).toBeVisible()
  const content = await preview.textContent()
  expect(content?.length).toBeGreaterThan(0)
})
```

新增联调测试时无需修改 `playwright.config.ts`（已配置好 Vite + Backend）。

### 运行测试

```bash
cd frontend

# 运行全部测试（纯 UI + 联调，自动启动 Vite + Backend）
npx playwright test

# 仅运行纯 UI 测试（跳过联调）
npx playwright test --grep-invert "前后端联调"

# 仅运行联调测试
npx playwright test tests/pdf-integration.spec.ts

# 有头模式（可见浏览器窗口）
npx playwright test --headed

# 交互式 UI 模式
npx playwright test --ui

# 运行单个文件
npx playwright test tests/home.spec.ts

# 查看 HTML 报告
npx playwright show-report
```

### 注意事项

- 项目使用 Vite + hash 路由，测试中访问工具页路径需加 `/#/` 前缀
- Vite dev server 端口为 5173，后端端口 4740，均由 Playwright 配置自动管理
- 仅安装了 Chromium，未安装 Firefox/WebKit
- 测试无需手动启动任何服务（webServer 配置自动处理）
- 首页侧边栏默认收起，工具页侧边栏默认展开
- 21 个测试预计耗时约 10 秒，Electron 5 个测试约 3 秒
- 有头模式默认无 slowMo，如需观察操作过程可临时添加 `launchOptions: { slowMo: 500 }`

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

- Electron 测试通过 `BACKEND_MANAGED=1` 环境变量让主进程跳过 Vite 启动，由 Playwright webServer 统一管理
- 其他注意事项与前端测试相同

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
