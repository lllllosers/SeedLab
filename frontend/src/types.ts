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
export type ExperimentStatus = 'draft' | 'ready' | 'active' | 'completed' | 'cancelled'
export interface Experiment {
  id: string
  code: string
  name: string
  description: string | null
  status: ExperimentStatus
  planned_start_date: string | null
  owner_id: string | null
  started_at: string | null
  ended_at: string | null
  created_at: string
}
export interface ExperimentProtocol {
  seeds_per_dish: number
  replicate_count: number
  observation_period_days: number
  sampling_rule: string
  sample_count: number
  sample_scope: 'per_dish' | 'per_material'
  germination_criterion: string
  summary: string | null
}
export interface AvailableLot {
  id: string
  code: string
  taxon_id: string
  taxon_name: string
  source: string | null
  quantity: number | null
}
export interface ExperimentMaterialInput {
  seed_lot_id: string
  label: string | null
  seeds_per_dish_override: number | null
  replicate_count_override: number | null
  sample_count_override: number | null
}
export interface ExperimentMaterial extends ExperimentMaterialInput {
  id: string
  seed_lot_code: string
  taxon_id: string
  taxon_name: string
  display_order: number
  effective_seeds_per_dish: number | null
  effective_replicate_count: number | null
  effective_sample_count: number | null
}
export interface Workload {
  material_count: number
  estimated_dish_count: number
  estimated_seed_count: number
  estimated_sample_count: number
  estimated_measurement_count: number
  estimated_latest_finish_date: string | null
}
export interface ExperimentConfiguration {
  experiment: Experiment
  owner_name: string | null
  protocol: ExperimentProtocol | null
  materials: ExperimentMaterial[]
  dag_days: number[]
  workload: Workload | null
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
