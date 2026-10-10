export type IdentityStatus = 'existing' | 'new' | 'updatable' | 'confirm' | 'pending' | 'error'
export type GerStatus = 'completed' | 'active' | 'recorded' | 'none' | 'pending'
export interface PreviewRow {
  line: number
  taxon_status: IdentityStatus
  material_status: IdentityStatus
  taxon_id: string | null
  name: string | null
  scientific_name: string | null
  source: string | null
  source_code: string | null
  taxon_ger_status: GerStatus
  material_ger_status: GerStatus
  taxon_candidates: {
    id: string
    code: string
    common_name: string | null
    scientific_name: string
    ger_status: GerStatus
  }[]
  candidate_lot_id: string | null
  candidate_lots: {
    id: string
    code: string
    is_active: boolean
    source_code: string | null
    source: string | null
    collected_at: string | null
    ger_status: GerStatus
  }[]
  candidate_row: number | null
  suggested_decision: string | null
  warnings: string[]
  fills: string[]
  conflicts: string[]
  errors: string[]
}
export const identityLabels: Record<IdentityStatus, string> = {
  existing: '已有',
  new: '新增',
  updatable: '可补全资料',
  confirm: '需确认',
  pending: '待物种确认',
  error: '请修正',
}
export const gerLabels: Record<GerStatus, string> = {
  completed: '已完成萌发试验',
  active: '萌发试验进行中',
  recorded: '有萌发试验记录',
  none: '无萌发试验历史',
  pending: '待确认后核对',
}
export function reviewRowReady(row: PreviewRow, choice?: string): boolean {
  if (row.errors.length || !['existing', 'new'].includes(row.taxon_status)) return false
  if (row.material_status === 'confirm')
    return (
      choice === 'new' ||
      (!!choice &&
        ((row.candidate_row !== null && choice === `reuse-row:${row.candidate_row}`) ||
          row.candidate_lots.some((lot) => choice === `reuse:${lot.id}`)))
    )
  return ['existing', 'new', 'updatable'].includes(row.material_status)
}
