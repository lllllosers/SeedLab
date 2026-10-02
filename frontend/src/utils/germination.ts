export function germinationText(value: number | null, percentage = false): string {
  return value === null ? '未记录' : `${value}${percentage ? '%' : ''}`
}
