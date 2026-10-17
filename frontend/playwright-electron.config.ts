import { defineConfig } from '@playwright/test'

// Electron 主进程自行启动后端与 Vite，因此这里不再声明 webServer，
// 否则会与 Electron 管理的服务争用端口和后端应用锁。
export default defineConfig({
  testDir: './tests',
  testMatch: 'electron.spec.ts',
  fullyParallel: false,
  retries: 0,
  workers: 1,
  reporter: 'html',
  use: {
    baseURL: 'http://127.0.0.1:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
})
