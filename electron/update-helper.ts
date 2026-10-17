/**
 * macOS 免签名更新安装 helper（纯 Node 脚本，零第三方依赖）。
 *
 * 由主进程通过 `ELECTRON_RUN_AS_NODE=1` 以当前应用自带的 Electron 二进制
 * 启动，随应用经 extraResources 打包到 Resources/update-helper.js。
 *
 * 职责：应答启动 → 等待主进程退出 → 校验 ZIP 摘要与条目路径 → 由应用后端
 * 取得应用级所有权 → ditto 解压 → 校验 BundleId、版本与最低系统版本 →
 * 移除 quarantine → 顺序替换（失败尽力回滚）→ 写结果文件 → 重启应用。
 *
 * 摘要、BundleId 与移除 quarantine 都不构成发布者签名或公证保证；
 * 替换不是原子操作，中途崩溃可能留下 backup- 目录，需要人工处理。
 */
import * as crypto from 'crypto'
import * as fs from 'fs'
import * as path from 'path'
import { spawn, spawnSync, ChildProcess } from 'child_process'

interface HelperArgs {
  zip: string
  target: string
  version: string
  result: string
  waitPid: number
  noRelaunch: boolean
  sha512: string
  dataRoot: string
}

const BUNDLE_ID = 'com.toolbox.app'
const MINIMUM_MACOS_VERSION = '14.0'
const GUARD_TIMEOUT_MS = 240000
const MAX_ZIP_ENTRIES = 200000
const EOCD_SIGNATURE = 0x06054b50
const ZIP64_EOCD_SIGNATURE = 0x06064b50
const ZIP64_LOCATOR_SIGNATURE = 0x07064b50
const CENTRAL_HEADER_SIGNATURE = 0x02014b50

function parseArgs(argv: string[]): HelperArgs {
  const args: HelperArgs = {
    zip: '',
    target: '',
    version: '',
    result: '',
    waitPid: 0,
    noRelaunch: false,
    sha512: '',
    dataRoot: '',
  }
  for (let i = 0; i < argv.length; i++) {
    const key = argv[i]
    const value = argv[i + 1]
    switch (key) {
      case '--zip': args.zip = value; i++; break
      case '--target': args.target = value; i++; break
      case '--version': args.version = value; i++; break
      case '--result': args.result = value; i++; break
      case '--wait-pid': args.waitPid = Number(value); i++; break
      case '--sha512': args.sha512 = value; i++; break
      case '--data-root': args.dataRoot = value; i++; break
      case '--no-relaunch': args.noRelaunch = true; break
      default: break
    }
  }
  return args
}

function readAt(fd: number, length: number, position: number, totalSize: number): Buffer {
  if (length < 0 || position < 0 || position + length > totalSize) {
    throw new Error('ZIP 结构读取越界')
  }
  const buffer = Buffer.alloc(length)
  const read = fs.readSync(fd, buffer, 0, length, position)
  if (read !== length) throw new Error('ZIP 结构读取不完整')
  return buffer
}

/**
 * 读取 ZIP 中央目录中的全部条目名。
 * ZIP64 时以 ZIP64 结束记录中的总条目数为准，并校验目录边界。
 */
function listZipEntryNames(zipPath: string): string[] {
  const fd = fs.openSync(zipPath, 'r')
  try {
    const size = fs.fstatSync(fd).size
    const tailLen = Math.min(size, 22 + 65535)
    const tail = readAt(fd, tailLen, size - tailLen, size)

    let eocdRel = -1
    for (let i = tailLen - 22; i >= 0; i--) {
      if (tail.readUInt32LE(i) === EOCD_SIGNATURE) {
        eocdRel = i
        break
      }
    }
    if (eocdRel < 0) throw new Error('ZIP 中央目录损坏')

    let entryCount = tail.readUInt16LE(eocdRel + 10)
    let cdSize = tail.readUInt32LE(eocdRel + 12)
    let cdOffset = tail.readUInt32LE(eocdRel + 16)

    // 任一分量命中哨兵值都按 ZIP64 处理，不能只看偏移与大小。
    if (entryCount === 0xffff || cdSize === 0xffffffff || cdOffset === 0xffffffff) {
      const locatorRel = eocdRel - 20
      if (locatorRel < 0 || tail.readUInt32LE(locatorRel) !== ZIP64_LOCATOR_SIGNATURE) {
        throw new Error('不支持的 ZIP64 中央目录')
      }
      const zip64Offset = Number(tail.readBigUInt64LE(locatorRel + 8))
      if (!Number.isSafeInteger(zip64Offset)) throw new Error('ZIP64 偏移无法安全表示')
      const record = readAt(fd, 56, zip64Offset, size)
      if (record.readUInt32LE(0) !== ZIP64_EOCD_SIGNATURE) {
        throw new Error('ZIP64 结束记录损坏')
      }
      const totalEntries = Number(record.readBigUInt64LE(32))
      const size64 = Number(record.readBigUInt64LE(40))
      const offset64 = Number(record.readBigUInt64LE(48))
      if (![totalEntries, size64, offset64].every((item) => Number.isSafeInteger(item))) {
        throw new Error('ZIP64 数值无法安全表示')
      }
      entryCount = totalEntries
      cdSize = size64
      cdOffset = offset64
    }

    if (entryCount < 0 || entryCount > MAX_ZIP_ENTRIES) throw new Error('ZIP 条目数超出处理预算')
    if (cdOffset + cdSize > size) throw new Error('ZIP 中央目录超出文件范围')

    const cd = readAt(fd, cdSize, cdOffset, size)
    const names: string[] = []
    let pos = 0
    for (let i = 0; i < entryCount; i++) {
      if (pos + 46 > cd.length) throw new Error('ZIP 中央目录条目越界')
      if (cd.readUInt32LE(pos) !== CENTRAL_HEADER_SIGNATURE) {
        throw new Error('ZIP 中央目录条目损坏')
      }
      const nameLen = cd.readUInt16LE(pos + 28)
      const extraLen = cd.readUInt16LE(pos + 30)
      const commentLen = cd.readUInt16LE(pos + 32)
      const next = pos + 46 + nameLen + extraLen + commentLen
      if (next > cd.length) throw new Error('ZIP 中央目录条目长度越界')
      names.push(cd.toString('utf8', pos + 46, pos + 46 + nameLen))
      pos = next
    }
    return names
  } finally {
    fs.closeSync(fd)
  }
}

function isSafeEntryName(name: string): boolean {
  if (name.startsWith('/') || name.includes('\\') || /^[A-Za-z]:/.test(name)) {
    return false
  }
  return !name.split('/').some((segment) => segment === '..')
}

function assertNoZipTraversal(zipPath: string) {
  const names = listZipEntryNames(zipPath)
  const unsafe = names.find((name) => !isSafeEntryName(name))
  if (unsafe) {
    throw new Error(`ZIP 包含不安全条目，已拒绝安装: ${unsafe}`)
  }
}

/** 摘要缺失或格式不符时直接失败：不再降级为“仅 HTTPS 完整性”。 */
function verifySha512(zipPath: string, expected: string): void {
  if (!/^[A-Za-z0-9+/=]+$/.test(expected)) {
    throw new Error('缺少有效的更新包 SHA-512，已拒绝安装')
  }
  const hash = crypto.createHash('sha512')
  const fd = fs.openSync(zipPath, 'r')
  try {
    const chunk = Buffer.alloc(1024 * 1024)
    let position = 0
    while (true) {
      const read = fs.readSync(fd, chunk, 0, chunk.length, position)
      if (read <= 0) break
      hash.update(chunk.subarray(0, read))
      position += read
    }
  } finally {
    fs.closeSync(fd)
  }
  if (hash.digest('base64') !== expected) {
    throw new Error('更新包 SHA-512 校验失败，已拒绝安装')
  }
}

function run(cmd: string, args: string[]): { status: number; stdout: string; stderr: string } {
  const result = spawnSync(cmd, args, { encoding: 'utf8' })
  return {
    status: result.status ?? -1,
    stdout: result.stdout || '',
    stderr: result.stderr || '',
  }
}

function compareVersions(a: string, b: string): number {
  const parse = (value: string) => value.split('.').map((part) => {
    const num = parseInt(part, 10)
    return Number.isNaN(num) ? 0 : num
  })
  const va = parse(a)
  const vb = parse(b)
  for (let i = 0; i < Math.max(va.length, vb.length); i++) {
    const diff = (va[i] ?? 0) - (vb[i] ?? 0)
    if (diff !== 0) return diff
  }
  return 0
}

function assertMinimumSystem(): void {
  const result = run('/usr/bin/sw_vers', ['-productVersion'])
  const version = result.stdout.trim()
  if (result.status !== 0 || !version) {
    throw new Error('无法确认当前 macOS 版本')
  }
  if (compareVersions(version, MINIMUM_MACOS_VERSION) < 0) {
    throw new Error(`当前系统 ${version} 低于最低要求 ${MINIMUM_MACOS_VERSION}`)
  }
}

/** 读取 Info.plist 中指定键的值（字符串），失败返回 null */
function readPlistKey(appPath: string, key: string): string | null {
  const plist = path.join(appPath, 'Contents', 'Info.plist')
  if (!fs.existsSync(plist)) return null
  const result = run('/usr/libexec/PlistBuddy', ['-c', `Print :${key}`, plist])
  if (result.status !== 0) return null
  return result.stdout.trim()
}

function assertValidApp(appPath: string, expectedVersion: string) {
  if (!fs.existsSync(appPath) || !fs.statSync(appPath).isDirectory()) {
    throw new Error(`解压结果中未找到应用: ${appPath}`)
  }
  const bundleId = readPlistKey(appPath, 'CFBundleIdentifier')
  if (bundleId !== BUNDLE_ID) {
    throw new Error(`应用标识校验失败: 期望 ${BUNDLE_ID}，实际 ${bundleId ?? '未知'}`)
  }
  const version = readPlistKey(appPath, 'CFBundleShortVersionString')
  if (version !== expectedVersion) {
    throw new Error(`应用版本校验失败: 期望 ${expectedVersion}，实际 ${version ?? '未知'}`)
  }
  const macosDir = path.join(appPath, 'Contents', 'MacOS')
  const executable = fs.existsSync(macosDir)
    ? fs.readdirSync(macosDir).find((name) => !name.startsWith('.')) || ''
    : ''
  if (!executable) {
    throw new Error(`应用主可执行文件缺失: ${macosDir}`)
  }
}

function isProcessAlive(pid: number): boolean {
  try {
    process.kill(pid, 0)
    return true
  } catch (error) {
    return (error as NodeJS.ErrnoException).code !== 'ESRCH'
  }
}

function waitForPidExit(pid: number, timeoutMs: number): boolean {
  const deadline = Date.now() + timeoutMs
  while (Date.now() < deadline) {
    if (!isProcessAlive(pid)) {
      // 进程已退出；再等 2 秒让文件句柄释放
      sleepSync(2000)
      return !isProcessAlive(pid)
    }
    sleepSync(500)
  }
  return false
}

function sleepSync(ms: number) {
  const buffer = new SharedArrayBuffer(4)
  const view = new Int32Array(buffer)
  Atomics.wait(view, 0, 0, ms)
}

/**
 * 启动应用后端作为所有权守卫：它在取得应用锁后才应答就绪。
 * 这样替换期间不会出现另一个实例同时启动并争用设备与记录。
 */
function startGuard(appPath: string, dataRoot: string): ChildProcess {
  const executable = path.join(appPath, 'Contents', 'Resources', 'backend', 'toolbox-backend')
  if (!fs.existsSync(executable)) {
    throw new Error(`应用内未找到后端运行时: ${executable}`)
  }
  return spawn(executable, ['--toolbox-update-guard'], {
    stdio: ['pipe', 'pipe', 'pipe'],
    env: { ...process.env, TOOLBOX_DATA_DIR: dataRoot },
  })
}

function waitGuardReady(guard: ChildProcess, timeoutMs: number): Promise<void> {
  return new Promise((resolve, reject) => {
    let settled = false
    let buffered = ''
    const finish = (error?: Error) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      if (error) reject(error)
      else resolve()
    }
    const timer = setTimeout(() => finish(new Error('等待应用所有权超时')), timeoutMs)
    guard.stdout?.on('data', (chunk: Buffer) => {
      buffered += chunk.toString('utf8')
      if (buffered.includes('"ready"')) finish()
    })
    guard.stderr?.on('data', (chunk: Buffer) => {
      const text = chunk.toString('utf8').trim()
      if (text) console.error(`[update-helper][guard] ${text}`)
    })
    guard.on('error', (error) => finish(new Error(`应用所有权守卫启动失败: ${error.message}`)))
    guard.on('exit', (code) => finish(new Error(`应用所有权守卫提前退出（code=${code}）`)))
  })
}

function stopGuard(guard: ChildProcess | null) {
  if (!guard) return
  try {
    guard.stdin?.end()
    guard.kill()
  } catch {
    // 已退出
  }
}

/** 生成替换脚本：备份 → 替换 → 校验 → 失败回滚 → 清理备份 */
function buildReplaceScript(target: string, newApp: string, backup: string, bundleId: string, version: string): string {
  const q = (value: string) => `'${value.replace(/'/g, `'\\''`)}'`
  return [
    'set -e',
    `target=${q(target)}`,
    `newapp=${q(newApp)}`,
    `backup=${q(backup)}`,
    'if [ ! -d "$target" ]; then echo "目标应用不存在: $target"; exit 3; fi',
    'rm -rf "$backup"',
    'mv "$target" "$backup"',
    'if ! mv "$newapp" "$target"; then',
    '  mv "$backup" "$target" || true',
    '  echo "替换失败，已回滚"; exit 4',
    'fi',
    `if [ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$target/Contents/Info.plist" 2>/dev/null || true)" != "${bundleId}" ]; then`,
    '  rm -rf "$target"',
    '  mv "$backup" "$target"',
    '  echo "替换后标识校验失败，已回滚"; exit 5',
    'fi',
    `if [ "$(/usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$target/Contents/Info.plist" 2>/dev/null || true)" != "${version}" ]; then`,
    '  rm -rf "$target"',
    '  mv "$backup" "$target"',
    '  echo "替换后版本校验失败，已回滚"; exit 6',
    'fi',
    'rm -rf "$backup"',
    'echo "替换完成"',
    'exit 0',
  ].join('\n')
}

function runReplaceScript(target: string, newApp: string, backup: string, bundleId: string, version: string): string {
  const script = buildReplaceScript(target, newApp, backup, bundleId, version)
  const targetDir = path.dirname(target)
  let writable = false
  try {
    fs.accessSync(targetDir, fs.constants.W_OK)
    writable = true
  } catch {
    writable = false
  }

  if (writable) {
    const result = run('/bin/bash', ['-c', script])
    if (result.status !== 0) {
      return result.stderr.trim() || result.stdout.trim() || `替换失败（退出码 ${result.status}）`
    }
    return ''
  }

  // 目标目录不可写（如 /Applications）：以管理员权限执行同一脚本
  const osa = `do shell script ${JSON.stringify(script)} with administrator privileges`
  const result = run('/usr/bin/osascript', ['-e', osa])
  if (result.status !== 0) {
    return result.stderr.trim() || result.stdout.trim() || '管理员授权替换失败'
  }
  return ''
}

function writeResultFile(resultPath: string, payload: Record<string, unknown>) {
  const tmp = `${resultPath}.tmp`
  fs.writeFileSync(tmp, JSON.stringify(payload, null, 2))
  fs.renameSync(tmp, resultPath)
}

function fail(args: HelperArgs, message: string): number {
  console.error(`[update-helper] ${message}`)
  try {
    writeResultFile(args.result, {
      state: 'failed',
      version: args.version,
      message,
      timestamp: new Date().toISOString(),
    })
  } catch {
    // 结果文件写入失败不影响退出码
  }
  return 1
}

async function main(): Promise<number> {
  // 主进程等待该应答后才退出；缺少脚本参数时这里根本不会执行。
  process.stdout.write(`${JSON.stringify({ kind: 'started' })}\n`)

  const args = parseArgs(process.argv.slice(2))
  if (!args.zip || !args.target || !args.version || !args.result) {
    console.error('[update-helper] 缺少必要参数: --zip --target --version --result')
    return 2
  }

  const updateDir = path.dirname(args.zip)
  const stageDir = path.join(updateDir, `stage-${args.version}`)
  const backupDir = path.join(updateDir, `backup-${args.version}`)
  const zipName = path.basename(args.zip)
  let guard: ChildProcess | null = null

  try {
    // 1. 等待主进程退出（waitPid=0 表示跳过，用于测试）
    if (args.waitPid > 0 && !waitForPidExit(args.waitPid, 120000)) {
      return fail(args, '等待应用退出超时')
    }

    // 2. 校验下载包：摘要必须匹配，条目不得逃逸
    if (!fs.existsSync(args.zip)) {
      return fail(args, `更新包不存在: ${zipName}`)
    }
    assertMinimumSystem()
    verifySha512(args.zip, args.sha512)
    assertNoZipTraversal(args.zip)

    // 3. 取得应用所有权后才继续替换
    guard = startGuard(args.target, args.dataRoot)
    await waitGuardReady(guard, GUARD_TIMEOUT_MS)

    // 4. 解压到暂存目录
    fs.rmSync(stageDir, { recursive: true, force: true })
    fs.mkdirSync(stageDir, { recursive: true })
    const ditto = run('/usr/bin/ditto', ['-x', '-k', args.zip, stageDir])
    if (ditto.status !== 0) {
      return fail(args, `解压失败: ${ditto.stderr.trim() || ditto.stdout.trim()}`)
    }

    // 5. 定位解压出的 .app
    const appNames = fs.readdirSync(stageDir).filter((name) => name.endsWith('.app'))
    if (appNames.length !== 1) {
      return fail(args, `解压结果中的 .app 数量异常（${appNames.length}），已拒绝安装`)
    }
    const newApp = path.join(stageDir, appNames[0])

    // 6. 校验应用标识与版本
    assertValidApp(newApp, args.version)

    // 7. 移除 quarantine，避免未签名应用被 Gatekeeper 拦截（不代表发布者身份）
    run('/usr/bin/xattr', ['-dr', 'com.apple.quarantine', newApp])

    // 8. 顺序替换（非原子；失败尽力回滚）
    const error = runReplaceScript(args.target, newApp, backupDir, BUNDLE_ID, args.version)
    if (error) {
      return fail(args, `安装失败: ${error}`)
    }

    // 9. 记录成功结果
    writeResultFile(args.result, {
      state: 'success',
      version: args.version,
      message: `已安装 ${args.version}`,
      timestamp: new Date().toISOString(),
    })

    // 10. 重启应用，并显式传递数据根
    if (!args.noRelaunch) {
      const relaunchArgs = args.dataRoot
        ? ['-n', args.target, '--args', `--toolbox-data-dir=${args.dataRoot}`]
        : ['-n', args.target]
      const relaunch = run('/usr/bin/open', relaunchArgs)
      if (relaunch.status !== 0) {
        console.warn(`[update-helper] 重启应用失败（可手动打开）: ${relaunch.stderr.trim()}`)
      }
    }

    // 清理暂存目录
    fs.rmSync(stageDir, { recursive: true, force: true })
    return 0
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    return fail(args, `更新失败: ${message}`)
  } finally {
    stopGuard(guard)
  }
}

main().then((code) => process.exit(code))
