import { beforeEach, describe, expect, it, vi } from 'vitest'

// The mutator reads API_BASE_URL at call time via the shared `api` module.
// With the default base URL of "/api/v1", generated Orval URLs that already
// contain "/api/v1/..." must be de-duplicated so requests don't resolve to
// "/api/v1/api/v1/...".
vi.mock('@/lib/api', () => {
  const api = vi.fn().mockResolvedValue({ data: { ok: true } })
  return { api, API_BASE_URL: '/api/v1' }
})

import { api } from '@/lib/api'
import { customInstance } from '@/api/mutator'

const mockedApi = api as unknown as ReturnType<typeof vi.fn>

describe('Orval customInstance URL normalization', () => {
  beforeEach(() => {
    mockedApi.mockClear()
  })

  it('strips a duplicate /api/v1 prefix baked into generated URLs', async () => {
    await customInstance({ url: '/api/v1/studies', method: 'GET' })
    expect(mockedApi).toHaveBeenCalledTimes(1)
    expect(mockedApi.mock.calls[0][0].url).toBe('/studies')
  })

  it('preserves nested path segments after stripping the prefix', async () => {
    await customInstance({ url: '/api/v1/studies/abc/versions', method: 'GET' })
    expect(mockedApi.mock.calls[0][0].url).toBe('/studies/abc/versions')
  })

  it('leaves URLs without the prefix untouched', async () => {
    await customInstance({ url: '/auth/me', method: 'GET' })
    expect(mockedApi.mock.calls[0][0].url).toBe('/auth/me')
  })

  it('does not strip a path that merely starts with a similar segment', async () => {
    // "/api/v1studies" is not "/api/v1/..." so it must be left as-is.
    await customInstance({ url: '/api/v1studies', method: 'GET' })
    expect(mockedApi.mock.calls[0][0].url).toBe('/api/v1studies')
  })
})
