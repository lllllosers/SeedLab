import assert from 'node:assert/strict'
import test from 'node:test'
import { existsSync, readFileSync } from 'node:fs'
import { createMemoryHistory, createRouter } from 'vue-router'
import { routes } from '../src/app/routes.ts'
import { experimentRoutes } from '../src/features/experiments/routes.ts'

const contracts = [
  ['/login', undefined, 'LoginView.vue'], ['/setup', undefined, 'SetupView.vue'],
  ['/change-password', undefined, 'ChangePasswordView.vue'],
  ['/', 'dashboard', 'DashboardView.vue'], ['/taxa', 'taxa', 'TaxaView.vue'],
  ['/taxa/:id', 'taxon-detail', 'TaxonDetailView.vue'], ['/seed-lots', 'seed-lots', 'SeedLotsView.vue'],
  ['/experiments', 'experiments', 'ExperimentsView.vue'],
  ['/experiments/new', 'experiment-new', 'ExperimentCreateView.vue'],
  ['/experiments/:id', 'experiment-detail', 'ExperimentWorkflowView.vue'],
  ['/experiments/:id/germination', 'experiment-germination', 'ExperimentWorkflowView.vue'],
  ['/data', 'data', 'DataView.vue'], ['/audit', 'audit', 'AuditView.vue'], ['/users', 'users', 'UsersView.vue'],
]

const stub = { render: () => null }
const stubbed = records => records.map(record => ({ ...record,
  component: record.component ? stub : undefined,
  children: record.children ? stubbed(record.children) : undefined }))

test('all existing paths, names, hierarchy, admin flag and catch-all stay unchanged', () => {
  const router = createRouter({ history: createMemoryHistory(), routes: stubbed(routes) })
  const actual = router.getRoutes().filter(route => route.name || ['/login', '/setup', '/change-password'].includes(route.path))
    .map(route => [route.path, route.name]).sort()
  assert.deepEqual(actual, contracts.map(([path, name]) => [path, name]).sort())
  assert.equal(routes.find(route => route.path === '/').children.length, 11)
  assert.equal(router.resolve('/users').meta.admin, true)
  assert.equal(routes.at(-1).path, '/:pathMatch(.*)*')
  assert.equal(routes.at(-1).redirect, '/')
})

for (const [url, name] of contracts) test(`direct navigation and fresh router resolve ${url}`, async () => {
  const target = url.replace(':id', 'sample-id') + (url.includes('germination') ? '?tab=measurement' : '')
  for (let refresh = 0; refresh < 2; refresh++) {
    const router = createRouter({ history: createMemoryHistory(), routes: stubbed(routes) })
    await router.push(target)
    await router.isReady()
    assert.equal(router.currentRoute.value.path, target.split('?')[0])
    assert.equal(router.currentRoute.value.name, name)
    if (target.includes('?')) assert.deepEqual(router.currentRoute.value.query, { tab: 'measurement' })
  }
})

test('unknown URL still redirects to dashboard', async () => {
  const router = createRouter({ history: createMemoryHistory(), routes: stubbed(routes) })
  await router.push('/unknown-path')
  assert.equal(router.currentRoute.value.path, '/')
  assert.equal(router.currentRoute.value.name, 'dashboard')
})

test('lazy page resolution points to real files and workflow modes dispatch correctly', () => {
  const visit = records => records.forEach(route => {
    if (route.component) {
      const spec = route.component.toString().match(/import\(['"]([^'"]+)['"]\)/)?.[1]
      assert.ok(spec, route.path)
      const base = experimentRoutes.includes(route) ? '../src/features/experiments/routes.ts' : '../src/app/routes.ts'
      assert.ok(existsSync(new URL(spec, new URL(base, import.meta.url))), `${route.path}: ${spec}`)
    }
    if (route.children) visit(route.children)
  })
  visit(routes)
  const detail = experimentRoutes.find(route => route.name === 'experiment-detail')
  const execution = experimentRoutes.find(route => route.name === 'experiment-germination')
  assert.deepEqual(detail.props, { mode: 'configuration' })
  assert.deepEqual(execution.props, { mode: 'execution' })
  for (const [path, , file] of contracts) {
    const records = [...routes, ...routes.find(route => route.path === '/').children]
    const record = path === '/' ? records.find(route => route.name === 'dashboard')
      : records.find(route => route.path === path || `/${route.path}` === path)
    assert.ok(record.component.toString().includes(file), `${path}: ${file}`)
  }
  const guard = readFileSync(new URL('../src/router/index.ts', import.meta.url), 'utf8')
  assert.match(guard, /createWebHistory\(\)/)
  for (const condition of ['auth.restore()', 'auth.user.must_change_password', 'to.meta.admin', "'/setup/status'"])
    assert.ok(guard.includes(condition))
})
