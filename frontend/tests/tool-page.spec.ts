import { test, expect } from '@playwright/test'

test.describe('PDF 转 Markdown 工具页', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/#/tools/pdf-to-markdown')
  })

  test('默认显示上传状态', async ({ page }) => {
    await expect(page.getByText('将 PDF 文件拖拽到此处')).toBeVisible()
  })

  test('切换为进度状态', async ({ page }) => {
    await page.getByText('转换中').click()
    await expect(page.getByText('读取 PDF 文件')).toBeVisible()
    await expect(page.getByText('生成 Markdown')).toBeVisible()
  })

  test('切换为结果状态', async ({ page }) => {
    await page.getByText('结果展示').click()
    await expect(page.getByText('转换结果')).toBeVisible()
    await expect(page.getByText('下载 .md')).toBeVisible()
    await expect(page.getByText('12 页')).toBeVisible()
  })

  test('切换为错误状态', async ({ page }) => {
    await page.getByText('错误状态').click()
    await expect(page.getByText('转换失败')).toBeVisible()
    await expect(page.getByText('该 PDF 文件包含加密内容')).toBeVisible()
  })

  test('所有演示按钮可点击', async ({ page }) => {
    const buttons = ['上传状态', '转换中', '结果展示', '错误状态']
    for (const text of buttons) {
      await page.getByText(text).click()
    }
  })
})
