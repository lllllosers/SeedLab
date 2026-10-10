import test from 'node:test'
import assert from 'node:assert/strict'
import { reviewRowReady, identityLabels, gerLabels } from '../src/shared/materialImportReview.ts'

const base = { taxon_status: 'existing', material_status: 'new', errors: [], candidate_row: null, candidate_lots: [] }
test('species and material decisions cannot stand in for one another', () => {
  assert.equal(reviewRowReady(base), true)
  assert.equal(reviewRowReady({...base, taxon_status: 'confirm'}, 'new'), false)
  assert.equal(reviewRowReady({...base, material_status: 'pending'}), false)
  assert.equal(reviewRowReady({...base, errors: ['请核对']}), false)
  assert.equal(reviewRowReady({...base, material_status: 'confirm'}), false)
  assert.equal(reviewRowReady({...base, material_status: 'confirm'}, 'new'), true)
})
test('material confirmation requires a current candidate or explicit new material', () => {
  const row = {...base, material_status: 'confirm', candidate_lots: [{id: 'lot-a'}]}
  assert.equal(reviewRowReady(row, 'reuse:lot-a'), true)
  assert.equal(reviewRowReady(row, 'reuse:other'), false)
  assert.equal(reviewRowReady(row, 'reuse'), false)
  assert.equal(reviewRowReady({...row, candidate_row: 2}, 'reuse-row:2'), true)
  assert.equal(reviewRowReady({...row, candidate_row: 2}, 'reuse-row:3'), false)
})
test('history labels distinguish completed, running, other records and no history', () => {
  assert.equal(new Set(Object.values(gerLabels)).size, 5)
  assert.match(gerLabels.completed, /已完成/)
  assert.match(gerLabels.active, /进行中/)
  assert.doesNotMatch(gerLabels.recorded, /完成/)
  assert.match(identityLabels.pending, /物种确认/)
})
