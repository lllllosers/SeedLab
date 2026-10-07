import type { RouteRecordRaw } from 'vue-router'
import { experimentRoutes } from '../features/experiments/index.ts'

export const routes: RouteRecordRaw[] = [
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
        ...experimentRoutes,
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
  ]
