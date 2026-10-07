import { defineStore } from 'pinia'
import { api, setCsrfToken } from '../shared/api/client'
import type { User } from '../types'

interface AuthResult {
  user: User
  csrf_token: string
}

export const useAuth = defineStore('auth', {
  state: () => ({ user: null as User | null, ready: false }),
  actions: {
    apply(result: AuthResult) {
      this.user = result.user
      setCsrfToken(result.csrf_token)
      this.ready = true
    },
    forget() {
      this.user = null
      setCsrfToken('')
      this.ready = true
    },
    async restore() {
      try {
        const { data } = await api.get<AuthResult>('/auth/me')
        this.apply(data)
      } catch {
        this.forget()
      } finally {
        this.ready = true
      }
    },
    async login(username: string, password: string) {
      const { data } = await api.post<AuthResult>('/auth/login', { username, password })
      this.apply(data)
    },
    async logout() {
      await api.post('/auth/logout')
      this.forget()
    },
  },
})
