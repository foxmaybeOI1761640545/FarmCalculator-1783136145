/**
 * Capacitor 应用配置。
 *
 * appId 对应 Android 包名，appName 是系统中显示的中文应用名，webDir 指向
 * Vite 生产构建输出目录 dist。
 */
import type { CapacitorConfig } from '@capacitor/cli'

const config: CapacitorConfig = {
  appId: 'com.farmcalculator.app',
  appName: '农场成熟时间计算器',
  webDir: 'dist',
}

export default config
