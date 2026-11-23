import axios from 'axios'
import { ElMessage } from 'element-plus'

const http = axios.create({ baseURL: '/api', timeout: 30000 })

http.interceptors.request.use((cfg) => {
  const token = localStorage.getItem('erp_token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  // 写接口幂等键，避免双击重复建单
  if (['post', 'put', 'patch', 'delete'].includes(cfg.method)) {
    cfg.headers['Idempotency-Key'] = `${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
  }
  return cfg
})

http.interceptors.response.use(
  (res) => res.data,
  (error) => {
    const status = error.response?.status
    const detail = error.response?.data?.detail
    // 附录 D.4：错误提示必须可读中文 + 明确原因
    const msg = detail || (status === 401 ? '登录已失效，请重新登录'
      : status === 403 ? '没有权限执行此操作'
      : status === 404 ? '请求的资源不存在'
      : status >= 500 ? '服务端处理失败，请查看后台日志' : '请求失败，请检查网络或参数')
    if (status === 401 && !location.hash.includes('/login')) {
      localStorage.removeItem('erp_token')
      localStorage.removeItem('erp_user')
    }
    ElMessage.error(msg)
    return Promise.reject(new Error(msg))
  }
)

export const get = (url, params) => http.get(url, { params })
export const post = (url, data) => http.post(url, data)
export const put = (url, data) => http.put(url, data)
export const del = (url, params) => http.delete(url, { params })
export const download = (url, params) => http.get(url, { params, responseType: 'blob' }).then((blob) => {
  const a = document.createElement('a')
  const href = URL.createObjectURL(blob)
  a.href = href
  a.download = (params?.filename || 'export') + (url.includes('pdf') ? '.pdf' : '.xlsx')
  document.body.appendChild(a); a.click(); a.remove()
  setTimeout(() => URL.revokeObjectURL(href), 2000)
})
export default http
