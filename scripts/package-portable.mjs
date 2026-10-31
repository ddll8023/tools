/**
 * 便携出包入口：按当前主机平台产出一份免安装 zip（Windows 解压即程序文件夹，macOS 顶层为 .app）。
 *
 * 只做前置断言、参数解析、镜像兜底与进程转发，不改变打包内容：先确认前端产物、主进程编译产物、
 * 后端运行时与（macOS）USB 原生依赖都在，再交给 electron-builder；缺任何一项直接失败，
 * 不产出一个看似成功却缺资源的坏包。
 *
 * 平台与架构在这里钉死，与主机不一致时同样直接失败：后端运行时由 PyInstaller 在本机编译，
 * USB 原生库只在 macOS arm64 构建，跨平台出包拿不到可用的二进制。
 */
import { spawnSync } from 'node:child_process'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')

/** 镜像兜底值：只在对应环境变量为空时生效，已显式设置的值不被覆盖 */
const mirrorDefaults = {
  ELECTRON_MIRROR: 'https://npmmirror.com/mirrors/electron/',
  ELECTRON_BUILDER_BINARIES_MIRROR: 'https://npmmirror.com/mirrors/electron-builder-binaries/'
}

/**
 * 各平台的出包参数与唯一可出架构。
 *
 * macOS 只能是 arm64：backend/packaging/backend.spec 只收集 darwin/arm64 的 USB 原生库，
 * scripts/build-backend-runtime.js 在其他架构上直接失败。Windows 当前只交付 x64。
 */
const platforms = {
  win32: { argument: '--win', name: 'Windows', arch: 'x64' },
  darwin: { argument: '--mac', name: 'macOS', arch: 'arm64' }
}

function fail(message) {
  console.error(`[package] ${message}`)
  process.exit(1)
}

/** 入口由 electron-builder 自身声明，不假定 bin 目录结构与平台后缀 */
function resolveBuilderEntry() {
  const manifestFile = resolve(projectRoot, 'node_modules', 'electron-builder', 'package.json')
  let manifest
  try {
    manifest = JSON.parse(readFileSync(manifestFile, 'utf8'))
  } catch {
    fail('未安装 electron-builder；请先在项目根目录执行 npm install。')
  }
  const declared = typeof manifest.bin === 'string' ? manifest.bin : manifest.bin?.['electron-builder']
  if (typeof declared !== 'string') fail('electron-builder 未声明可执行入口。')
  return resolve(projectRoot, 'node_modules', 'electron-builder', declared)
}

/** 平台参数缺省取当前主机；显式指定时必须是本机能出的平台 */
function resolvePlatform() {
  const requested = process.argv.slice(2).filter((value) => value === '--win' || value === '--mac')
  if (requested.length > 1) fail('一次只能指定一个平台参数：--win 或 --mac。')
  const host = platforms[process.platform]
  if (requested.length === 0) {
    if (!host) fail(`当前平台 ${process.platform} 不在支持的出包平台内。`)
    return host
  }
  const target = Object.values(platforms).find((platform) => platform.argument === requested[0])
  if (!host || target.argument !== host.argument) {
    fail(`只能在本机产出本机平台的包：请在 ${target.name} 主机上执行 ${requested[0]}。`)
  }
  return target
}

/** 出包前断言随包资源齐全，缺项直接失败，不让 electron-builder 静默漏包。 */
function assertBundleInputs() {
  const required = [
    ['前端构建产物', resolve(projectRoot, 'frontend', 'dist', 'index.html')],
    ['主进程编译产物', resolve(projectRoot, 'electron', 'main.js')],
    [
      '后端运行时',
      resolve(
        projectRoot,
        'build',
        'backend-runtime',
        process.platform === 'win32' ? 'toolbox-backend.exe' : 'toolbox-backend'
      )
    ]
  ]
  if (process.platform === 'darwin') {
    required.push([
      'USB 原生依赖清单',
      resolve(projectRoot, 'build', 'usb-native', 'dist', 'manifest.json')
    ])
  }
  const missing = required.filter(([, file]) => !existsSync(file))
  if (missing.length > 0) {
    for (const [name, file] of missing) console.error(`[package] 缺少${name}: ${file}`)
    fail('出包前置资源不完整；先执行 npm run build:release（macOS 还需 npm run build:usb-native）。')
  }
}

const platform = resolvePlatform()
if (process.arch !== platform.arch) {
  fail(`${platform.name} 包只能在 ${platform.arch} 主机上产出，当前主机架构为 ${process.arch}。`)
}
assertBundleInputs()

const env = { ...process.env }
for (const [name, value] of Object.entries(mirrorDefaults)) {
  if (!env[name]) env[name] = value
}

const result = spawnSync(
  process.execPath,
  [resolveBuilderEntry(), platform.argument, `--${platform.arch}`, '--publish', 'never'],
  { cwd: projectRoot, env, stdio: 'inherit' }
)
if (result.error) throw result.error
if (result.status !== 0) process.exit(result.status ?? 1)
console.log(`[package] 便携产物已生成：${resolve(projectRoot, 'release')}`)
