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
