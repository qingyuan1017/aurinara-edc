import { StrictMode } from 'react'
import { render, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CognitoCallbackPage } from '@/features/auth/CognitoCallbackPage'

const { navigate, consumeState, exchangeCode, completeLogin } = vi.hoisted(() => ({
  navigate: vi.fn().mockResolvedValue(undefined),
  consumeState: vi.fn(),
  exchangeCode: vi.fn(),
  completeLogin: vi.fn().mockResolvedValue(undefined),
}))

vi.mock('@tanstack/react-router', () => ({ useNavigate: () => navigate }))
vi.mock('@/lib/cognito', () => ({
  consumeCognitoCallbackState: consumeState,
  exchangeCognitoCode: exchangeCode,
}))
vi.mock('@/lib/auth', () => ({
  useAuthStore: { getState: () => ({ completeCognitoLogin: completeLogin }) },
}))

describe('CognitoCallbackPage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    window.history.replaceState({}, '', '/auth/cognito/callback?code=test-code&state=test-state')
    consumeState.mockReturnValue({ verifier: 'test-verifier', returnTo: '/studies' })
  })

  it('exchanges the one-time code once and navigates under React Strict Mode', async () => {
    const tokens = { access_token: 'access', refresh_token: 'refresh', id_token: 'id' }
    exchangeCode.mockResolvedValue(tokens)

    render(<StrictMode><CognitoCallbackPage /></StrictMode>)

    await waitFor(() => expect(navigate).toHaveBeenCalledWith({ to: '/studies' }))
    expect(consumeState).toHaveBeenCalledTimes(1)
    expect(consumeState).toHaveBeenCalledWith('test-state')
    expect(exchangeCode).toHaveBeenCalledTimes(1)
    expect(exchangeCode).toHaveBeenCalledWith('test-code', 'test-verifier')
    expect(completeLogin).toHaveBeenCalledTimes(1)
    expect(completeLogin).toHaveBeenCalledWith(tokens)
  })
})
