import { createRouter, createWebHistory } from 'vue-router'
import { useAuth } from '../stores/auth'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: () => import('../views/LoginView.vue') },
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
          path: 'experiments/:id',
          name: 'experiment-detail',
          component: () => import('../views/ExperimentDetailView.vue'),
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
  if (!auth.ready) await auth.restore()
  if (to.path === '/login') return auth.user ? '/' : true
  if (!auth.user) return '/login'
  if (to.meta.admin && !auth.user.is_admin) return '/'
})

export default router
