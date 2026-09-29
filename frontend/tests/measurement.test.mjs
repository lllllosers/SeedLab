import assert from 'node:assert/strict'
import test from 'node:test'
import { historyValue, isResolved, measurementStatusLabels, measurementValue } from '../src/utils/measurement.ts'

test('measurement display keeps zero, missing, and unavailable distinct', () => {
  assert.equal(measurementValue(0, false, true), '0')
  assert.equal(measurementValue(null, true, true), 'NA')
  assert.equal(measurementValue(null, false, false), '—')
  assert.equal(historyValue(undefined), '—')
  assert.equal(historyValue({ measurement_id: 'record', root_length_mm: 0,
    shoot_length_mm: null, root_unavailable: false, shoot_unavailable: true }), '0 / NA')
})

test('quick entry requires both resolved values and retains zero', () => {
  assert.equal(isResolved('0', false), true)
  assert.equal(isResolved('0.00', false), true)
  assert.equal(isResolved('', true), true)
  assert.equal(isResolved('', false), false)
  assert.equal(isResolved('1', true), false)
  assert.equal(isResolved('-1', false), false)
  assert.equal(isResolved('1.234', false), false)
  assert.equal(measurementStatusLabels.overdue, '已逾期')
  assert.equal(measurementStatusLabels.due_today, '今日待测')
})
