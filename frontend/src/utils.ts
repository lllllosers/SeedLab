export function dateText(value: string | null | undefined): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date(value))
}
export const statusLabels: Record<string, string> = {
  draft: '草稿',
  ready: '已就绪',
  active: '进行中',
  completed: '已完成',
  cancelled: '已取消',
}
export const actionLabels: Record<string, string> = {
  create: '创建',
  update: '更新',
  delete: '删除',
  import: '导入',
}
export const entityLabels: Record<string, string> = {
  Taxon: '物种',
  SeedLot: '种子批次',
  Experiment: '实验',
  User: '用户',
}
