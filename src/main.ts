/**
 * Vue 应用入口。
 *
 * 只负责加载全局样式、创建 App 根组件并挂载到 index.html 的 #app；
 * Capacitor 和浏览器构建都复用同一入口。
 */
import { createApp } from 'vue'
import './style.css'
import App from './App.vue'

createApp(App).mount('#app')
