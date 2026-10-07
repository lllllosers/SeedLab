export function dateText(value: string | null | undefined): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).format(new Date(value))
}
export function dateTimeText(value: string | null | undefined): string {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(value))
}
export const statusLabels: Record<string, string> = {
  draft: '草稿',
  ready: '已就绪',
  active: '进行中',
  completed: '已完成',
  cancelled: '已终止',
}
export const actionLabels: Record<string, string> = {
  create: '创建',
  update: '更新',
  delete: '删除',
  import: '导入',
}
export const entityLabels: Record<string, string> = {
  ImportJob: '材料导入',
  Taxon: '物种',
  SeedLot: '种子批次',
  Experiment: '实验',
  User: '用户',
  ExperimentProtocol: '实验方案',
  ExperimentMaterial: '实验材料',
  ExperimentMaterialOrder: '材料顺序',
  MeasurementTimepoint: '测定时间',
  GerminationDish: '培养皿',
  GerminationObservation: '发芽巡检',
  SeedlingSample: '幼苗样本',
  SeedlingMeasurement: '幼苗测定',
}
