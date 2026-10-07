import type { ExperimentMaterialInput, ExperimentProtocol } from '../index'

export function effectiveMaterial(
  material: Pick<ExperimentMaterialInput, 'seeds_per_dish_override' | 'replicate_count_override' | 'sample_count_override'>,
  protocol: Pick<ExperimentProtocol, 'seeds_per_dish' | 'replicate_count' | 'sample_count'>,
) {
  return {
    seedsPerDish: material.seeds_per_dish_override ?? protocol.seeds_per_dish,
    replicateCount: material.replicate_count_override ?? protocol.replicate_count,
    sampleCount: material.sample_count_override ?? protocol.sample_count,
  }
}
