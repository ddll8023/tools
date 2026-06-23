import { test, expect } from '@playwright/test'

const SIDEBAR_COLLAPSED_CLASS = '-ml-\\[220px\\]'

test.describe('侧边栏', () => {
  test('首页默认收起', async ({ page }) => {
    await page.goto('/')
    const sidebar = page.locator('aside')
    await expect(sidebar).toHaveClass(new RegExp(SIDEBAR_COLLAPSED_CLASS))
  })

  test('工具页默认展开', async ({ page }) => {
    await page.goto('/#/tools/pdf-to-markdown')
    const sidebar = page.locator('aside')
    await expect(sidebar).not.toHaveClass(new RegExp(SIDEBAR_COLLAPSED_CLASS))
  })

  test('汉堡按钮切换展开/收起', async ({ page }) => {
    await page.goto('/')
    const sidebar = page.locator('aside')
    const toggle = page.getByLabel('切换侧边栏')

    await toggle.click()
    await expect(sidebar).not.toHaveClass(new RegExp(SIDEBAR_COLLAPSED_CLASS))

    await toggle.click()
    await expect(sidebar).toHaveClass(new RegExp(SIDEBAR_COLLAPSED_CLASS))
  })

  test('侧边栏当前工具高亮', async ({ page }) => {
    await page.goto('/#/tools/pdf-to-markdown')
    const activeItem = page.locator('aside a').filter({ hasText: 'PDF 转 Markdown' })
    await expect(activeItem).toHaveClass(/bg-primary-light/)
  })

  test('侧边栏可返回首页', async ({ page }) => {
    await page.goto('/#/tools/pdf-to-markdown')
    await page.locator('aside').getByText('首页').click()
    await expect(page).toHaveURL(/\/$/)
  })
})
