import { fileURLToPath, URL } from 'node:url'

import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import vueDevTools from 'vite-plugin-vue-devtools'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // 读 .env / .env.local，便于不同机器上覆盖端口与后端地址
  const env = loadEnv(mode, process.cwd(), '')

  // 默认 5174：本机 5173 常被其他前端项目占用，strictPort 下会直接启动失败
  const port = Number(env.VITE_PORT || process.env.VITE_PORT || 5174)
  const proxyTarget =
    env.VITE_PROXY_TARGET || process.env.VITE_PROXY_TARGET || 'http://127.0.0.1:5001'

  return {
    plugins: [vue(), vueDevTools()],
    resolve: {
      alias: {
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    server: {
      host: '127.0.0.1',
      port,
      // 端口被占用时直接报错，而不是悄悄换端口——
      // 否则浏览器访问的还是旧地址，问题极难定位
      strictPort: true,
      // 把 /api 转发到 Flask：前端只写相对路径，既不触发跨域预检，
      // 也不会把后端地址写死进打包产物
      proxy: {
        '/api': {
          target: proxyTarget,
          changeOrigin: true,
        },
      },
    },
    preview: {
      host: '127.0.0.1',
      port: port + 100,
      strictPort: true,
    },
  }
})
