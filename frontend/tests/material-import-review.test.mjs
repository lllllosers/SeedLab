import test from 'node:test'
import assert from 'node:assert/strict'
import {
  reviewRowReady,
  identityLabels,
  gerLabels,
  filterReviewRows,
  isNewMaterial,
} from '../src/shared/materialImportReview.ts'

const base = {
  taxon_status: 'existing',
  material_status: 'new',
  errors: [],
  candidate_row: null,
  candidate_lots: [],
}
test('merged checklist material retains the identity of the chosen material', () => {
  const rows = [
    { ...base, line: 2 },
    { ...base, line: 3, material_status: 'confirm', candidate_row: 2 },
  ]
  assert.equal(isNewMaterial(rows, rows[1], { 3: 'reuse-row:2' }), true)
  assert.equal(filterReviewRows(rows, 'new-material', '', { 3: 'reuse-row:2' }).length, 2)
  rows[0].material_status = 'existing'
  assert.equal(isNewMaterial(rows, rows[1], { 3: 'reuse-row:2' }), false)
})
test('species and material decisions cannot stand in for one another', () => {
  assert.equal(reviewRowReady(base), true)
  assert.equal(reviewRowReady({ ...base, taxon_status: 'confirm' }, 'new'), false)
  assert.equal(reviewRowReady({ ...base, material_status: 'pending' }), false)
  assert.equal(reviewRowReady({ ...base, errors: ['请核对'] }), false)
  assert.equal(reviewRowReady({ ...base, material_status: 'confirm' }), false)
  assert.equal(reviewRowReady({ ...base, material_status: 'confirm' }, 'new'), true)
})
test('search and independent population filters retain one representative per group', () => {
  const rows = [
    {
      ...base,
      line: 2,
      name: '甲',
      scientific_name: 'Species a',
      source: '山地',
      source_code: 'A',
      taxon_ger_status: 'none',
      selection_species_group: 'a',
      selection_batch_group: 'a1',
    },
    {
      ...base,
      line: 3,
      name: '甲别名',
      scientific_name: 'Species a',
      source: '山地',
      source_code: 'A',
      taxon_ger_status: 'none',
      selection_species_group: 'a',
      selection_batch_group: 'a1',
    },
    {
      ...base,
      line: 4,
      name: '甲',
      scientific_name: 'Species a',
      source: '河岸',
      source_code: 'B',
      taxon_ger_status: 'none',
      selection_species_group: 'a',
      selection_batch_group: 'a2',
    },
    {
      ...base,
      line: 5,
      name: '乙',
      scientific_name: 'Species b',
      source: '林地',
      source_code: 'CODE-C',
      taxon_status: 'confirm',
      material_status: 'pending',
      taxon_ger_status: 'pending',
    },
  ]
  assert.equal(filterReviewRows(rows, 'species-plan').length, 1)
  assert.equal(filterReviewRows(rows, 'batch-plan').length, 2)
  assert.deepEqual(
    filterReviewRows(rows, 'all', '河岸').map((row) => row.line),
    [4],
  )
  assert.deepEqual(
    filterReviewRows(rows, 'all', 'species b').map((row) => row.line),
    [5],
  )
  assert.equal(filterReviewRows(rows, 'pending').length, 1)
  assert.equal(filterReviewRows(rows, 'all', 'CODE-C').length, 1)
})
test('material confirmation requires a current candidate or explicit new material', () => {
  const row = { ...base, material_status: 'confirm', candidate_lots: [{ id: 'lot-a' }] }
  assert.equal(reviewRowReady(row, 'reuse:lot-a'), true)
  assert.equal(reviewRowReady(row, 'reuse:other'), false)
  assert.equal(reviewRowReady(row, 'reuse'), false)
  assert.equal(reviewRowReady({ ...row, candidate_row: 2 }, 'reuse-row:2'), true)
  assert.equal(reviewRowReady({ ...row, candidate_row: 2 }, 'reuse-row:3'), false)
})
test('history labels distinguish completed, running, other records and no history', () => {
  assert.equal(new Set(Object.values(gerLabels)).size, 5)
  assert.match(gerLabels.completed, /做过/)
  assert.match(gerLabels.active, /正在做/)
  assert.doesNotMatch(gerLabels.recorded, /完成/)
  assert.match(identityLabels.pending, /物种确认/)
})
