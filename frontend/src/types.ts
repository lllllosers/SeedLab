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
  taxon_common_name: string | null
  taxon_scientific_name: string
  taxon_code: string
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
  taxon_common_name: string | null
  taxon_scientific_name: string
  taxon_code: string
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
export interface GerminationDishStatus {
  id: string
  code: string
  material_id: string
  taxon_common_name: string | null
  taxon_scientific_name: string
  taxon_code: string
  seed_lot_code: string
  replicate_no: number
  label: string
  seed_count: number
  sown_at: string | null
  cumulative_germinated: number
  germination_rate: number
  remaining_ungerminated: number
  sample_count: number
  sample_target: number | null
  material_sample_count: number
  last_observed_at: string | null
  observation_count: number
}
export interface GerminationMaterialStatus {
  id: string
  taxon_common_name: string | null
  taxon_scientific_name: string
  taxon_code: string
  seed_lot_code: string
  dish_count: number
  seed_count: number
  cumulative_germinated: number
  germination_rate: number
  sample_count: number
  sample_target: number | null
}
export interface GerminationObservation {
  id: string
  dish_id: string
  dish_code: string
  replicate_no: number
  observed_at: string
  new_germinated_count: number
  notes: string | null
  generated_sample_count: number
}
export interface GerminationExecution {
  experiment: Pick<Experiment, 'id' | 'code' | 'name' | 'status' | 'started_at'>
  sampling_rule: string | null
  sample_scope: 'per_dish' | 'per_material' | null
  observation_period_days: number | null
  observation_period_end_at: string | null
  observation_period_overdue: boolean
  dish_count: number
  seed_count: number
  cumulative_germinated: number
  germination_rate: number
  sample_count: number
  materials: GerminationMaterialStatus[]
  dishes: GerminationDishStatus[]
  recent_observations: GerminationObservation[]
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
