/**
 * Vite 构建配置。
 *
 * 使用 Vue 插件编译单文件组件；base 设置为相对路径，保证打包后的 dist
 * 能被 Capacitor Android WebView 从本地资源目录正确加载。
 */
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  base: './',
})
