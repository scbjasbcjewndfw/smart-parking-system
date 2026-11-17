import './assets/main.css'

import { createApp } from 'vue'
import App from './App.vue'
import router from './router'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'

const app=createApp(App)
app.use(router).use(ElementPlus)

// 全量注册 Element Plus 图标组件,模板里 <upload-filled /> / <el-icon><upload-filled/></el-icon> 等可直接使用
for (const [key, component] of Object.entries(ElementPlusIconsVue)) {
  app.component(key, component)
}

app.mount('#app')
