/**
 * macOS 免签名更新安装 helper（纯 Node 脚本，零第三方依赖）。
 *
 * 由主进程通过 `ELECTRON_RUN_AS_NODE=1` 以当前应用自带的 Electron 二进制
 * 启动，随应用经 extraResources 打包到 Resources/update-helper.js。
 *
 * 职责：等待主进程退出 → 校验 ZIP 条目无路径逃逸 → ditto 解压 →
 * 校验应用 BundleId 与版本 → 移除 quarantine → 原子替换（必要时弹
 * 管理员授权）→ 失败回滚 → 写入结果文件 → 重启应用。
 */
import * as crypto from 'crypto'
import * as fs from 'fs'
import * as path from 'path'
import { spawnSync } from 'child_process'

interface HelperArgs {
  zip: string
  target: string
  version: string
  result: string
  waitPid: number
  noRelaunch: boolean
}

const BUNDLE_ID = 'com.toolbox.app'

function parseArgs(argv: string[]): HelperArgs {
  const args: HelperArgs = {
    zip: '',
    target: '',
    version: '',
    result: '',
    waitPid: 0,
    noRelaunch: false,
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
      case '--no-relaunch': args.noRelaunch = true; break
      default: break
    }
  }
  return args
}

/** 读取 ZIP 中央目录中的全部条目名，用于路径逃逸校验 */
function listZipEntryNames(zipPath: string): string[] {
  const fd = fs.openSync(zipPath, 'r')
  try {
    const size = fs.fstatSync(fd).size
    const tailLen = Math.min(size, 22 + 65535)
    const tail = Buffer.alloc(tailLen)
    fs.readSync(fd, tail, 0, tailLen, size - tailLen)

    let eocdRel = -1
    for (let i = tailLen - 22; i >= 0; i--) {
      if (tail.readUInt32LE(i) === 0x06054b50) {
        eocdRel = i
        break
      }
    }
    if (eocdRel < 0) throw new Error('ZIP 中央目录损坏')

    const entryCount = tail.readUInt16LE(eocdRel + 10)
    let cdOffset = tail.readUInt32LE(eocdRel + 16)
    let cdSize = tail.readUInt32LE(eocdRel + 12)

    if (cdOffset === 0xffffffff || cdSize === 0xffffffff) {
      const locRel = eocdRel - 20
      if (locRel < 0 || tail.readUInt32LE(locRel) !== 0x07064b50) {
        throw new Error('不支持的 ZIP64 中央目录')
      }
      const z64Abs = Number(tail.readBigUInt64LE(locRel + 8))
      const z64 = Buffer.alloc(56)
      fs.readSync(fd, z64, 0, 56, z64Abs)
      cdOffset = Number(z64.readBigUInt64LE(48))
      cdSize = Number(z64.readBigUInt64LE(40))
    }

    const cd = Buffer.alloc(cdSize)
    fs.readSync(fd, cd, 0, cdSize, cdOffset)

    const names: string[] = []
    let pos = 0
    for (let i = 0; i < entryCount; i++) {
      if (cd.readUInt32LE(pos) !== 0x02014b50) {
        throw new Error('ZIP 中央目录条目损坏')
      }
      const nameLen = cd.readUInt16LE(pos + 28)
      const extraLen = cd.readUInt16LE(pos + 30)
      const commentLen = cd.readUInt16LE(pos + 32)
      names.push(cd.toString('utf8', pos + 46, pos + 46 + nameLen))
      pos += 46 + nameLen + extraLen + commentLen
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

function run(cmd: string, args: string[]): { status: number; stdout: string; stderr: string } {
  const result = spawnSync(cmd, args, { encoding: 'utf8' })
  return {
    status: result.status ?? -1,
    stdout: result.stdout || '',
    stderr: result.stderr || '',
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

function main() {
  const args = parseArgs(process.argv.slice(2))
  if (!args.zip || !args.target || !args.version || !args.result) {
    console.error('[update-helper] 缺少必要参数: --zip --target --version --result')
    return 2
  }

  const updateDir = path.dirname(args.zip)
  const stageDir = path.join(updateDir, `stage-${args.version}`)
  const backupDir = path.join(updateDir, `backup-${args.version}`)
  const zipName = path.basename(args.zip)

  try {
    // 1. 等待主进程退出（waitPid=0 表示跳过，用于测试）
    if (args.waitPid > 0 && !waitForPidExit(args.waitPid, 120000)) {
      return fail(args, '等待应用退出超时')
    }

    // 2. 校验下载包
    if (!fs.existsSync(args.zip)) {
      return fail(args, `更新包不存在: ${zipName}`)
    }
    assertNoZipTraversal(args.zip)

    // 3. 解压到暂存目录
    fs.rmSync(stageDir, { recursive: true, force: true })
    fs.mkdirSync(stageDir, { recursive: true })
    const ditto = run('/usr/bin/ditto', ['-x', '-k', args.zip, stageDir])
    if (ditto.status !== 0) {
      return fail(args, `解压失败: ${ditto.stderr.trim() || ditto.stdout.trim()}`)
    }

    // 4. 定位解压出的 .app
    const appNames = fs.readdirSync(stageDir).filter((name) => name.endsWith('.app'))
    if (appNames.length !== 1) {
      return fail(args, `解压结果中的 .app 数量异常（${appNames.length}），已拒绝安装`)
    }
    const newApp = path.join(stageDir, appNames[0])

    // 5. 校验应用标识与版本
    assertValidApp(newApp, args.version)

    // 6. 移除 quarantine，避免未签名应用被 Gatekeeper 拦截
    run('/usr/bin/xattr', ['-dr', 'com.apple.quarantine', newApp])

    // 7. 原子替换（含失败回滚）
    const error = runReplaceScript(args.target, newApp, backupDir, BUNDLE_ID, args.version)
    if (error) {
      return fail(args, `安装失败: ${error}`)
    }

    // 8. 记录成功结果
    writeResultFile(args.result, {
      state: 'success',
      version: args.version,
      message: `已安装 ${args.version}`,
      timestamp: new Date().toISOString(),
    })

    // 9. 重启应用
    if (!args.noRelaunch) {
      const relaunch = run('/usr/bin/open', [args.target])
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
  }
}

process.exit(main())
