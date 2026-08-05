import { test, expect } from '@playwright/test'

test.describe('PDF 转 Word 工具页', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/#/tools/pdf-to-word')
  })

  test('默认显示上传区域', async ({ page }) => {
    await expect(page.getByText('将 PDF 文件拖拽到此处')).toBeVisible()
  })

  test('显示文件上传按钮', async ({ page }) => {
    await expect(page.getByText('选择 PDF 文件')).toBeVisible()
  })

  test('显示文件格式和扫描件限制提示', async ({ page }) => {
    await expect(page.getByText(/支持 \.pdf 格式，最大 50MB/)).toBeVisible()
    await expect(page.getByText(/纯扫描 PDF 暂不支持/)).toBeVisible()
  })
})
