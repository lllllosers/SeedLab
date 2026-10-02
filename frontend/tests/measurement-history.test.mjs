import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { materialProgressTasks, measurementProgressLabels, measurementProgressTagTypes, measurementValue, progressStatusText } from '../src/utils/measurement.ts'
const source = (name) => readFileSync(new URL('../src/views/GerminationExecution/' + name, import.meta.url), 'utf8')

test('inspection headers name seed counts and germination without changing values', () => {
  const component = source('GerminationQuickEntry.vue')
  const headers = [...component.matchAll(/<th>([^<]+)<\/th>/g)].map(match => match[1])
  assert.deepEqual(headers, ['培养皿 / 材料', '重复', '置床粒数', '累计发芽', '发芽率', '未发芽', '取样进度', '本次新增', '备注'])
})

test('progress groups numeric dishes, seedlings and all configured days without dropping unmeasured slots', () => {
  const slots = []
  for (const replicate of [10, 2, 1]) for (const sample of [3, 1, 2]) for (const dag of [3, 0, 1])
    slots.push({ field_number: '001-' + replicate, replicate_no: replicate, sample_number: sample,
      day_after_germination: dag, sample_id: `${replicate}-${sample}`, measurement_id: dag === 0 ? 'record' : null,
      measured_at: dag === 0 ? '2026-10-01T09:00:00Z' : null })
  const sorted = materialProgressTasks(slots)
  assert.equal(sorted.length, 27); assert.equal(sorted.filter(slot => slot.measurement_id).length, 9)
  assert.deepEqual(sorted.slice(0, 9).map(slot => [slot.replicate_no, slot.sample_number, slot.day_after_germination]),
    [[1,1,0],[1,1,1],[1,1,3],[1,2,0],[1,2,1],[1,2,3],[1,3,0],[1,3,1],[1,3,3]])
  assert.equal(sorted[9].replicate_no, 2); assert.equal(sorted[18].replicate_no, 10)
  assert.equal(slots[0].replicate_no, 10) // do not reorder the active work queue
})

test('progress values and states distinguish zero, NA, missing and real measurement delay', () => {
  assert.equal(measurementValue(0, false, true), '0')
  assert.equal(measurementValue(null, true, true), 'NA')
  assert.equal(measurementValue(null, false, false), '—')
  assert.deepEqual(measurementProgressLabels, {overdue:'已逾期',due_today:'今日待测',upcoming:'后续任务',completed:'已测',unschedulable:'无法安排'})
  assert.equal(progressStatusText({status:'completed',measurement_id:'r',delay_days:0}), '已测 · 0天')
  assert.equal(progressStatusText({status:'completed',measurement_id:'r',delay_days:2}), '已测 · 延迟 2天')
  assert.equal(progressStatusText({status:'overdue',measurement_id:null,delay_days:null}), '已逾期')
  assert.equal(progressStatusText({status:'completed',measurement_id:'r',delay_days:null}), '已测')
  assert.equal(measurementProgressTagTypes.completed,'success'); assert.equal(measurementProgressTagTypes.upcoming,'info')
})

test('compact progress omits repeated context, keeps task details and guards edit actions', () => {
  const table = source('MeasurementRecordsTable.vue'), workbench = source('SeedlingMeasurementWorkbench.vue')
  assert.match(table, /compact\?: boolean/)
  assert.match(table, /v-if="!compact"[^>]*label="实验编号"/)
  assert.match(table, /v-if="!compact"[^>]*label="物种"/)
  for (const label of ['幼苗编号','DAG','根长（mm）','苗长（mm）','计划日期','实际测定时间','状态 / 延迟','备注','操作']) assert.ok(table.includes(`label="${label}"`))
  assert.match(table, /v-if="row.measurement_id"/)
  assert.match(table, /measurementValue\(row.root_length_mm, row.root_unavailable, !!row.measurement_id\)/)
  assert.match(workbench, /:items="progressTasks"\s+compact/)
  assert.match(workbench, /materialProgressTasks\(tasks.value\)/)
  assert.match(workbench, /本材料测定进度与记录/)
})
