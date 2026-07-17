// frontend/src/main.js
// 应用入口：注册 Vue 插件，挂载应用
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { ElButton, ElForm, ElFormItem, ElIcon, ElInput } from 'element-plus'
import 'element-plus/es/components/button/style/css'
import 'element-plus/es/components/form/style/css'
import 'element-plus/es/components/form-item/style/css'
import 'element-plus/es/components/icon/style/css'
import 'element-plus/es/components/input/style/css'
import App from './App.vue'
import router from './router/index.js'
import './styles/global.css'
import { registerIcons } from './plugins/icons.js'
import { useAuthStore } from '@/stores/auth.js'

const app = createApp(App)

registerIcons(app)

for (const component of [ElButton, ElForm, ElFormItem, ElIcon, ElInput]) {
  app.component(component.name, component)
}

// Pinia：全局状态管理
const pinia = createPinia()
app.use(pinia)

// Vue Router：页面路由
app.use(router)

async function bootstrap() {
  const authStore = useAuthStore()
  if (authStore.refreshToken) {
    await authStore.ensureSession()
  }
  app.mount('#app')
}

bootstrap()
