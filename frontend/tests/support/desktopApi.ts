/**
 * Playwright 共享 fixture
 * 功能描述：向页面注入桌面端控制面凭据，使浏览器用例可访问受保护的本机 API
 * 说明：控制面凭据由后端启动时写入用户数据目录，浏览器环境没有 preload，只能由此补齐
 */

import { test as base, expect } from '@playwright/test'
import { readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const APP_DATA_DIR_NAME = '工具盒子'
const packageJsonPath = fileURLToPath(new URL('../../package.json', import.meta.url))

/** 与后端 core/config.py 的默认数据目录保持一致。 */
function resolveDataDir(): string {
  const configured = process.env.TOOLBOX_DATA_DIR
  if (configured) return path.resolve(configured)

  const home = homedir()
  if (process.platform === 'win32') {
    return path.resolve(path.join(process.env.APPDATA || path.join(home, 'AppData', 'Roaming'), APP_DATA_DIR_NAME))
  }
  if (process.platform === 'darwin') {
    return path.resolve(path.join(home, 'Library', 'Application Support', APP_DATA_DIR_NAME))
  }
  return path.resolve(path.join(process.env.XDG_CONFIG_HOME || path.join(home, '.config'), APP_DATA_DIR_NAME))
}

/**
 * 读取凭据文件中属于本次后端实例的 token。
 * 该文件是包含 instance_id/launch_id/token 的 JSON 身份包，不是裸字符串。
 */
function readControlToken(): string {
  try {
    const raw = readFileSync(path.join(resolveDataDir(), 'runtime', 'control-token'), 'utf-8')
    const bundle: unknown = JSON.parse(raw)
    if (typeof bundle === 'object' && bundle !== null) {
      const token = (bundle as { token?: unknown }).token
      if (typeof token === 'string') return token
    }
    return ''
  } catch {
    return ''
  }
}

function readAppVersion(): string {
  try {
    return String(JSON.parse(readFileSync(packageJsonPath, 'utf-8')).version ?? '')
  } catch {
    return ''
  }
}

interface Fixtures {
  injectDesktopApi: void
}

export const test = base.extend<Fixtures>({
  // 自动生效：所有用例都能在浏览器环境下取到控制面凭据。
  injectDesktopApi: [
    async ({ page }, use) => {
      await page.addInitScript(
        (payload: { token: string; version: string }) => {
          window.desktopApi = {
            platform: 'playwright',
            versions: {
              node: '',
              chrome: '',
              electron: '',
              app: payload.version,
            },
            getControlToken: async () => payload.token,
          } as unknown as Window['desktopApi']
        },
        { token: readControlToken(), version: readAppVersion() }
      )
      await use()
    },
    { auto: true },
  ],
})

export { expect }
