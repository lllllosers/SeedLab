import type { MeasurementStatus, MeasurementTask } from '../index'

export const measurementStatusLabels: Record<MeasurementStatus, string> = {
  overdue: '已逾期',
  due_today: '今日待测',
  upcoming: '后续任务',
  completed: '已完成',
  unschedulable: '无法安排',
}

export function measurementValue(
  value: number | null,
  unavailable: boolean,
  completed: boolean,
): string {
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

export interface MeasurementForm {
  root: string
  shoot: string
  rootNA: boolean
  shootNA: boolean
  measuredAt: string
  notes: string
}
export function updateMeasurementPayload(form: MeasurementForm) {
  if (!isResolved(form.root, form.rootNA) || !isResolved(form.shoot, form.shootNA))
    throw new Error('根长和苗长都需要填写非负数值，或勾选“无法测量”；空白不能当作 0。')
  const time = new Date(form.measuredAt)
  if (Number.isNaN(time.getTime())) throw new Error('请填写有效的实际测定时间。')
  return {
    root_length_mm: form.rootNA ? null : Number(form.root),
    shoot_length_mm: form.shootNA ? null : Number(form.shoot),
    root_unavailable: form.rootNA,
    shoot_unavailable: form.shootNA,
    measured_at: time.toISOString(),
    notes: form.notes.trim() || null,
  }
}
export function createMeasurementPayload(
  task: Pick<MeasurementTask, 'sample_id' | 'timepoint_id'>,
  form: MeasurementForm,
) {
  return {
    sample_id: task.sample_id,
    timepoint_id: task.timepoint_id,
    ...updateMeasurementPayload(form),
  }
}
export async function focusNextRoot(nextTick: () => Promise<unknown>, focus: () => void) {
  await nextTick()
  focus()
}
export function nextPendingTask(tasks: MeasurementTask[], dag: number | null = null) {
  return (
    tasks.find(
      (task) =>
        ['overdue', 'due_today'].includes(task.status) &&
        (dag === null || task.day_after_germination === dag),
    ) || null
  )
}
export function taskSearchMatches(task: MeasurementTask, search: string) {
  const term = search.trim().toLocaleLowerCase().replace(/\s+/g, '')
  return (
    !term ||
    [
      task.experiment_number,
      task.field_number,
      task.sample_display_number,
      task.taxon_common_name,
      task.taxon_scientific_name,
      `幼苗${String(task.sample_number).padStart(2, '0')}`,
      task.position_label,
    ].some((value) =>
      String(value ?? '')
        .toLocaleLowerCase()
        .replace(/\s+/g, '')
        .includes(term),
    )
  )
}

/** Keep each seedling's configured days together within its actual dish. */
export function materialProgressTasks(tasks: MeasurementTask[]): MeasurementTask[] {
  return [...tasks].sort(
    (a, b) =>
      (a.field_number || '').localeCompare(b.field_number || '', 'en', { numeric: true }) ||
      a.replicate_no - b.replicate_no ||
      a.sample_number - b.sample_number ||
      a.day_after_germination - b.day_after_germination ||
      a.sample_id.localeCompare(b.sample_id),
  )
}
export const measurementProgressLabels: Record<MeasurementStatus, string> = {
  ...measurementStatusLabels,
  completed: '已测',
}
export const measurementProgressTagTypes = {
  completed: 'success',
  due_today: 'primary',
  overdue: 'warning',
  upcoming: 'info',
  unschedulable: 'warning',
} as const
export function progressStatusText(task: MeasurementTask): string {
  const label = measurementProgressLabels[task.status]
  // Delay describes an actual measurement; an unmeasured task has no measured date.
  return task.measurement_id && task.delay_days !== null
    ? `${label} · ${task.delay_days > 0 ? '延迟 ' : ''}${task.delay_days}天`
    : label
}
