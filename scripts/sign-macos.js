/**
 * macOS ad-hoc 签名钩子：按内部二进制到应用包的顺序显式签名。
 *
 * 不使用 Developer ID、不启用 hardened runtime、不请求时间戳，也不承诺
 * Gatekeeper 免提示；任一步失败都让构建失败，不静默跳过或降级。
 */
const fs = require('fs')
const path = require('path')
const { spawnSync } = require('child_process')

// 芯片厂商自行签名的内核扩展不参与本应用签名。
const SKIP_SUFFIXES = ['.kext']
// 常见 Mach-O magic：thin（大小端）与 fat（含 64 位）。
const MACHO_MAGIC = new Set([0xfeedface, 0xfeedfacf, 0xcefaedfe, 0xcffaedfe, 0xcafebabe, 0xbebafeca, 0xcafebabf])

function isMachO(file) {
  try {
    if (!fs.lstatSync(file).isFile()) return false
    const descriptor = fs.openSync(file, 'r')
    try {
      const header = Buffer.alloc(4)
      if (fs.readSync(descriptor, header, 0, 4, 0) < 4) return false
      return MACHO_MAGIC.has(header.readUInt32BE(0))
    } finally {
      fs.closeSync(descriptor)
    }
  } catch {
    return false
  }
}

function walk(directory, found = []) {
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const full = path.join(directory, entry.name)
    // 框架内部的 Current 等符号链接不单独签名，签名其真实目标即可。
    if (entry.isSymbolicLink()) continue
    if (entry.isDirectory()) walk(full, found)
    else if (isMachO(full)) found.push(full)
  }
  return found
}

function codesign(args, target) {
  const result = spawnSync('codesign', args, { encoding: 'utf8' })
  if (result.error) throw new Error(`无法执行 codesign: ${result.error.message}`)
  if (result.status !== 0) {
    throw new Error(`codesign 失败（${target}）: ${(result.stderr || result.stdout || '').trim()}`)
  }
}

module.exports = async function signApp(configuration) {
  if (process.platform !== 'darwin') throw new Error('macOS 签名钩子只能在 macOS 上运行')
  const appPath = configuration && configuration.app
  if (!appPath || !fs.existsSync(appPath)) {
    throw new Error(`未找到待签名的应用包: ${appPath || '未提供'}`)
  }

  const targets = walk(path.join(appPath, 'Contents'))
    .filter((file) => !SKIP_SUFFIXES.some((suffix) => file.endsWith(suffix)))
    // 先签最深层文件，外层容器随后覆盖，避免外层签名被内部改动作废。
    .sort((left, right) => right.split(path.sep).length - left.split(path.sep).length)
  for (const target of targets) {
    codesign(['--force', '--sign', '-', target], target)
  }
  codesign(['--force', '--sign', '-', appPath], appPath)

  // 只校验签名结构完整；ad-hoc 签名不代表发布者身份，也不代表公证。
  codesign(['--verify', '--deep', '--strict', appPath], appPath)
  console.log(`[sign-macos] 已对 ${targets.length + 1} 个 Mach-O 完成 ad-hoc 签名`)
  return true
}
