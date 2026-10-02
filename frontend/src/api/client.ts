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
    if (Array.isArray(detail) && detail.length) {
      const field = String(detail[0]?.loc?.at(-1) || '')
      const labels: Record<string, string> = {
        experiment_type: '实验类型',
        seeds_per_dish: '每皿种子数',
        replicate_count: '重复数',
        observation_period_days: '观察周期',
        sample_count: '取样数',
        seeds_per_dish_override: '材料每皿种子数',
        replicate_count_override: '材料重复数',
        sample_count_override: '材料取样数',
        dag_days: 'DAG 时间点',
        germination_criterion: '发芽判定标准',
      }
      if (labels[field]) return `请检查${labels[field]}：需要填写符合要求的值`
    }
    if (error.response?.status === 401) return '登录已失效，请重新登录'
    if (error.response?.status === 422) return '请检查填写内容'
  }
  return '操作失败，请稍后重试'
}
