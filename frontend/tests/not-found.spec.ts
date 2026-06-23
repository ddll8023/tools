import { test, expect } from '@playwright/test'

test.describe('404 页面', () => {
  test('无效路由显示 404', async ({ page }) => {
    await page.goto('/#/nonexistent')
    await expect(page.getByText('404')).toBeVisible()
    await expect(page.getByText('页面不存在')).toBeVisible()
  })

  test('点击返回首页回到首页', async ({ page }) => {
    await page.goto('/#/nonexistent')
    await page.getByText('返回首页').click()
    await expect(page).toHaveURL(/\/$/)
  })
})
