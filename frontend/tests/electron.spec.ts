import { test, expect, _electron as electron } from '@playwright/test'
import type { ElectronApplication, Page } from '@playwright/test'
import * as path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

const BASE_URL = 'http://127.0.0.1:5173'

let app: ElectronApplication
let page: Page

test.beforeAll(async () => {
  const mainJs = path.resolve(__dirname, '../../electron/main.js')
  app = await electron.launch({
    args: [mainJs, '--no-sandbox'],
    env: {
      ...process.env,
      BACKEND_MANAGED: '1',
      ComSpec: process.env.ComSpec || 'C:\\WINDOWS\\system32\\cmd.exe'
    }
  })

  // 等待主窗口并导航到首页
  page = await app.firstWindow()
  await page.goto(`${BASE_URL}/#/`)
  await page.waitForLoadState('networkidle')
})

test.afterAll(async () => {
  await app.close()
})

test.describe('Electron 桌面壳', () => {
  test('窗口正常打开，显示首页', async () => {
    await expect(page.getByRole('heading', { name: '工具盒子' })).toBeVisible()
    await expect(page.getByText('轻量文档处理工具集')).toBeVisible()
  })

  test('点击 PDF 转 Markdown 卡片跳转到工具页', async () => {
    await page.goto(`${BASE_URL}/#/`)
    await page.waitForLoadState('networkidle')
    await page.getByRole('heading', { name: 'PDF 转 Markdown' }).click()
    await expect(page).toHaveURL(/tools\/pdf-to-markdown/)
    await expect(page.getByText('将 PDF 文件拖拽到此处')).toBeVisible()
  })

  test('汉堡按钮切换侧边栏', async () => {
    await page.goto(`${BASE_URL}/#/`)
    await page.waitForLoadState('networkidle')
    const sidebar = page.locator('aside')

    await page.getByLabel('切换侧边栏').click()
    await expect(sidebar).not.toHaveClass(/-ml-\[220px\]/)

    await page.getByLabel('切换侧边栏').click()
    await expect(sidebar).toHaveClass(/-ml-\[220px\]/)
  })

  test('工具页侧边栏默认展开', async () => {
    await page.goto(`${BASE_URL}/#/tools/pdf-to-markdown`)
    await page.waitForLoadState('networkidle')
    const sidebar = page.locator('aside')
    await expect(sidebar).not.toHaveClass(/-ml-\[220px\]/)
  })

  test('preload 正确暴露 desktopApi', async () => {
    const desktopApi = await page.evaluate(() => {
      return (window as any).desktopApi
    })
    expect(desktopApi).toBeDefined()
    expect(desktopApi.platform).toBe('win32')
    expect(desktopApi.versions).toBeDefined()
    expect(desktopApi.versions.electron).toBeDefined()
  })
})
