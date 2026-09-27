/** 验证设置页证件照模型下载、进度和路径边界。 */
import { test, expect } from '@playwright/test'

const modelApi = 'http://127.0.0.1:4740/api/v1/settings/models'

function mineruStatus() {
  return {
    model_id: 'mineru-pipeline',
    name: 'MinerU Pipeline',
    description: 'PDF 深度解析模型',
    source: 'ModelScope',
    path: 'C:/data/resources/mineru',
    approx_size_bytes: 2147483648,
    status: 'not_downloaded',
    progress: null,
    stage: '尚未下载模型',
    error: null,
    job_id: null,
    can_download: false,
    can_delete: false,
    delete_reason: '没有可删除的模型缓存',
  }
}

function idPhotoStatus(overrides: Record<string, unknown> = {}) {
  return {
    model_id: 'id-photo',
    name: '证件照模型',
    description: '本地人脸检测与人像抠图模型',
    source: '用户数据目录',
    path: 'C:/Users/test/AppData/工具盒子/resources/id_photo',
    approx_size_bytes: null,
    status: 'not_downloaded',
    progress: null,
    stage: '证件照模型未准备',
    error: '缺少人像抠图模型，当前资源目录需包含：hivision_modnet.onnx',
    job_id: null,
    can_download: true,
    can_delete: false,
    delete_reason: '没有可删除的用户数据模型',
    ...overrides,
  }
}

test.describe('设置页证件照模型管理', () => {
  test('支持主动下载、查看进度并取消', async ({ page }) => {
    let currentStatus = idPhotoStatus()

    await page.route(`${modelApi}/status`, async (route) => {
      await route.fulfill({
        json: {
          code: 0,
          message: 'ok',
          data: { models: [mineruStatus(), currentStatus] },
        },
      })
    })
    await page.route(`${modelApi}/download`, async (route) => {
      const request = route.request().postDataJSON() as { model_id: string }
      if (request.model_id === 'id-photo') {
        currentStatus = idPhotoStatus({
          status: 'downloading',
          progress: 45,
          stage: '正在下载人像抠图模型...',
          error: null,
          job_id: 'photo-download',
          can_download: false,
          delete_reason: '证件照模型下载中，暂不能删除',
        })
      }
      await route.fulfill({
        json: { code: 0, message: 'ok', data: currentStatus },
      })
    })
    await page.route(`${modelApi}/cancel`, async (route) => {
      currentStatus = idPhotoStatus({
        status: 'cancelled',
        progress: 45,
        stage: '证件照模型下载已取消',
        error: '下载已取消，可重新准备模型。',
      })
      await route.fulfill({
        json: { code: 0, message: 'ok', data: currentStatus },
      })
    })

    await page.goto('/#/settings')
    const card = page.locator('section[aria-labelledby="id-photo-model-title"]')
    await card.getByRole('button', { name: '下载并准备模型' }).click()
    await expect(card.getByText('45%')).toBeVisible()
    await card.getByRole('button', { name: '取消下载' }).click()
    await expect(card.getByText('已取消', { exact: true })).toBeVisible()
    await expect(card.getByRole('button', { name: '重试下载' })).toBeVisible()
  })

  test('自定义路径模型显示手动准备说明且不开放下载', async ({ page }) => {
    const customPathStatus = idPhotoStatus({
      source: '自定义路径',
      path: 'D:/models/id-photo',
      can_download: false,
      error: '缺少人像抠图模型，当前资源目录需包含：hivision_modnet.onnx',
    })

    await page.route(`${modelApi}/status`, async (route) => {
      await route.fulfill({
        json: {
          code: 0,
          message: 'ok',
          data: { models: [mineruStatus(), customPathStatus] },
        },
      })
    })

    await page.goto('/#/settings')
    const card = page.locator('section[aria-labelledby="id-photo-model-title"]')
    await expect(card.getByText('请按当前模型路径手动准备资源。')).toBeVisible()
    await expect(card.getByRole('button', { name: '下载并准备模型' })).toHaveCount(0)
    await expect(card.getByRole('button', { name: '复制模型路径' })).toBeVisible()
  })
})
