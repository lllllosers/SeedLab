import { dateTimeText, statusLabels } from '../utils.ts'
import type { Audit } from '../types'
const labels: Record<string, string> = {
  field_number: '现场编号',
  new_taxa: '新增物种数',
  new_lots: '新增批次数',
  material_count: '实验材料数',
  planned: '计划培养皿',
  numbering_confirmed: '已确认置床编号',
  reason: '取消原因',
  collected_at: '采集时间',
  life_form: '生活型',
  genus: '属',
  line: '导入行号',
  code: '编号',
  name: '名称',
  scientific_name: '学名',
  common_name: '中文名',
  family: '科',
  notes: '备注',
  description: '实验说明',
  source: '来源',
  source_code: '原始材料编号',
  quantity: '种子数量',
  collection_date: '采集日期',
  storage_location: '存放位置',
  is_active: '使用状态',
  username: '登录账号',
  display_name: '显示姓名',
  is_admin: '管理员权限',
  status: '实验状态',
  termination_reason: '终止原因',
  ended_at: '结束时间',
  started_at: '开始时间',
  planned_start_date: '计划开始日期',
  numbering_locked_at: '编号确认时间',
  seeds_per_dish: '每皿粒数',
  replicate_count: '重复数',
  observation_period_days: '观察周期（天）',
  sample_count: '取样数',
  sample_scope: '取样范围',
  sampling_rule: '取样规则',
  germination_criterion: '发芽判定标准',
  label: '材料标签',
  seeds_per_dish_override: '本材料每皿粒数',
  replicate_count_override: '本材料重复数',
  sample_count_override: '本材料取样数',
  experiment_number: '本次实验编号',
  material_order: '材料顺序',
  days: '发芽后测定天数',
  day_after_germination: '发芽后测定天数',
  sown_at: '实际置床时间',
  cancelled_at: '取消时间',
  cancel_reason: '取消原因',
  seed_count: '置床粒数',
  replicate_no: '重复编号',
  observed_at: '巡检时间',
  new_germinated_count: '本次新增发芽',
  cumulative_germinated_count: '累计发芽',
  sample_number: '幼苗编号',
  germinated_at: '发芽判定时间',
  position_label: '位置标签',
  root_length_mm: '根长（mm）',
  shoot_length_mm: '苗长（mm）',
  measured_at: '实际测定时间',
  filename: '导入文件',
  total_rows: '材料行数',
  successful_rows: '成功导入行数',
  created_taxa: '新增物种数',
  created_lots: '新增批次数',
  password_reset: '重置密码',
  must_change_password: '首次登录需修改密码',
  protocol: '实验方案',
  materials: '实验材料',
  dag_days: '发芽后测定天数',
  order: '材料顺序',
  summary: '方案说明',
  reordered: '调整材料顺序',
}
function value(key: string, raw: unknown): string {
  if (raw === null || raw === undefined || raw === '') return '未填写'
  if (typeof raw === 'boolean')
    return key === 'is_active' ? (raw ? '使用中' : '已停用') : raw ? '是' : '否'
  if (key === 'status')
    return (
      statusLabels[String(raw)] ||
      { completed: '已完成', previewed: '已预览', confirmed: '已确认' }[String(raw)] ||
      '已记录'
    )
  if (key === 'sample_scope') return raw === 'per_dish' ? '每个培养皿' : '每份实验材料'
  if (key === 'sampling_rule') return '按发芽顺序选择前若干株'
  if (key.endsWith('_at')) return dateTimeText(String(raw))
  if (Array.isArray(raw))
    return raw.every((v) => typeof v === 'number') ? raw.join('、') : `${raw.length} 份已记录`
  if (typeof raw === 'object')
    return (
      Object.entries(raw as Record<string, unknown>)
        .filter(([k]) => labels[k])
        .map(([k, v]) => `${labels[k]}：${value(k, v)}`)
        .join('；') || '已记录'
    )
  return String(raw)
}
export function auditDetails(log: Pick<Audit, 'before' | 'after' | 'entity_type'>) {
  const formatted = (key: string, raw: unknown) =>
    key === 'status' && log.entity_type === 'GerminationDish'
      ? { planned: '待置床', cancelled: '已取消' }[String(raw)] || value(key, raw)
      : value(key, raw)
  const before = log.before || {},
    after = log.after || {},
    keys = [...new Set([...Object.keys(before), ...Object.keys(after)])]
  return keys
    .filter(
      (key) =>
        labels[key] &&
        !key.endsWith('_id') &&
        !['root_unavailable', 'shoot_unavailable'].includes(key),
    )
    .map((key) => ({
      label: labels[key],
      before:
        (key === 'root_length_mm' && before.root_unavailable) ||
        (key === 'shoot_length_mm' && before.shoot_unavailable)
          ? 'NA'
          : formatted(key, before[key]),
      after:
        (key === 'root_length_mm' && after.root_unavailable) ||
        (key === 'shoot_length_mm' && after.shoot_unavailable)
          ? 'NA'
          : formatted(key, after[key]),
    }))
}
