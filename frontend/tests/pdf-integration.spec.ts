import { test, expect } from '@playwright/test'
import path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

const testFile = path.resolve(
  __dirname,
  '../../数据/2025年6月六级真题原卷（全3套）/2025.06六级真题第1套.pdf'
)

test.describe('PDF 转 Markdown 前后端联调', () => {

  test('上传 PDF 文件并查看转换结果', async ({ page }) => {
    await page.goto('/#/tools/pdf-to-markdown')
    await expect(page.getByText('将 PDF 文件拖拽到此处')).toBeVisible()

    await page.locator('input[type="file"]').setInputFiles(testFile)

    await expect(page.getByText('正在解析 PDF 文件...')).toBeVisible({ timeout: 10000 })

    await expect(page.getByText('转换结果')).toBeVisible({ timeout: 60000 })

    await expect(page.getByText(/\d+ 页/).first()).toBeVisible()
    await expect(page.getByText(/\d+ 张图片/)).toBeVisible()

    const preview = page.locator('.markdown-preview')
    await expect(preview).toBeVisible()
    const content = await preview.textContent()
    expect(content?.length).toBeGreaterThan(0)

    await expect(page.getByText('下载 .md')).toBeVisible()
  })

  test('勾选深度解析后上传 PDF 并查看进度', async ({ page }) => {
    test.setTimeout(300000)
    await page.goto('/#/tools/pdf-to-markdown')
    const checkbox = page.locator('input[type="checkbox"]')
    await checkbox.check()
    await expect(checkbox).toBeChecked()

    await page.locator('input[type="file"]').setInputFiles(testFile)

    await expect(page.getByText('正在处理')).toBeVisible({ timeout: 10000 })

    const stagePattern = /正在|准备|加载|识别|提取|生成|解析|排队/
    await expect(page.getByText(stagePattern)).toBeVisible({ timeout: 120000 })

    await expect(page.getByText('转换结果')).toBeVisible({ timeout: 120000 })

    await expect(page.getByText(/\d+ 页/).first()).toBeVisible()
    const preview = page.locator('.markdown-preview')
    await expect(preview).toBeVisible()
    const content = await preview.textContent()
    expect(content?.length).toBeGreaterThan(0)
  })

  test('重置后可重新上传', async ({ page }) => {
    await page.goto('/#/tools/pdf-to-markdown')

    await page.locator('input[type="file"]').setInputFiles(testFile)

    await expect(page.getByText('转换结果')).toBeVisible({ timeout: 60000 })

    await page.getByText('重新上传').click()
    await expect(page.getByText('将 PDF 文件拖拽到此处')).toBeVisible()
  })
})
