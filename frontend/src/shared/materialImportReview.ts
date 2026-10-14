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
  collected_at?: string | null
  system_common_name?: string | null
  name_difference?: boolean
  can_update_common_name?: boolean
  selection_species_group?: string | null
  selection_batch_group?: string | null
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
  completed: '做过',
  active: '正在做',
  recorded: '有历史记录',
  none: '没做过',
  pending: '待确认后核对',
}
export function displayCollectedDate(value: string | null | undefined): string {
  return value?.slice(0, 10) || '未记录'
}
export type ReviewFilter =
  | 'all'
  | 'pending'
  | 'new-species'
  | 'existing-species'
  | 'new-material'
  | 'history'
  | 'species-plan'
  | 'batch-plan'
export function filterReviewRows(
  rows: PreviewRow[],
  filter: ReviewFilter,
  search = '',
  decisions: Record<string, string> = {},
) {
  const query = search.trim().toLocaleLowerCase()
  const groups = new Set<string>()
  return rows.filter((row) => {
    const keep =
      filter === 'pending'
        ? !reviewRowReady(row, decisions[String(row.line)])
        : filter === 'new-species'
          ? row.taxon_status === 'new'
          : filter === 'existing-species'
            ? row.taxon_status === 'existing'
            : filter === 'new-material'
              ? isNewMaterial(rows, row, decisions)
              : filter === 'history'
                ? !['none', 'pending'].includes(row.taxon_ger_status)
                : true
    if (
      !keep ||
      (query &&
        ![
          row.name,
          row.scientific_name,
          row.source,
          row.source_code,
          ...row.candidate_lots.map((lot) => lot.source_code),
        ].some((value) => value?.toLocaleLowerCase().includes(query)))
    )
      return false
    if (filter === 'species-plan' || filter === 'batch-plan') {
      const group =
        filter === 'species-plan' ? row.selection_species_group : row.selection_batch_group
      if (!group || groups.has(group)) return false
      groups.add(group)
    }
    return true
  })
}
export function isNewMaterial(
  rows: PreviewRow[],
  row: PreviewRow,
  decisions: Record<string, string>,
): boolean {
  const visited = new Set<number>()
  while (!visited.has(row.line)) {
    visited.add(row.line)
    const choice = decisions[String(row.line)]
    if (!choice?.startsWith('reuse-row:')) return row.material_status === 'new' || choice === 'new'
    const other = rows.find((item) => String(item.line) === choice.slice(10))
    if (!other) return false
    row = other
  }
  return false
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
