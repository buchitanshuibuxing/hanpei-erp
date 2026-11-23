import { defineStore } from 'pinia'

export const useAuth = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem('erp_token') || '',
    user: JSON.parse(localStorage.getItem('erp_user') || 'null'),
    scope: localStorage.getItem('erp_scope') || 'internal',
  }),
  getters: {
    logged: (s) => !!s.token,
    role: (s) => s.user?.role || '',
    permissions: (s) => s.user?.permissions || {},
  },
  actions: {
    save(data) {
      this.token = data.token
      this.user = data.user
      this.scope = data.scope || 'internal'
      localStorage.setItem('erp_token', data.token)
      localStorage.setItem('erp_user', JSON.stringify(data.user))
      localStorage.setItem('erp_scope', this.scope)
    },
    clear() {
      this.token = ''
      this.user = null
      this.scope = 'internal'
      localStorage.removeItem('erp_token')
      localStorage.removeItem('erp_user')
      localStorage.removeItem('erp_scope')
    },
    can(module, action = 'view') {
      if (['ADMIN', 'MANAGER'].includes(this.role)) return true
      return (this.permissions[module] || []).includes(action)
    },
  },
})
