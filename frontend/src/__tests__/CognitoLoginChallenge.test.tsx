import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { LoginPage } from '@/features/auth/LoginPage'
import { CognitoSignInError } from '@/lib/cognito-sdk'
import type { CognitoSignInResult } from '@/lib/cognito-sdk'

const { mockNavigate, mockSearch } = vi.hoisted(() => ({
  mockNavigate: vi.fn(),
  mockSearch: vi.fn(() => ({})),
}))

vi.mock('@tanstack/react-router', () => ({
  useNavigate: () => mockNavigate,
  useSearch: () => mockSearch(),
}))

const { signInWithCognito, isCognitoSdkConfigured } = vi.hoisted(() => ({
  signInWithCognito: vi.fn(),
  isCognitoSdkConfigured: vi.fn(() => true),
}))

vi.mock('@/lib/cognito-sdk', async () => {
  const actual = await vi.importActual<typeof import('@/lib/cognito-sdk')>('@/lib/cognito-sdk')
  return {
    ...actual,
    signInWithCognito,
    isCognitoSdkConfigured,
  }
})

const completeCognitoLogin = vi.fn().mockResolvedValue(undefined)

vi.mock('@/lib/auth', () => ({
  useAuthStore: Object.assign(
    (selector: (state: unknown) => unknown) =>
      selector({ login: vi.fn(), isLoading: false }),
    { getState: () => ({ completeCognitoLogin }) },
  ),
}))

vi.mock('@/lib/cognito', () => ({
  isCognitoConfigured: () => false,
  buildCognitoAuthorizeUrl: vi.fn(),
}))

const tokens = {
  access_token: 'access-jwt',
  refresh_token: 'refresh-jwt',
  id_token: 'id-jwt',
  token_type: 'Bearer',
  expires_in: 3600,
}

function submitCredentials() {
  fireEvent.change(screen.getByLabelText(/Email/), { target: { value: 'user@example.com' } })
  fireEvent.change(screen.getByLabelText(/^Password/), { target: { value: 'secret' } })
  fireEvent.click(screen.getByRole('button', { name: 'Sign In' }))
}

describe('LoginPage Cognito SDK challenge flow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSearch.mockReturnValue({})
    isCognitoSdkConfigured.mockReturnValue(true)
  })

  it('surfaces the SMS MFA field, completes it, and finishes login', async () => {
    const respond = vi.fn<(code: string) => Promise<CognitoSignInResult>>().mockResolvedValue({
      status: 'SUCCESS',
      tokens,
    })
    signInWithCognito.mockResolvedValue({ status: 'MFA_REQUIRED', mfaType: 'SMS_MFA', respond })

    render(<LoginPage />)
    submitCredentials()

    const mfaField = await screen.findByLabelText(/SMS code/)
    expect(mfaField).toBeInTheDocument()

    fireEvent.change(mfaField, { target: { value: '123456' } })
    fireEvent.click(screen.getByRole('button', { name: 'Verify Code' }))

    await waitFor(() => expect(respond).toHaveBeenCalledWith('123456'))
    await waitFor(() => expect(completeCognitoLogin).toHaveBeenCalledWith(tokens))
    expect(mockNavigate).toHaveBeenCalledWith({ to: '/' })
  })

  it('labels the field for an authenticator (TOTP) challenge', async () => {
    const respond = vi.fn().mockResolvedValue({ status: 'SUCCESS', tokens })
    signInWithCognito.mockResolvedValue({
      status: 'MFA_REQUIRED',
      mfaType: 'SOFTWARE_TOKEN_MFA',
      respond,
    })

    render(<LoginPage />)
    submitCredentials()

    expect(await screen.findByLabelText(/Authenticator code/)).toBeInTheDocument()
  })

  it('surfaces the new-password form, validates it, and completes login', async () => {
    const respond = vi.fn().mockResolvedValue({ status: 'SUCCESS', tokens })
    signInWithCognito.mockResolvedValue({ status: 'NEW_PASSWORD_REQUIRED', respond })

    render(<LoginPage />)
    submitCredentials()

    const newPassword = await screen.findByLabelText(/New Password/)
    const confirm = screen.getByLabelText(/Confirm Password/)

    // Mismatch shows the zod error and does not call respond.
    fireEvent.change(newPassword, { target: { value: 'NewPass123' } })
    fireEvent.change(confirm, { target: { value: 'Mismatch123' } })
    fireEvent.click(screen.getByRole('button', { name: 'Set New Password' }))
    expect(await screen.findByText('Passwords do not match')).toBeInTheDocument()
    expect(respond).not.toHaveBeenCalled()

    // Matching passwords complete the challenge.
    fireEvent.change(confirm, { target: { value: 'NewPass123' } })
    fireEvent.click(screen.getByRole('button', { name: 'Set New Password' }))

    await waitFor(() => expect(respond).toHaveBeenCalledWith('NewPass123'))
    await waitFor(() => expect(completeCognitoLogin).toHaveBeenCalledWith(tokens))
    expect(mockNavigate).toHaveBeenCalledWith({ to: '/' })
  })

  it('shows the error alert and keeps the MFA UI when the code is rejected', async () => {
    const respond = vi
      .fn()
      .mockRejectedValue(new CognitoSignInError('AUTH_FAILED', 'Invalid code'))
    signInWithCognito.mockResolvedValue({ status: 'MFA_REQUIRED', mfaType: 'SMS_MFA', respond })

    render(<LoginPage />)
    submitCredentials()

    const mfaField = await screen.findByLabelText(/SMS code/)
    fireEvent.change(mfaField, { target: { value: '000000' } })
    fireEvent.click(screen.getByRole('button', { name: 'Verify Code' }))

    expect(await screen.findByText('Invalid code')).toBeInTheDocument()
    expect(screen.getByLabelText(/SMS code/)).toBeInTheDocument()
    expect(completeCognitoLogin).not.toHaveBeenCalled()
  })
})
