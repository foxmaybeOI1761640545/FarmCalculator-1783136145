# 农场成熟时间计算器 / FarmCalculator

农场成熟时间计算器是一个 Vue 3 + Vite + TypeScript + Capacitor Android 应用，用于根据作物类型、成熟剩余时间或具体成熟时间、水分剩余时间，计算浇水后的理论最快成熟时间。

## 功能

- 支持 8 小时、16 小时、32 小时作物。
- 支持倒计时输入模式与具体时间输入模式。
- 支持今日/明日判断、32 小时作物手动选择日期。
- 计算当前水分剩余时间、浇水减少成熟时间、理论最快成熟时间、预计最快成熟日期和时间。
- 保留中文提示、输入校验、localStorage 保存时间输入模式、清空输入、回车计算、输入框自动跳转、方向键切换、连续退格清空和移动端结果滚动。

## 技术栈与固定版本

- Vue 3.5.39
- Vite 8.1.0
- TypeScript 6.0.3
- vue-tsc 3.3.5
- Capacitor Core/CLI/Android 7.6.7
- Capacitor App 7.1.2
- Android Gradle Plugin 8.7.2
- Gradle 8.11.1
- Node.js 20
- JDK 21
- Android compileSdk/targetSdk 35，minSdk 23

## 常用命令

```bash
npm ci
npm run dev
npm run typecheck
npm run build
npm run sync:android
npm run android:debug
npm run android:release
npm run android:bundle
npm run verify:version
```

## Android 配置

- applicationId: `com.farmcalculator.app`
- namespace: `com.farmcalculator.app`
- 主 Activity: `android/app/src/main/java/com/farmcalculator/app/MainActivity.java`
- Web 资源打包进 App，不配置远程服务器 URL，离线可打开计算器。
- 图标与启动页只使用 XML 矢量、shape、adaptive icon 资源；不提交 PNG Android 图标。

## 版本规则

`package.json` 的 `version` 是唯一事实来源。版本格式固定为 `X.0.Y`，Git Tag 固定为 `vX.0.Y`。

Android `versionCode` 计算规则：

```text
versionCode = 主版本号 × 1000000 + 修订版本号
```

例如：`1.0.0 => 1000000`，`1.0.1 => 1000001`，`2.0.8 => 2000008`。

## 正式签名

正式 APK 和 AAB 必须使用固定正式密钥。Debug APK 不使用正式签名；Release APK 和 AAB 使用同一正式密钥。

在仓库外创建并永久安全备份 JKS，例如：

```bash
keytool -genkeypair \
  -v \
  -keystore farm-calculator-release.jks \
  -alias farm-calculator \
  -keyalg RSA \
  -keysize 2048 \
  -validity 10000
```

JKS 不得提交到 Git，密码不得写入仓库。丢失 JKS 或密码后，将无法继续为相同 applicationId 发布可覆盖安装的更新。

转换为 Base64 时仅在本机执行，并将结果写入 GitHub Secrets，不要写入仓库文件：

```bash
base64 -w 0 farm-calculator-release.jks
```

GitHub Secrets 必须配置：

- `ANDROID_KEYSTORE_BASE64`
- `ANDROID_KEYSTORE_PASSWORD`
- `ANDROID_KEY_ALIAS`
- `ANDROID_KEY_PASSWORD`

本地 Release 构建需要环境变量：

- `ANDROID_KEYSTORE_PATH`
- `ANDROID_KEYSTORE_PASSWORD`
- `ANDROID_KEY_ALIAS`
- `ANDROID_KEY_PASSWORD`

缺少任意 Release 签名变量时 Release 构建会立即失败，不生成 fallback keystore。

## CI/CD

Debug 工作流执行 `npm ci`、类型检查、版本校验、Capacitor 同步和 `gradle assembleDebug`，上传 Debug APK artifact，不读取签名 Secrets。

Release 工作流只响应 `vX.0.Y` Tag 或手动指定已有 Tag。流程为：检出 Tag、安装依赖、校验版本与 Tag、同步 Android、检查四个签名 Secret、解码 JKS 到 Runner 临时目录、构建 signed APK/AAB、验证签名、重命名为 `FarmCalculator-vX.0.Y.apk` 和 `FarmCalculator-vX.0.Y.aab`、上传 artifact 并创建/更新同名 GitHub Release。

推荐发布顺序：

```text
1. 获取远端 Tags
2. 运行 prepare-next-version.ps1
3. 检查 package.json 和 package-lock.json
4. 运行 npm run verify:version
5. 创建符合仓库模板的提交
6. 推送 main
7. 创建与 package.json 一致的 vX.0.Y Tag
8. 推送 Tag
9. 等待 Android Signed Release 工作流
```

## 仓库二进制规则

构建产物不进入 Git。不得修改、删除、复制或新增二进制文件；`public/favicon.png` 必须保持不变。不得提交 APK、AAB、JKS、Keystore、JAR、PNG Android 资源或 Gradle wrapper jar。
