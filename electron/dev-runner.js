/**
 * 开发启动器：编译主进程后启动 Electron，后端与 Vite 统一由 Electron 管理。
 *
 * 不再自行拉起后端，避免同一份数据目录和 USB 设备出现两个所有者；
 * 收到中断信号时只转发给 Electron，由其完成传输停止协调。
 */
const path = require('path')
const { spawn } = require('child_process')

const ROOT_DIR = path.resolve(__dirname, '..')
const FORCE_KILL_WINDOW_MS = 5000

function runCompile() {
  const npmCommand = process.platform === 'win32' ? 'npm.cmd' : 'npm'
  const tscProc = spawn(npmCommand, ['run', 'compile:electron'], {
    cwd: ROOT_DIR,
    // Windows 的 npm.cmd 需要通过 shell 启动；参数均为固定值，不拼接用户输入。
    shell: process.platform === 'win32',
    stdio: 'inherit'
  })
  return new Promise((resolve, reject) => {
    tscProc.on('error', reject)
    tscProc.on('close', (code) => {
      if (code !== 0) return reject(new Error('TypeScript 编译失败'))
      resolve()
    })
  })
}

async function main() {
  console.log('[dev-runner] 1/2 编译 Electron 主进程 ...')
  await runCompile()
  console.log('[dev-runner] ✓ TypeScript 编译完成')

  console.log('[dev-runner] 2/2 启动 Electron（后端与 Vite 由主进程管理）...')
  const electronPath = require('electron')
  const electronProc = spawn(electronPath, ['.'], {
    cwd: ROOT_DIR,
    stdio: 'inherit',
    env: { ...process.env }
  })

  let interruptAt = 0
  const forward = (signal) => {
    if (!electronProc.pid) return
    const now = Date.now()
    // 首次中断交给 Electron 走协调退出；短时间内再次中断才视为要求强制结束。
    if (interruptAt && now - interruptAt < FORCE_KILL_WINDOW_MS) {
      console.warn('[dev-runner] 再次收到中断，强制结束 Electron')
      try {
        electronProc.kill('SIGKILL')
      } catch {
        // 进程已退出
      }
      return
    }
    interruptAt = now
    console.log('[dev-runner] 请求 Electron 有序退出；若正在传输，请在窗口中选择是否停止')
    try {
      electronProc.kill(signal)
    } catch {
      // 进程已退出
    }
  }

  process.on('SIGINT', () => forward('SIGINT'))
  process.on('SIGTERM', () => forward('SIGTERM'))

  electronProc.on('error', (error) => {
    console.error('[dev-runner] ❌ Electron 启动失败:', error.message)
    process.exit(1)
  })
  electronProc.on('close', (code) => {
    console.log('[dev-runner] Electron 退出, code:', code)
    process.exit(code || 0)
  })
}

main().catch((err) => {
  console.error('[dev-runner] ❌ 启动失败:', err.message || err)
  process.exit(1)
})
