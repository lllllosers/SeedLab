import assert from 'node:assert/strict'
import test from 'node:test'
import { germinationText } from '../src/utils/germination.ts'

test('unrecorded inspection stays distinct from explicitly recorded zero', () => {
  assert.equal(germinationText(null), '未记录')
  assert.equal(germinationText(null, true), '未记录')
  assert.equal(germinationText(0), '0')
  assert.equal(germinationText(0, true), '0%')
  assert.equal(germinationText(12), '12')
  assert.equal(germinationText(24, true), '24%')
})
