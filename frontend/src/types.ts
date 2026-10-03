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
export type ExperimentStatus = 'draft' | 'ready' | 'active' | 'completed' | 'cancelled'
export interface Experiment {
  experiment_type: 'GER'
  experiment_type_label: string
  id: string
  code: string
  name: string
  description: string | null
  status: ExperimentStatus
  planned_start_date: string | null
  owner_id: string | null
  started_at: string | null
  numbering_locked_at: string | null
  ended_at: string | null
  termination_reason: string | null
  created_at: string
}
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

export type MeasurementStatus = 'overdue' | 'due_today' | 'upcoming' | 'completed' | 'unschedulable'
export interface MeasurementTask {
  experiment_id: string
  experiment_code: string
  material_id: string
  experiment_number: string | null
  dish_id: string
  dish_code: string
  field_number: string | null
  replicate_no: number
  sample_id: string
  sample_display_number: string | null
  sample_number: number
  position_label: string | null
  taxon_common_name: string | null
  taxon_scientific_name: string
  taxon_code: string
  seed_lot_code: string
  source_code: string | null
  germinated_at: string | null
  timepoint_id: string
  day_after_germination: number
  scheduled_date: string | null
  status: MeasurementStatus
  measurement_id: string | null
  root_length_mm: number | null
  shoot_length_mm: number | null
  root_unavailable: boolean
  shoot_unavailable: boolean
  measured_at: string | null
  notes: string | null
  delay_days: number | null
}
export interface MeasurementTasks {
  experiment_status: ExperimentStatus
  dag_days: number[]
  summary: {
    due_today_count: number
    overdue_count: number
    completed_today_count: number
    upcoming_count: number
    unschedulable_count: number
  }
  tasks: MeasurementTask[]
}
export interface MeasurementHistory {
  dag_days: number[]
  samples: Array<{
    sample_id: string
    sample_display_number: string | null
    sample_number: number
    field_number: string | null
    position_label: string | null
    germinated_at: string | null
    measurements: Record<string, MeasurementTask>
  }>
}

export interface MeasurementSummary {
  due_today_count: number
  overdue_count: number
  completed_today_count: number
  upcoming_count: number
  unschedulable_count: number
  pending_count: number
  material_count: number
}
export interface MeasurementMaterial {
  material_id: string
  experiment_number: string
  common_name: string | null
  scientific_name: string
  due_today_count: number
  overdue_count: number
  upcoming_count: number
  completed_today_count: number
  pending_count: number
  dag_counts: Array<{ day_after_germination: number; pending_count: number }>
}
export interface MeasurementWorklist {
  experiment_status: ExperimentStatus
  dag_days: number[]
  summary: MeasurementSummary
  materials: MeasurementMaterial[]
  page: number
  page_size: number
  total_materials: number
  total_pages: number
}
export interface Paged<T> {
  items: T[]
  total: number
  page: number
  page_size: number
  total_pages: number
}
