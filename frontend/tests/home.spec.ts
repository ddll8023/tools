import { test, expect } from '@playwright/test'

test.describe('首页', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
  })

  test('渲染品牌标题和 Logo', async ({ page }) => {
    await expect(page.getByRole('heading', { name: '工具盒子' })).toBeVisible()
    await expect(page.getByText('轻量文档处理工具集')).toBeVisible()
  })

  test('显示工具卡片', async ({ page }) => {
    const card = page.getByRole('heading', { name: 'PDF 转 Markdown' })
    await expect(card).toBeVisible()
  })

  test('点击工具卡片跳转到工具页', async ({ page }) => {
    await page.getByRole('heading', { name: 'PDF 转 Markdown' }).click()
    await expect(page).toHaveURL(/\/tools\/pdf-to-markdown/)
  })

  test('显示页脚信息', async ({ page }) => {
    await expect(page.getByText('本地处理，文件不会上传')).toBeVisible()
    await expect(page.getByText('v0.1.0')).toBeVisible()
  })
})
