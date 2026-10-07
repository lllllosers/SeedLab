import type { RouteRecordRaw } from 'vue-router'

export const experimentRoutes: RouteRecordRaw[] = [
  { path: 'experiments', name: 'experiments', component: () => import('./pages/ExperimentsView.vue') },
  { path: 'experiments/new', name: 'experiment-new', component: () => import('./pages/ExperimentCreateView.vue') },
  { path: 'experiments/:id', name: 'experiment-detail',
    component: () => import('./pages/ExperimentWorkflowView.vue'), props: { mode: 'configuration' } },
  { path: 'experiments/:id/germination', name: 'experiment-germination',
    component: () => import('./pages/ExperimentWorkflowView.vue'), props: { mode: 'execution' } },
]
