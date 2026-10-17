import axios, {
  AxiosError,
  type AxiosAdapter,
  type AxiosResponse,
  type InternalAxiosRequestConfig,
} from 'axios'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, getApiErrorMessage } from '@/lib/api'

function response(
  config: InternalAxiosRequestConfig,
  status: number,
  data: unknown,
): AxiosResponse {
  return {
    config,
    data,
    headers: {},
    status,
    statusText: status === 401 ? 'Unauthorized' : 'OK',
  }
}

describe('API authentication lifecycle', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
  })

  it('attaches the current bearer token to mutation requests', async () => {
    localStorage.setItem('access_token', 'subject-token')
    const adapter: AxiosAdapter = async (config) => response(config, 200, { ok: true })

    const result = await api.post('/studies/study-1/subjects', { site_id: 'site-1' }, { adapter })

    expect(result.config.headers.Authorization).toBe('Bearer subject-token')
  })

  it('uses one refresh for simultaneous 401 responses and retries both requests', async () => {
    localStorage.setItem('access_token', 'expired-token')
    localStorage.setItem('refresh_token', 'rotating-refresh-token')
    localStorage.setItem('auth_provider', 'local')

    let resolveRefresh!: (value: { data: { access_token: string; refresh_token: string } }) => void
    const refreshResult = new Promise<{ data: { access_token: string; refresh_token: string } }>((resolve) => {
      resolveRefresh = resolve
    })
    const refresh = vi.spyOn(axios, 'post').mockReturnValue(refreshResult as never)
    let unauthorizedResponses = 0
    const adapter: AxiosAdapter = async (config) => {
      if (config.headers.Authorization === 'Bearer expired-token') {
        unauthorizedResponses += 1
        throw new AxiosError(
          'Authentication required',
          'ERR_BAD_REQUEST',
          config,
          undefined,
          response(config, 401, { error: { code: 'AuthenticationError', message: 'Missing authentication credentials' } }),
        )
      }
      return response(config, 200, { ok: true })
    }

    const requests = [
      api.get('/studies/study-1/subjects', { adapter }),
      api.post('/studies/study-1/subjects', { site_id: 'site-1' }, { adapter }),
    ]

    while (unauthorizedResponses < 2) {
      await Promise.resolve()
    }
    await vi.waitFor(() => expect(refresh).toHaveBeenCalledTimes(1))
    resolveRefresh({ data: { access_token: 'fresh-token', refresh_token: 'fresh-refresh-token' } })

    const results = await Promise.all(requests)
    expect(results.map((item) => item.config.headers.Authorization)).toEqual([
      'Bearer fresh-token',
      'Bearer fresh-token',
    ])
    expect(localStorage.getItem('access_token')).toBe('fresh-token')
    expect(localStorage.getItem('refresh_token')).toBe('fresh-refresh-token')
  })

  it('reads the shared backend error envelope without exposing raw payloads', () => {
    const config = { headers: {} } as InternalAxiosRequestConfig
    const error = new AxiosError(
      'Request failed',
      'ERR_BAD_REQUEST',
      config,
      undefined,
      response(config, 401, { error: { message: 'Missing authentication credentials' } }),
    )

    expect(getApiErrorMessage(error, 'Fallback')).toBe('Missing authentication credentials')
    expect(getApiErrorMessage(new Error('internal detail'), 'Fallback')).toBe('Fallback')
  })
})
