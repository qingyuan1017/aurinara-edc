import { create } from 'zustand'
import { api } from './api'

/**
 * Represents the current authenticated user and their authorization scope.
 */
export interface CurrentUser {
  id: string
  email: string
  first_name: string
  last_name: string
  roles: UserRoleAssignment[]
  permissions: string[]
}

export interface UserRoleAssignment {
  role_id?: string
  role_name: string
  scope_level?: string
  permissions?: string[]
  study_id?: string
  site_id?: string
}

/** Adapt the API's role-scoped permissions to the flat shape used by the UI. */
function normalizeCurrentUser(user: Omit<CurrentUser, 'permissions'> & { permissions?: string[] }): CurrentUser {
  const permissions = user.roles.flatMap((role) => role.permissions ?? [])
  return {
    ...user,
    permissions: [...new Set(user.permissions ?? permissions)],
  }
}

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
}

interface AuthState {
  user: CurrentUser | null
  isAuthenticated: boolean
  isLoading: boolean

  login: (email: string, password: string, mfaCode?: string) => Promise<void>
  logout: () => Promise<void>
  refreshUser: () => Promise<void>
  setUser: (user: CurrentUser | null) => void
}

/**
 * Auth store — manages session state, login/logout, and current user.
 * Frontend checks are convenience only; the server is authoritative.
 */
export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  isAuthenticated: !!localStorage.getItem('access_token'),
  isLoading: false,

  login: async (email, password, mfaCode) => {
    set({ isLoading: true })
    try {
      const { data } = await api.post<TokenPair>('/auth/login', {
        email,
        password,
        mfa_code: mfaCode,
      })
      localStorage.setItem('access_token', data.access_token)
      localStorage.setItem('refresh_token', data.refresh_token)
      set({ isAuthenticated: true })

      // Fetch full user profile after login
      const { data: user } = await api.get<CurrentUser>('/auth/me')
      set({ user: normalizeCurrentUser(user) })
    } finally {
      set({ isLoading: false })
    }
  },

  logout: async () => {
    try {
      const refreshToken = localStorage.getItem('refresh_token')
      if (refreshToken) {
        await api.post('/auth/logout', { refresh_token: refreshToken })
      }
    } finally {
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
      set({ user: null, isAuthenticated: false })
    }
  },

  refreshUser: async () => {
    set({ isLoading: true })
    try {
      const { data } = await api.get<CurrentUser>('/auth/me')
      set({ user: normalizeCurrentUser(data), isAuthenticated: true })
    } catch {
      set({ user: null, isAuthenticated: false })
    } finally {
      set({ isLoading: false })
    }
  },

  setUser: (user) => set({ user, isAuthenticated: !!user }),
}))
