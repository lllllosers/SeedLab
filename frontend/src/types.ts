export interface User {
  id: string
  username: string
  display_name: string
  is_admin: boolean
  is_active: boolean
}
export interface Taxon {
  id: string
  code: string
  scientific_name: string
  common_name: string | null
  family: string | null
  notes: string | null
  is_active: boolean
  created_at: string
}
export interface SeedLot {
  id: string
  code: string
  taxon_id: string
  source: string | null
  quantity: number | null
  notes: string | null
  is_active: boolean
  created_at: string
}
export type ExperimentStatus = 'draft' | 'active' | 'completed' | 'cancelled'
export interface Experiment {
  id: string
  code: string
  name: string
  description: string | null
  status: ExperimentStatus
  started_at: string | null
  ended_at: string | null
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
}
export interface Dashboard {
  taxa: number
  seed_lots: number
  experiments: number
  active_experiments: number
  recent_experiments: Pick<Experiment, 'id' | 'code' | 'name' | 'status'>[]
  recent_actions: Pick<Audit, 'id' | 'action' | 'entity_type' | 'created_at'>[]
}
