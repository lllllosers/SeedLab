import axios from 'axios'

export const api = axios.create({ baseURL: '/api', withCredentials: true })
let csrfToken = ''
export function setCsrfToken(value: string) {
  csrfToken = value
}
api.interceptors.request.use((config) => {
  if (csrfToken) config.headers['X-CSRF-Token'] = csrfToken
  return config
})

export function errorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (error.response?.status === 401) return '登录已失效，请重新登录'
    if (error.response?.status === 422) return '请检查填写内容'
  }
  return '操作失败，请稍后重试'
}
