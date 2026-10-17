/**
 * macOS arm64 USB 原生依赖构建：固定来源与摘要、隔离构建、重定位依赖并准备分发材料。
 *
 * 只产出 build/usb-native/dist（库、许可、构建记录、对应源码包），由
 * scripts/build-backend-runtime.js 和 backend/packaging/backend.spec 消费。
 * 不安装系统组件、不读取用户机器上的 Homebrew 库、不签名应用包本身。
 */
const fs = require('fs')
const path = require('path')
const os = require('os')
const https = require('https')
const crypto = require('crypto')
const { spawnSync } = require('child_process')

const rootDir = path.resolve(__dirname, '..')
const sourcesFile = path.join(rootDir, 'backend', 'packaging', 'usb-native-sources.json')
const workDir = path.join(rootDir, 'build', 'usb-native')
const distDir = path.join(workDir, 'dist')
const downloadDir = path.join(workDir, 'downloads')
const sourceDir = path.join(workDir, 'src')
const prefixDir = path.join(workDir, 'prefix')
const libDistDir = path.join(distDir, 'lib')
const licenseDistDir = path.join(distDir, 'licenses')

/** 只允许 HTTPS，跟随有限次重定向，流式落盘避免整包进内存。 */
function download(url, target, redirects = 0) {
  return new Promise((resolve, reject) => {
    if (!url.startsWith('https://')) {
      reject(new Error(`拒绝非 HTTPS 来源: ${url}`))
      return
    }
    const request = https.get(url, { headers: { 'User-Agent': 'toolbox-usb-native-build' } }, (response) => {
      const status = response.statusCode || 0
      if (status >= 300 && status < 400 && response.headers.location) {
        response.resume()
        if (redirects >= 5) {
          reject(new Error(`重定向次数过多: ${url}`))
          return
        }
        download(new URL(response.headers.location, url).toString(), target, redirects + 1).then(resolve, reject)
        return
      }
      if (status !== 200) {
        response.resume()
        reject(new Error(`下载失败 ${status}: ${url}`))
        return
      }
      const output = fs.createWriteStream(target)
      response.pipe(output)
      output.on('finish', () => output.close(() => resolve()))
      output.on('error', reject)
    })
    request.on('error', reject)
    request.setTimeout(60000, () => request.destroy(new Error(`下载超时: ${url}`)))
  })
}

function sha256(file) {
  const hash = crypto.createHash('sha256')
  hash.update(fs.readFileSync(file))
  return hash.digest('hex')
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, { stdio: 'inherit', cwd: rootDir, ...options })
  if (result.error) throw new Error(`无法执行 ${command}: ${result.error.message}`)
  if (result.status !== 0) throw new Error(`${command} 退出码 ${result.status}`)
}

function output(command, args) {
  const result = spawnSync(command, args, { encoding: 'utf8' })
  if (result.status !== 0) throw new Error(`${command} 失败: ${result.stderr || result.status}`)
  return result.stdout
}

function extract(archive, target) {
  fs.mkdirSync(target, { recursive: true })
  run('tar', ['-xf', archive, '-C', target, '--strip-components=1'])
}

/** 上游共享库名带 soname 版本；只接受唯一的普通文件，避免误取符号链接。 */
function findDylib(directory, pattern) {
  const matches = fs.readdirSync(directory)
    .filter((name) => pattern.test(name))
    .map((name) => path.join(directory, name))
    .filter((full) => fs.lstatSync(full).isFile())
  if (matches.length !== 1) {
    throw new Error(`预期唯一的共享库，实际 ${matches.length} 个: ${pattern}`)
  }
  return matches[0]
}

function buildLibrary(entry, previousPrefixes) {
  const archive = path.join(downloadDir, path.basename(new URL(entry.url).pathname))
  const source = path.join(sourceDir, entry.name)
  const prefix = path.join(prefixDir, entry.name)
  extract(archive, source)
  const pkgConfigPath = previousPrefixes
    .map((item) => path.join(item, 'lib', 'pkgconfig'))
    .filter((item) => fs.existsSync(item))
  const environment = {
    ...process.env,
    CFLAGS: '-mmacosx-version-min=14.0 -O2',
    LDFLAGS: '-mmacosx-version-min=14.0',
    PKG_CONFIG_PATH: pkgConfigPath.join(path.delimiter),
  }
  run('./configure', [`--prefix=${prefix}`, ...entry.configureArgs], { cwd: source, env: environment })
  run('make', ['-j', String(Math.max(1, os.cpus().length))], { cwd: source, env: environment })
  run('make', ['install'], { cwd: source, env: environment })
  return { source, prefix, environment }
}

/** 只允许包内相对引用和系统库；出现其他绝对路径就中止，避免绑定构建机。 */
function relocate(bundledPath, allowedPrefixes) {
  const dependencies = output('otool', ['-L', bundledPath])
    .split('\n')
    .slice(1)
    .map((line) => line.trim().split(' (')[0])
    .filter(Boolean)
  for (const dependency of dependencies) {
    const local = allowedPrefixes.find((prefix) => dependency.startsWith(prefix))
    if (local) {
      const replacement = `@loader_path/${path.basename(dependency)}`
      run('install_name_tool', ['-change', dependency, replacement, bundledPath])
      continue
    }
    const system = dependency.startsWith('/usr/lib/') || dependency.startsWith('/System/')
    if (!system && !dependency.startsWith('@loader_path/') && !dependency.startsWith('@rpath/')) {
      throw new Error(`存在非系统绝对依赖，拒绝分发: ${dependency}`)
    }
  }
}

function verifyRelocated(bundledPath) {
  const dependencies = output('otool', ['-L', bundledPath])
    .split('\n')
    .slice(1)
    .map((line) => line.trim().split(' (')[0])
    .filter(Boolean)
  const unexpected = dependencies.filter((item) => !item.startsWith('@loader_path/')
    && !item.startsWith('/usr/lib/') && !item.startsWith('/System/'))
  if (unexpected.length) {
    throw new Error(`重定位后仍存在可疑依赖: ${unexpected.join(', ')}`)
  }
}

async function main() {
  if (process.platform !== 'darwin') {
    throw new Error('USB 原生依赖只在 macOS 上构建')
  }
  if (process.arch !== 'arm64') {
    throw new Error(`只支持 arm64 构建，当前为 ${process.arch}`)
  }
  const config = JSON.parse(fs.readFileSync(sourcesFile, 'utf8'))
  if (config.platform !== 'darwin' || config.arch !== 'arm64' || config.mtpz !== false) {
    throw new Error('来源配置与目标平台或 MTPZ 策略不符')
  }

  fs.rmSync(workDir, { recursive: true, force: true })
  for (const directory of [downloadDir, sourceDir, prefixDir, libDistDir, licenseDistDir]) {
    fs.mkdirSync(directory, { recursive: true })
  }

  const archives = []
  for (const entry of config.libraries) {
    const archive = path.join(downloadDir, path.basename(new URL(entry.url).pathname))
    console.log(`[usb-native] 下载 ${entry.name} ${entry.version}`)
    await download(entry.url, archive)
    const actual = sha256(archive)
    if (actual !== entry.sha256) {
      throw new Error(`${entry.name} 摘要不匹配: 期望 ${entry.sha256}，实际 ${actual}`)
    }
    archives.push(archive)
  }

  const prefixes = []
  const bundled = []
  for (const entry of config.libraries) {
    console.log(`[usb-native] 构建 ${entry.name} ${entry.version}`)
    const built = buildLibrary(entry, [...prefixes])
    prefixes.push(built.prefix)
    const produced = findDylib(path.join(built.prefix, 'lib'), new RegExp(`^${entry.name}.*\\.dylib$`))
    const name = entry.bundledName || path.basename(produced)
    const target = path.join(libDistDir, name)
    fs.copyFileSync(produced, target)
    fs.chmodSync(target, 0o755)
    relocate(target, prefixes.map((prefix) => path.join(prefix, 'lib')))
    run('install_name_tool', ['-id', `@loader_path/${name}`, target])
    verifyRelocated(target)
    // 重写头部会破坏原签名；按 PyInstaller 的同类做法重新做 ad-hoc 签名。
    run('codesign', ['--force', '--sign', '-', target])
    const license = ['COPYING', 'COPYING.LIB', 'LICENSE'].map((item) => path.join(built.source, item))
      .find((item) => fs.existsSync(item))
    if (!license) {
      throw new Error(`${entry.name} 缺少许可文本，不能完成分发准备`)
    }
    const licenseName = `${entry.name}-${path.basename(license)}.txt`
    fs.copyFileSync(license, path.join(licenseDistDir, licenseName))
    bundled.push({
      name: entry.name,
      version: entry.version,
      file: name,
      sha256: sha256(target),
      license: `licenses/${licenseName}`,
      configureArgs: entry.configureArgs,
      sourceUrl: entry.url,
      sourceSha256: entry.sha256,
      digestSource: entry.digestSource,
    })
  }

  const notices = path.join(rootDir, 'backend', 'packaging', 'usb-notices.txt')
  fs.copyFileSync(notices, path.join(distDir, 'NOTICE.txt'))

  const buildInfo = {
    platform: config.platform,
    arch: config.arch,
    minimumMacosVersion: config.minimumMacosVersion,
    mtpz: config.mtpz,
    builtAt: new Date().toISOString(),
    libraries: bundled,
  }
  fs.writeFileSync(path.join(distDir, 'build-info.json'), `${JSON.stringify(buildInfo, null, 2)}\n`)
  fs.writeFileSync(path.join(distDir, 'manifest.json'), `${JSON.stringify({
    libraries: bundled.map((item) => ({ file: item.file, name: item.name, version: item.version, license: item.license })),
    notice: 'NOTICE.txt',
    buildInfo: 'build-info.json',
  }, null, 2)}\n`)

  // 对应源码随发布资产分发；不在应用包内重复存放源码。
  run('tar', [
    '-czf', path.join(distDir, 'usb-sources.tar.gz'),
    '-C', downloadDir, ...archives.map((item) => path.basename(item)),
    '-C', distDir, 'build-info.json',
  ])

  console.log(`[usb-native] 完成: ${distDir}`)
  for (const item of bundled) {
    console.log(`[usb-native] ${item.file} sha256=${item.sha256}`)
  }
}

main().catch((error) => {
  console.error(`[usb-native] 构建失败: ${error.message}`)
  process.exit(1)
})
