import type { GerminationDishStatus } from '../index'

export function todayPendingDish(
  dish: Pick<GerminationDishStatus, 'sown_at' | 'cancelled_at' | 'today_observed'>,
): boolean {
  return !!dish.sown_at && !dish.cancelled_at && !dish.today_observed
}

export function observationPlanOverdue(endAt: string | null, now = Date.now()): boolean {
  return endAt !== null && new Date(endAt).getTime() < now
}

export function germinationText(value: number | null, percentage = false): string {
  return value === null ? '未记录' : `${value}${percentage ? '%' : ''}`
}
