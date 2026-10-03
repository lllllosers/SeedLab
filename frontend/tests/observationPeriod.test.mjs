import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import { defaultExperimentProtocol, validDishPlan } from '../src/utils/experimentProtocol.ts'
import { todayPendingDish, observationPlanOverdue, germinationText } from '../src/utils/germination.ts'

const source = (path) => readFileSync(new URL('../src/' + path, import.meta.url), 'utf8')

test('existing completion action explains actual tasks without directing normal completion to termination', () => {
  const component = source('views/ExperimentDesignDetailView.vue')
  const completion = component.slice(component.indexOf('async function completeExperiment()'),
    component.indexOf('async function terminateExperiment()'))
  assert.match(completion, /if \(!data\.can_complete\)/)
  assert.match(completion, /data\.pending_dish_count/)
  assert.match(completion, /data\.measurement_pending_count/)
  assert.match(completion, /请先处理待置床培养皿并完成已有幼苗测定/)
  assert.match(completion, /请确认本实验已正常完成/)
  assert.match(completion, /api\.post\(`\$\{base\.value\}\/complete`\)/)
  assert.doesNotMatch(completion, /终止实验|仍在观察|观察天数不代表观察已完成/)
})

test('wizard defaults to no observation plan and accepts empty or positive days', () => {
  const protocol = defaultExperimentProtocol()
  assert.equal(protocol.observation_period_days, null)
  assert.equal(validDishPlan(protocol), false) // the germination criterion is still required
  protocol.germination_criterion = '胚根可见'
  assert.equal(validDishPlan(protocol), true)
  for (const days of [1, 14, 30]) assert.equal(validDishPlan({ ...protocol, observation_period_days: days }), true)
  for (const days of [0, -1, 1.5]) assert.equal(validDishPlan({ ...protocol, observation_period_days: days }), false)
  for (const values of [{ seeds_per_dish: 0 }, { replicate_count: 0 }, { germination_criterion: ' ' }])
    assert.equal(validDishPlan({ ...protocol, ...values }), false)
  const wizard = source('views/ExperimentWizardView.vue')
  assert.match(wizard, /defaultExperimentProtocol\(\)/)
  assert.match(wizard, /step\.value === 2 && !validDishPlan\(protocol\.value\)/)
  assert.doesNotMatch(wizard, /!protocol\.value\.observation_period_days|observation_period_days:\s*14/)
})

test('pending inspection depends only on sowing, cancellation and inspection today', () => {
  const now = Date.parse('2026-10-03T08:00:00Z')
  const dish = { sown_at: '2026-08-01T00:00:00Z', cancelled_at: null, today_observed: false }
  for (const endAt of [null, '2026-09-01T00:00:00Z', '2026-11-01T00:00:00Z']) {
    const row = { ...dish, observation_period_end_at: endAt }
    assert.equal(todayPendingDish(row), true)
    assert.equal(observationPlanOverdue(endAt, now), endAt === '2026-09-01T00:00:00Z')
    assert.equal(todayPendingDish({ ...row, today_observed: true }), false)
    assert.equal(todayPendingDish({ ...row, sown_at: null }), false)
    assert.equal(todayPendingDish({ ...row, cancelled_at: '2026-09-01T00:00:00Z' }), false)
  }
  const component = source('views/GerminationExecution/GerminationQuickEntry.vue')
  assert.match(component, /mode\.value === 'pending' && !todayPendingDish\(dish\)/)
  assert.match(component, /mode\.value === 'ended' && !observationPlanOverdue\(dish\.observation_period_end_at\)/)
  assert.match(component, /label="超过计划观察期限" value="ended"/)
  assert.doesNotMatch(component, /观察期已结束|periodEnded/)
  assert.equal(germinationText(null, true), '未记录')
  assert.equal(germinationText(0, true), '0%')
})

test('creation and editing explain optional days and preserve null on clearing', () => {
  for (const path of ['views/ExperimentWizard/ProtocolStep.vue', 'views/ExperimentDesignDetailView.vue']) {
    const component = source(path)
    assert.match(component, /计划发芽观察天数（可选）/)
    assert.match(component, /仅用于预计日期和超期提醒，不会自动结束观察；不确定时可留空。/)
    assert.match(component, /protocol\.observation_period_days = \$event \?\? null/)
    assert.doesNotMatch(component, /observation_period_days:\s*14/)
  }
})
