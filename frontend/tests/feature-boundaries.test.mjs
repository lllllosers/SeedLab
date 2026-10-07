import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync, readdirSync, existsSync } from 'node:fs'
import { dependencies, assertFeatureDependencies, assertNoLifecycleAuthority } from './frontendArchitecture.mjs'
import { experimentUiRegistry, resolveExperimentUi } from '../src/features/experiments/uiRegistry.ts'
import { experimentTarget } from '../src/features/experiments/navigation.ts'

const root = new URL('../src/', import.meta.url)
const read = file => readFileSync(new URL(file, root), 'utf8')
function files(folder = '') {
  return readdirSync(new URL(folder, root), { withFileTypes: true }).flatMap(entry =>
    entry.isDirectory() ? files(`${folder ? folder + '/' : ''}${entry.name}`) : /\.(ts|vue)$/.test(entry.name)
      ? [`${folder ? folder + '/' : ''}${entry.name}`] : [])
}

test('actual feature imports use public composition and shared stays independent', () => {
  for (const file of files()) {
    assertFeatureDependencies(read(file), file)
    assertNoLifecycleAuthority(read(file), file)
    if (file.startsWith('features/') || file.startsWith('shared/'))
      for (const dep of dependencies(read(file), file))
        assert.ok(['.ts', '.vue', '/index.ts'].some(ext => existsSync(new URL(dep + ext, root))), `${file}: ${dep}`)
  }
})

for (const [file, source] of [
  ['features/experiments/pages/Any.vue', "import Page from '../../germination/pages/Private.vue'"],
  ['features/experiments/pages/Any.vue', "const page = () => import('../../germination/pages/Private.vue')"],
  ['features/experiments/pages/Any.ts', "export { germinationUi } from '../../germination'"],
  ['features/measurement/types.ts', "import type { GER } from '../germination/index.ts'"],
  ['shared/helper.ts', "import type { Experiment } from '../features/experiments'"],
  ['app/routes.ts', "const page = () => import('../features/germination/pages/Private.vue')"],
]) test(`architecture guard rejects injected ${source}`, () => {
  const fixture = file.endsWith('.vue') ? `<script setup lang="ts">${source}</script>` : source
  assert.throws(() => assertFeatureDependencies(fixture, file), /private feature|registry|measurement|shared/)
})

for (const source of ['function can_complete(facts) { return true }',
  'const canReady = () => true', "const allowedTransitions = { draft: ['active'] }",
  'const rules = { canComplete: () => true }'])
  test(`lifecycle guard rejects injected ${source}`, () => {
    assert.throws(() => assertNoLifecycleAuthority(source, 'features/experiments/rules.ts'), /lifecycle authority/)
  })

test('architecture guard also checks ordinary Vue script blocks', () => {
  assert.throws(() => assertFeatureDependencies(
    '<script lang="ts">import Page from "../../germination/pages/Private.vue"</script>',
    'features/experiments/pages/Any.vue'), /private feature/)
})

test('visibility and backend completion-check responses are not a second state machine', () => {
  assertNoLifecycleAuthority('const canSave = status === "active"; if (data.can_complete) submit()', 'ui.ts')
})

test('static UI registry has exactly one frozen GER capability with authoritative metadata', () => {
  assert.deepEqual(Object.keys(experimentUiRegistry), ['GER'])
  const entry = resolveExperimentUi('GER')
  assert.equal(entry.code, 'GER')
  assert.equal(entry.label, '种子萌发试验')
  const backend = readFileSync(new URL('../../backend/app/core/experiment_types.py', import.meta.url), 'utf8')
  assert.ok(backend.includes(`"${entry.code}": "${entry.label}"`))
  assert.ok(Object.isFrozen(experimentUiRegistry) && Object.isFrozen(entry))
  assert.throws(() => { experimentUiRegistry.UNKNOWN = entry }, TypeError)
  assert.equal('register' in experimentUiRegistry, false)
  assert.deepEqual(Object.keys(entry), ['code', 'label', 'create', 'configuration', 'execution', 'executionPath'])
  for (const [capability, file] of [['create', 'ExperimentWizardView.vue'],
    ['configuration', 'ExperimentDesignDetailView.vue'], ['execution', 'GerminationExecutionView.vue']]) {
    assert.ok(entry[capability].toString().includes(file))
    assert.ok(existsSync(new URL(`features/germination/pages/${file}`, root)))
  }
})

test('unknown, empty and prototype names never silently resolve GER', () => {
  for (const code of ['UNKNOWN', '', '__proto__', 'constructor', 'ger']) {
    assert.equal(resolveExperimentUi(code), undefined)
    assert.equal(experimentTarget({ id: 'x', status: 'active', experiment_type: code }), '/experiments/x')
  }
  assert.equal(experimentTarget({ id: 'x', status: 'active', experiment_type: 'GER' }), '/experiments/x/germination')
  for (const status of ['draft', 'ready', 'completed', 'cancelled'])
    assert.equal(experimentTarget({ id: 'x', status, experiment_type: 'GER' }), '/experiments/x')
})

test('creation and both workflow modes resolve API type before rendering a public capability', () => {
  const create = read('features/experiments/pages/ExperimentCreateView.vue')
  const workflow = read('features/experiments/pages/ExperimentWorkflowView.vue')
  assert.match(create, /getExperimentTypes\(\)/)
  assert.match(create, /resolveExperimentUi\(types.value\[0\]\?\.value/)
  assert.match(create, /if \(ui\) page.value = defineAsyncComponent\(ui.create\)/)
  assert.match(workflow, /getExperiment\(id\)/)
  assert.match(workflow, /resolveExperimentUi\(data.experiment_type\)/)
  assert.match(workflow, /if \(ui\) page.value = defineAsyncComponent\(ui\[mode\]\)/)
  assert.match(workflow, /watch\(\(\) => \[String\(route.params.id\), props.mode\]/)
  for (const source of [create, workflow]) {
    assert.match(source, /UnavailableExperiment v-else-if="unavailable"/)
    assert.doesNotMatch(source, /germinationUi|\|\|\s*.*GER/)
  }
})
