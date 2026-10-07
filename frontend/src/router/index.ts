import { createRouter, createWebHistory } from 'vue-router'
import { routes } from '../app/routes'
import { useAuth } from '../stores/auth'
import { api } from '../shared/api/client'

const router = createRouter({
  history: createWebHistory(),
  routes,
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
