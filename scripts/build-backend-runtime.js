const fs = require('fs')
const path = require('path')
const { spawnSync } = require('child_process')

const rootDir = path.resolve(__dirname, '..')
const backendDir = path.join(rootDir, 'backend')
const buildDir = path.join(rootDir, 'build')
const runtimeDir = path.join(buildDir, 'backend-runtime')
const workDir = path.join(buildDir, 'backend-work')
const specFile = path.join(backendDir, 'packaging', 'backend.spec')
// 精确版本，不再只约束上界：不同 PyInstaller 的收集与重签名行为会变。
const PYINSTALLER_VERSION = '6.20.0'
const MINIMUM_MACOS_VERSION = '14.0'
const usbNativeDir = path.join(buildDir, 'usb-native', 'dist')

function firstExisting(candidates) {
  return candidates.find((candidate) => fs.existsSync(candidate))
}

const python = process.env.PYTHON || firstExisting(
  process.platform === 'win32'
    ? [
        path.join(backendDir, '.venv', 'Scripts', 'python.exe'),
        path.join(backendDir, '.venv', 'Scripts', 'python'),
      ]
    : [path.join(backendDir, '.venv', 'bin', 'python')],
) || (process.platform === 'win32' ? 'python' : 'python3')

if (!fs.existsSync(specFile)) {
  console.error(`[backend-build] spec 文件不存在: ${specFile}`)
  process.exit(1)
}

fs.rmSync(runtimeDir, { recursive: true, force: true })
fs.rmSync(workDir, { recursive: true, force: true })
fs.mkdirSync(buildDir, { recursive: true })

console.log(`[backend-build] Python: ${python}`)
console.log(`[backend-build] 平台: ${process.platform}/${process.arch}`)

const versionCheck = spawnSync(python, ['-m', 'PyInstaller', '--version'], { encoding: 'utf8' })
if (versionCheck.status !== 0) {
  console.error('[backend-build] 无法读取 PyInstaller 版本，请先在 backend/.venv 安装固定版本。')
  process.exit(1)
}
const installedVersion = (versionCheck.stdout || '').trim()
if (installedVersion !== PYINSTALLER_VERSION) {
  console.error(`[backend-build] 需要 PyInstaller ${PYINSTALLER_VERSION}，当前为 ${installedVersion || '未知'}`)
  process.exit(1)
}

// USB 原生依赖只随 macOS arm64 产物分发，其他平台不构建也不收集。
if (process.platform === 'darwin') {
  if (process.arch !== 'arm64') {
    console.error(`[backend-build] macOS 只构建 arm64，当前为 ${process.arch}`)
    process.exit(1)
  }
  console.log('[backend-build] 构建 USB 原生依赖...')
  const usbBuild = spawnSync(process.execPath, [path.join(rootDir, 'scripts', 'build-usb-native.js')], {
    cwd: rootDir,
    stdio: 'inherit',
  })
  if (usbBuild.status !== 0) {
    console.error('[backend-build] USB 原生依赖构建失败')
    process.exit(usbBuild.status || 1)
  }
  if (!fs.existsSync(path.join(usbNativeDir, 'manifest.json'))) {
    console.error(`[backend-build] 缺少 USB 原生依赖清单: ${usbNativeDir}`)
    process.exit(1)
  }
} else {
  console.log('[backend-build] 当前平台不包含 USB 原生依赖')
}

console.log('[backend-build] 开始构建 PyInstaller 后端运行时...')

const result = spawnSync(
  python,
  [
    '-m',
    'PyInstaller',
    specFile,
    '--noconfirm',
    '--clean',
    '--distpath',
    buildDir,
    '--workpath',
    workDir,
  ],
  {
    cwd: rootDir,
    stdio: 'inherit',
    env: {
      ...process.env,
      PYTHONHASHSEED: '0',
      ...(process.platform === 'darwin' ? { MACOSX_DEPLOYMENT_TARGET: MINIMUM_MACOS_VERSION } : {}),
    },
  },
)

if (result.error) {
  console.error(`[backend-build] 无法启动 Python: ${result.error.message}`)
  console.error('[backend-build] 请先在目标平台的 backend/.venv 中安装 PyInstaller。')
  process.exit(1)
}
if (result.status !== 0) {
  process.exit(result.status || 1)
}

const executable = path.join(
  runtimeDir,
  process.platform === 'win32' ? 'toolbox-backend.exe' : 'toolbox-backend',
)
if (!fs.existsSync(executable) || fs.statSync(executable).size === 0) {
  console.error(`[backend-build] 未生成后端可执行文件: ${executable}`)
  process.exit(1)
}

console.log(`[backend-build] 后端运行时已生成: ${runtimeDir}`)
console.log(`[backend-build] 可执行文件大小: ${(fs.statSync(executable).size / 1024 / 1024).toFixed(1)} MB`)
