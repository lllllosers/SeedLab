import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync, readdirSync } from 'node:fs'
import { taskSearchMatches } from '../src/utils/measurement.ts'
import { auditDetails } from '../src/utils/audit.ts'

test('execution displays public numbers and never falls back to internal dish code', () => {
  const folder = new URL('../src/views/GerminationExecution/', import.meta.url)
  for (const file of readdirSync(folder).filter(name => name.endsWith('.vue'))) {
    const source = readFileSync(new URL(file, folder), 'utf8')
    assert.doesNotMatch(source, /dish\.code|dish_code/, file)
  }
  for (const file of ['MeasurementEditor.vue', 'MeasurementRecordsTable.vue', 'SeedlingMeasurementWorkbench.vue']) {
    const source = readFileSync(new URL(file, folder), 'utf8')
    assert.match(source, /sample_display_number/)
    assert.doesNotMatch(source, /String\([^)]*\.sample_number\)\.padStart/)
  }
  const details = auditDetails({ entity_type: 'GerminationDish', before: null,
    after: { code: 'GER-202609-001-M001-R01', field_number: '001-1' } })
  assert.deepEqual(details, [{ label: '现场编号', before: '未填写', after: '001-1' }])
})

test('full seedling identities are searchable, internal codes are not', () => {
  for (const number of ['001-01', '001-1-01']) {
    const task = { experiment_number: '001', field_number: number === '001-01' ? '001' : '001-1',
      sample_display_number: number, sample_number: 1, dish_code: 'GER-202609-001-M001-R01' }
    assert.equal(taskSearchMatches(task, number), true)
    assert.equal(taskSearchMatches(task, task.dish_code), false)
  }
})

test('creation offers explicit experiment type and an empty freely named experiment', () => {
  const source = readFileSync(new URL('../src/views/ExperimentWizardView.vue', import.meta.url), 'utf8')
  assert.match(source, /name: ''/)
  assert.match(source, /label="实验类型"/)
  assert.match(source, /\/experiments\/types/)
  assert.match(source, /experiment_type: form.experiment_type/)
  assert.match(source, /研究内容自定义/)
  assert.doesNotMatch(source, /form\.name\s*=/)
})
