import { defineStore } from 'pinia'
import { api, setCsrfToken } from '../api/client'
import type { User } from '../types'

interface AuthResult {
  user: User
  csrf_token: string
}

export const useAuth = defineStore('auth', {
  state: () => ({ user: null as User | null, ready: false }),
  actions: {
    async restore() {
      try {
        const { data } = await api.get<AuthResult>('/auth/me')
        this.user = data.user
        setCsrfToken(data.csrf_token)
      } catch {
        this.user = null
        setCsrfToken('')
      } finally {
        this.ready = true
      }
    },
    async login(username: string, password: string) {
      const { data } = await api.post<AuthResult>('/auth/login', { username, password })
      this.user = data.user
      setCsrfToken(data.csrf_token)
      this.ready = true
    },
    async logout() {
      await api.post('/auth/logout')
      this.user = null
      setCsrfToken('')
    },
  },
})
