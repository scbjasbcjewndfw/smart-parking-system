/**
 * axios 实例：统一基址、超时、鉴权与 401 处理。
 *
 * 基址策略
 * --------
 * 默认 ``/api``，由 Vite 开发代理或 Nginx 转发到后端，避免把
 * ``http://127.0.0.1:5000`` 写死进打包产物（部署到服务器后必然失效）。
 * 需要直连后端时设置环境变量 ``VITE_API_BASE_URL``。
 */
import axios from 'axios'

const baseURL = import.meta.env.VITE_API_BASE_URL || '/api'

const request = axios.create({
  baseURL,
  // 识别接口要跑 YOLO + OCR，首次调用还要加载模型，5 秒会误判为超时
  timeout: 60000,
})

// 请求拦截器：自动带 JWT token
request.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token')
    if (token) {
      config.headers['Authorization'] = 'Bearer ' + token
    }
    return config
  },
  (error) => Promise.reject(error),
)

// 响应拦截器：处理 401 未授权
request.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response && error.response.status === 401) {
      localStorage.removeItem('access_token')
      localStorage.removeItem('username')
      // 给页面发个事件通知，由页面提示"登录已过期"
      window.dispatchEvent(new CustomEvent('auth-expired'))
    }
    return Promise.reject(error)
  },
)

export default request
