/**
 * 发布版本一致性检查脚本。
 *
 * 校验 package.json 与 package-lock.json 的版本完全一致，并强制版本号使用 X.0.Y
 * 形式；Android versionCode 按 major * 1_000_000 + patch 派生，确保在有符号
 * 32 位整型范围内；当 CI 传入 RELEASE_TAG 时，还会验证 tag 必须为 vX.0.Y
 * 且与 package.json version 对齐。
 */
import { readFile } from 'node:fs/promises'

// 版本格式约束：仓库发布流程只允许中间版本段固定为 0，便于生成 Android versionCode。
const versionPattern = /^[0-9]+\.0\.[0-9]+$/
const tagPattern = /^v[0-9]+\.0\.[0-9]+$/
const maxAndroidInt = 2147483647

/**
 * 输出版本校验失败原因并以非零状态结束进程。
 *
 * @param message 面向维护者的失败详情，通常包含实际版本值或不一致的字段。
 */
function fail(message) {
  console.error(`version verification failed: ${message}`)
  process.exit(1)
}

// 锁文件一致性检查：防止只修改 package.json 而忘记同步 package-lock.json。
const packageJson = JSON.parse(await readFile('package.json', 'utf8'))
const packageLock = JSON.parse(await readFile('package-lock.json', 'utf8'))
const version = packageJson.version

if (!versionPattern.test(version)) fail(`package.json version must match X.0.Y, actual: ${version}`)
if (packageLock.version !== version) fail(`package-lock.json top-level version mismatch: ${packageLock.version} !== ${version}`)
if (packageLock.packages?.['']?.version !== version) fail(`package-lock packages[""].version mismatch: ${packageLock.packages?.['']?.version} !== ${version}`)

// Android versionCode 计算：只使用主版本和补丁号，保持递增且不超过 Android int 上限。
const [major, , patch] = version.split('.').map(Number)
const versionCode = major * 1000000 + patch
if (!Number.isSafeInteger(versionCode) || versionCode <= 0 || versionCode > maxAndroidInt) fail(`versionCode out of Android int range: ${versionCode}`)

// RELEASE_TAG 校验：发布工作流传入 tag 时必须与包版本一一对应。
const releaseTag = process.env.RELEASE_TAG
if (releaseTag) {
  if (!tagPattern.test(releaseTag)) fail(`RELEASE_TAG must match vX.0.Y, actual: ${releaseTag}`)
  if (releaseTag.slice(1) !== version) fail(`RELEASE_TAG ${releaseTag} does not match package.json version ${version}`)
}

console.log(`version=${version}`)
console.log(`android_version_code=${versionCode}`)
