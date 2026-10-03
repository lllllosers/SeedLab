import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'

const source = (path) => readFileSync(new URL('../src/' + path, import.meta.url), 'utf8')

test('ended experiment execution explains zero tasks and retains history navigation', () => {
  const page = source('views/GerminationExecutionView.vue')
  assert.match(page, /v-if="execution\.experiment\.status !== 'active'"/)
  assert.match(page, /实验已结束，无当前执行待办；历史数据仍可查看。/)
  assert.match(page, /v-if="execution\.experiment\.status === 'active'"[\s\S]*?:execution="execution"/)
  for (const label of ['培养皿状态', '巡检历史', '幼苗测定']) assert.ok(page.includes(`label="${label}"`))
})

test('inactive measurement workbench hides editors and task cards while records remain accessible', () => {
  const page = source('views/GerminationExecution/SeedlingMeasurementWorkbench.vue')
  const guard = page.indexOf(`v-else-if="data && data.experiment_status !== 'active'"`)
  const workbench = page.indexOf('class="measurement-workbench"')
  assert.ok(guard > 0 && workbench > guard)
  assert.match(page.slice(guard, workbench), /请打开“测定记录”查看历史数据。/)
  assert.match(page, /<MeasurementRecords\s+v-if="tab === 'records' && data"/)
  assert.match(page, /:status="data\.experiment_status"/)
  assert.match(page, /<el-tab-pane label="测定记录" name="records"/)
})
