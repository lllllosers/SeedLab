import type { ExperimentStatus } from '../experiments/index'
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
