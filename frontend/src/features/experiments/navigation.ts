import type { Experiment } from './types'
import { resolveExperimentUi } from './uiRegistry.ts'

export function experimentTarget(experiment: Pick<Experiment, 'id' | 'status' | 'experiment_type'>) {
  const ui = resolveExperimentUi(experiment.experiment_type)
  return experiment.status === 'active' && ui
    ? ui.executionPath(experiment.id)
    : `/experiments/${experiment.id}`
}
