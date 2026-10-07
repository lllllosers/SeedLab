import assert from 'node:assert/strict'
import test from 'node:test'
import { effectiveMaterial } from '../src/features/germination/utils/effectiveMaterial.ts'

test('review shows final protocol values for defaults and material changes', () => {
  const protocol = { seeds_per_dish: 5, replicate_count: 2, sample_count: 3 }
  assert.deepEqual(effectiveMaterial({
    seeds_per_dish_override: null, replicate_count_override: null, sample_count_override: null,
  }, protocol), { seedsPerDish: 5, replicateCount: 2, sampleCount: 3 })
  assert.deepEqual(effectiveMaterial({
    seeds_per_dish_override: 8, replicate_count_override: null, sample_count_override: 4,
  }, protocol), { seedsPerDish: 8, replicateCount: 2, sampleCount: 4 })
})
