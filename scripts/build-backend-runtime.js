const fs = require('fs')
const path = require('path')
const { spawnSync } = require('child_process')

const rootDir = path.resolve(__dirname, '..')
const backendDir = path.join(rootDir, 'backend')
const buildDir = path.join(rootDir, 'build')
const runtimeDir = path.join(buildDir, 'backend-runtime')
const workDir = path.join(buildDir, 'backend-work')
const specFile = path.join(backendDir, 'packaging', 'backend.spec')

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
    env: { ...process.env, PYTHONHASHSEED: '0' },
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
