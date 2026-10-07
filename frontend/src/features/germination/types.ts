import type { Experiment } from '../experiments/index'
export interface ExperimentProtocol {
  seeds_per_dish: number
  replicate_count: number
  observation_period_days: number | null
  sampling_rule: string
  sample_count: number
  sample_scope: 'per_dish' | 'per_material'
  germination_criterion: string
  summary: string | null
}
export interface AvailableLot {
  id: string
  code: string
  sort_rank: number
  taxon_id: string
  taxon_common_name: string | null
  taxon_scientific_name: string
  taxon_code: string
  source: string | null
  source_code: string | null
  collected_at: string | null
  notes: string | null
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
  source_code: string | null
  source: string | null
  collected_at: string | null
  quantity: number | null
  notes: string | null
  taxon_id: string
  taxon_common_name: string | null
  taxon_scientific_name: string
  taxon_code: string
  display_order: number
  experiment_number: number | null
  preview_number: number
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
  source_code: string | null
  experiment_number: number | null
  preview_number: number
  field_number: string | null
  replicate_no: number
  label: string
  seed_count: number
  sown_at: string | null
  cancelled_at: string | null
  cancel_reason: string | null
  today_observed: boolean
  observation_period_end_at: string | null
  cumulative_germinated: number | null
  germination_rate: number | null
  remaining_ungerminated: number | null
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
  source_code: string | null
  experiment_number: number | null
  preview_number: number
  sown_count: number
  cancelled_count: number
  dish_count: number
  seed_count: number
  cumulative_germinated: number | null
  germination_rate: number | null
  sample_count: number
  sample_target: number | null
}
export interface GerminationObservation {
  id: string
  dish_id: string
  dish_code: string
  field_number: string | null
  replicate_no: number
  observed_at: string
  new_germinated_count: number
  notes: string | null
  generated_sample_count: number
}
export interface GerminationExecution {
  experiment: Pick<
    Experiment,
    'id' | 'code' | 'name' | 'status' | 'started_at' | 'numbering_locked_at'
  >
  sampling_rule: string | null
  sample_scope: 'per_dish' | 'per_material' | null
  observation_period_days: number | null
  observation_period_end_at: string | null
  observation_period_overdue: boolean
  dish_count: number
  sown_count: number
  pending_count: number
  cancelled_count: number
  today_observed_count: number
  today_pending_count: number
  latest_sown_estimated_finish_at: string | null
  pending_material_count: number
  seed_count: number
  cumulative_germinated: number | null
  germination_rate: number | null
  sample_count: number
  materials: GerminationMaterialStatus[]
  dishes: GerminationDishStatus[]
  recent_observations: GerminationObservation[]
}
