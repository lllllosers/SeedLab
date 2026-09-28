import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '../stores/auth'
import { api } from '../api/client'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: () => import('../views/LoginView.vue') },
    { path: '/setup', component: () => import('../views/SetupView.vue') },
    { path: '/change-password', component: () => import('../views/ChangePasswordView.vue') },
    {
      path: '/',
      component: () => import('../layouts/AppLayout.vue'),
      children: [
        { path: '', name: 'dashboard', component: () => import('../views/DashboardView.vue') },
        { path: 'taxa', name: 'taxa', component: () => import('../views/TaxaView.vue') },
        {
          path: 'taxa/:id',
          name: 'taxon-detail',
          component: () => import('../views/TaxonDetailView.vue'),
        },
        {
          path: 'seed-lots',
          name: 'seed-lots',
          component: () => import('../views/SeedLotsView.vue'),
        },
        {
          path: 'experiments',
          name: 'experiments',
          component: () => import('../views/ExperimentsView.vue'),
        },
        {
          path: 'experiments/new',
          name: 'experiment-new',
          component: () => import('../views/ExperimentWizardView.vue'),
        },
        {
          path: 'experiments/:id',
          name: 'experiment-detail',
          component: () => import('../views/ExperimentDesignDetailView.vue'),
        },
        {
          path: 'experiments/:id/germination',
          name: 'experiment-germination',
          component: () => import('../views/GerminationExecutionView.vue'),
        },
        { path: 'data', name: 'data', component: () => import('../views/DataView.vue') },
        { path: 'audit', name: 'audit', component: () => import('../views/AuditView.vue') },
        {
          path: 'users',
          name: 'users',
          component: () => import('../views/UsersView.vue'),
          meta: { admin: true },
        },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuth()
  if (to.path === '/setup') {
    const { data } = await api.get<{ initialized: boolean }>('/setup/status')
    return data.initialized ? '/login' : true
  }
  if (!auth.ready) await auth.restore()
  if (to.path === '/login')
    return auth.user ? (auth.user.must_change_password ? '/change-password' : '/') : true
  if (!auth.user) return '/login'
  if (auth.user.must_change_password && to.path !== '/change-password') return '/change-password'
  if (to.meta.admin && !auth.user.is_admin) return '/'
})

export default router
