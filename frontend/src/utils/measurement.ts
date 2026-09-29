import type { MeasurementStatus, MeasurementTask } from '../types'

export const measurementStatusLabels: Record<MeasurementStatus, string> = {
  overdue: '已逾期', due_today: '今日待测', upcoming: '后续任务',
  completed: '已完成', unschedulable: '无法安排',
}

export function measurementValue(value: number | null, unavailable: boolean, completed: boolean): string {
  if (!completed) return '—'
  if (unavailable) return 'NA'
  return value === null ? '—' : String(value)
}

export function historyValue(task: MeasurementTask | undefined): string {
  if (!task?.measurement_id) return '—'
  return `${measurementValue(task.root_length_mm, task.root_unavailable, true)} / ${measurementValue(task.shoot_length_mm, task.shoot_unavailable, true)}`
}

export function isResolved(value: string, unavailable: boolean): boolean {
  if (unavailable) return value.trim() === ''
  if (value.trim() === '') return false
  const number = Number(value)
  return Number.isFinite(number) && number >= 0 && /^\d+(\.\d{1,2})?$/.test(value.trim())
}
