import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api, getRefreshEndpoint } from '@/lib/api'
import { useAuthStore } from '@/lib/auth'
import {
  buildCognitoAuthorizeUrl,
  consumeCognitoCallbackState,
  isCognitoConfigured,
} from '@/lib/cognito'

describe('Cognito browser authentication', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    vi.unstubAllEnvs()
    useAuthStore.setState({ user: null, isAuthenticated: false, isLoading: false })
  })

  it('keeps local authentication fallback when Cognito is not configured', () => {
    expect(isCognitoConfigured()).toBe(false)
    expect(getRefreshEndpoint()).toBe('/api/v1/auth/refresh')
  })

  it('builds a stateful PKCE Hosted UI redirect without a client secret', async () => {
    vi.stubEnv('VITE_COGNITO_DOMAIN', 'example.auth.us-east-1.amazoncognito.com')
    vi.stubEnv('VITE_COGNITO_CLIENT_ID', 'public-client')
    vi.stubEnv('VITE_COGNITO_REDIRECT_URI', 'http://localhost:5173/auth/callback')
    const url = new URL(await buildCognitoAuthorizeUrl())
    expect(url.origin).toBe('https://example.auth.us-east-1.amazoncognito.com')
    expect(url.pathname).toBe('/oauth2/authorize')
    expect(url.searchParams.get('client_id')).toBe('public-client')
    expect(url.searchParams.get('response_type')).toBe('code')
    expect(url.searchParams.get('code_challenge_method')).toBe('S256')
    expect(url.searchParams.get('state')).toBe(sessionStorage.getItem('cognito_oauth_state'))
    expect(sessionStorage.getItem('cognito_pkce_verifier')).toBeTruthy()
  })

  it('rejects callback state mismatches and consumes valid state once', async () => {
    vi.stubEnv('VITE_COGNITO_DOMAIN', 'example.auth.us-east-1.amazoncognito.com')
    vi.stubEnv('VITE_COGNITO_CLIENT_ID', 'public-client')
    vi.stubEnv('VITE_COGNITO_REDIRECT_URI', 'http://localhost:5173/auth/callback')
    await buildCognitoAuthorizeUrl()
    expect(() => consumeCognitoCallbackState('wrong-state')).toThrow()
    await buildCognitoAuthorizeUrl()
    const validState = sessionStorage.getItem('cognito_oauth_state')
    expect(consumeCognitoCallbackState(validState)).toBeTruthy()
    expect(() => consumeCognitoCallbackState(validState)).toThrow()
  })

  it('never routes Cognito refresh tokens to local refresh', () => {
    localStorage.setItem('auth_provider', 'cognito')
    expect(getRefreshEndpoint()).toBe('/api/v1/auth/cognito/refresh')
  })

  it('stores Cognito tokens and loads authoritative /auth/me', async () => {
    const get = vi.spyOn(api, 'get').mockResolvedValue({
      data: {
        id: 'user-1', email: 'user@example.com', first_name: 'Test', last_name: 'User', roles: [],
      },
      status: 200, statusText: 'OK', headers: {}, config: {},
    })
    await useAuthStore.getState().completeCognitoLogin({
      access_token: 'access', refresh_token: 'refresh', id_token: 'id',
    })
    expect(localStorage.getItem('auth_provider')).toBe('cognito')
    expect(localStorage.getItem('access_token')).toBe('access')
    expect(get).toHaveBeenCalledWith('/auth/me')
    expect(useAuthStore.getState().isAuthenticated).toBe(true)
    get.mockRestore()
  })
})
