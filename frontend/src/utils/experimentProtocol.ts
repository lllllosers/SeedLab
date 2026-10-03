import type { ExperimentProtocol } from '../types'

export function defaultExperimentProtocol(): ExperimentProtocol {
  return {
    seeds_per_dish: 20,
    replicate_count: 3,
    observation_period_days: null,
    sampling_rule: 'first_germinated',
    sample_count: 5,
    sample_scope: 'per_dish',
    germination_criterion: '',
    summary: null,
  }
}

export function validDishPlan(protocol: ExperimentProtocol): boolean {
  const days = protocol.observation_period_days
  return (
    protocol.seeds_per_dish > 0 &&
    protocol.replicate_count > 0 &&
    !!protocol.germination_criterion.trim() &&
    (days === null || (Number.isInteger(days) && days > 0))
  )
}
