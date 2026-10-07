import type { Experiment } from './features/experiments/index'
export interface User {
  id: string
  username: string
  display_name: string
  is_admin: boolean
  is_active: boolean
  must_change_password: boolean
}
export interface Taxon {
  id: string
  code: string
  scientific_name: string
  common_name: string | null
  family: string | null
  genus: string | null
  life_form: string | null
  notes: string | null
  is_active: boolean
  created_at: string
}
export interface SeedLot {
  id: string
  code: string
  taxon_id: string
  taxon: Taxon
  source: string | null
  source_code: string | null
  collected_at: string | null
  quantity: number | null
  notes: string | null
  is_active: boolean
  created_at: string
}
export interface Audit {
  id: string
  user_id: string | null
  action: string
  entity_type: string
  entity_id: string
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  created_at: string
  entity_label: string
  subject_label: string
  user_display_name: string
}
export interface Dashboard {
  taxa: number
  seed_lots: number
  experiments: number
  active_experiments: number
  active_experiment_ids: string[]
  recent_experiments: Pick<Experiment, 'id' | 'code' | 'name' | 'status'>[]
  recent_actions: Pick<Audit, 'id' | 'action' | 'entity_type' | 'created_at'>[]
  measurement: {
    due_today_count: number
    overdue_count: number
    experiments: Array<{
      id: string
      code: string
      name: string
      due_today_count: number
      overdue_count: number
      material_count: number
    }>
  }
}
