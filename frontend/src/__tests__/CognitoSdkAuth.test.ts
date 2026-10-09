import { beforeEach, describe, expect, it, vi } from 'vitest'

// Shared handles to the CognitoUser mocks so each test can drive the SDK
// callbacks (onSuccess / onFailure / challenges and their completions)
// deterministically.
const authenticateUser = vi.fn()
const sendMFACode = vi.fn()
const completeNewPasswordChallenge = vi.fn()

vi.mock('amazon-cognito-identity-js', () => {
  class CognitoUserPool {}
  class CognitoUser {
    authenticateUser = authenticateUser
    sendMFACode = sendMFACode
    completeNewPasswordChallenge = completeNewPasswordChallenge
  }
  class AuthenticationDetails {}
  return { CognitoUserPool, CognitoUser, AuthenticationDetails }
})

const FIXED_EXPIRATION = 2_000_000_000

function fakeSession() {
  return {
    getAccessToken: () => ({
      getJwtToken: () => 'access-jwt',
      getExpiration: () => FIXED_EXPIRATION,
    }),
    getRefreshToken: () => ({ getToken: () => 'refresh-jwt' }),
    getIdToken: () => ({
      getJwtToken: () => 'id-jwt',
      getExpiration: () => FIXED_EXPIRATION,
    }),
  }
}

async function importModule() {
  return import('@/lib/cognito-sdk')
}

function stubConfigured() {
  vi.stubEnv('VITE_COGNITO_REGION', 'us-east-1')
  vi.stubEnv('VITE_COGNITO_USER_POOL_ID', 'us-east-1_pool')
  vi.stubEnv('VITE_COGNITO_CLIENT_ID', 'client-123')
}

describe('Cognito SDK (SRP) authentication', () => {
  beforeEach(() => {
    vi.resetModules()
    vi.unstubAllEnvs()
    authenticateUser.mockReset()
    sendMFACode.mockReset()
    completeNewPasswordChallenge.mockReset()
  })

  it('is not configured when the env vars are unset', async () => {
    vi.stubEnv('VITE_COGNITO_REGION', '')
    vi.stubEnv('VITE_COGNITO_USER_POOL_ID', '')
    vi.stubEnv('VITE_COGNITO_CLIENT_ID', '')
    const { isCognitoSdkConfigured } = await importModule()
    expect(isCognitoSdkConfigured()).toBe(false)
  })

  it('is configured when region, pool id, and client id are present', async () => {
    stubConfigured()
    const { isCognitoSdkConfigured } = await importModule()
    expect(isCognitoSdkConfigured()).toBe(true)
  })

  it('sends the ID token as the Bearer access_token and returns refresh/id tokens', async () => {
    stubConfigured()
    authenticateUser.mockImplementation((_details, callbacks) => {
      callbacks.onSuccess(fakeSession())
    })

    const { signInWithCognito } = await importModule()
    const result = await signInWithCognito('user@example.com', 'secret')

    expect(result.status).toBe('SUCCESS')
    if (result.status !== 'SUCCESS') throw new Error('expected SUCCESS')
    // The ID token is the Bearer credential: it carries the verified email/name
    // claims the backend needs for just-in-time provisioning on first login.
    expect(result.tokens.access_token).toBe('id-jwt')
    expect(result.tokens.access_token).not.toBe('access-jwt')
    expect(result.tokens.refresh_token).toBe('refresh-jwt')
    expect(result.tokens.id_token).toBe('id-jwt')
    expect(result.tokens.token_type).toBe('Bearer')
    expect(typeof result.tokens.expires_in).toBe('number')
  })

  it('rejects with a CognitoSignInError when authentication fails', async () => {
    stubConfigured()
    authenticateUser.mockImplementation((_details, callbacks) => {
      callbacks.onFailure(new Error('Incorrect username or password.'))
    })

    const { signInWithCognito, CognitoSignInError } = await importModule()
    await expect(signInWithCognito('user@example.com', 'bad')).rejects.toBeInstanceOf(
      CognitoSignInError,
    )
    await expect(signInWithCognito('user@example.com', 'bad')).rejects.toMatchObject({
      code: 'AUTH_FAILED',
    })
  })

  it('surfaces an SMS MFA challenge and completes it to tokens with the ID token as Bearer', async () => {
    stubConfigured()
    authenticateUser.mockImplementation((_details, callbacks) => {
      callbacks.mfaRequired('SMS_MFA', {})
    })
    sendMFACode.mockImplementation((_code, callbacks) => {
      callbacks.onSuccess(fakeSession())
    })

    const { signInWithCognito } = await importModule()
    const challenge = await signInWithCognito('user@example.com', 'secret')

    expect(challenge.status).toBe('MFA_REQUIRED')
    if (challenge.status !== 'MFA_REQUIRED') throw new Error('expected MFA_REQUIRED')
    expect(challenge.mfaType).toBe('SMS_MFA')

    const completed = await challenge.respond('123456')
    expect(completed.status).toBe('SUCCESS')
    if (completed.status !== 'SUCCESS') throw new Error('expected SUCCESS')
    expect(completed.tokens.access_token).toBe('id-jwt')
    // SMS MFA must NOT pass a mfaType third argument (defaults to SMS_MFA).
    expect(sendMFACode).toHaveBeenCalledTimes(1)
    expect(sendMFACode.mock.calls[0][0]).toBe('123456')
    expect(sendMFACode.mock.calls[0][2]).toBeUndefined()
  })

  it('surfaces a TOTP challenge and sends SOFTWARE_TOKEN_MFA on completion', async () => {
    stubConfigured()
    authenticateUser.mockImplementation((_details, callbacks) => {
      callbacks.totpRequired('SOFTWARE_TOKEN_MFA', {})
    })
    sendMFACode.mockImplementation((_code, callbacks) => {
      callbacks.onSuccess(fakeSession())
    })

    const { signInWithCognito } = await importModule()
    const challenge = await signInWithCognito('user@example.com', 'secret')

    expect(challenge.status).toBe('MFA_REQUIRED')
    if (challenge.status !== 'MFA_REQUIRED') throw new Error('expected MFA_REQUIRED')
    expect(challenge.mfaType).toBe('SOFTWARE_TOKEN_MFA')

    const completed = await challenge.respond('654321')
    expect(completed.status).toBe('SUCCESS')
    expect(sendMFACode).toHaveBeenCalledTimes(1)
    expect(sendMFACode.mock.calls[0][2]).toBe('SOFTWARE_TOKEN_MFA')
  })

  it('rejects a CognitoSignInError when the MFA code is wrong', async () => {
    stubConfigured()
    authenticateUser.mockImplementation((_details, callbacks) => {
      callbacks.mfaRequired('SMS_MFA', {})
    })
    sendMFACode.mockImplementation((_code, callbacks) => {
      callbacks.onFailure(new Error('Invalid code'))
    })

    const { signInWithCognito, CognitoSignInError } = await importModule()
    const challenge = await signInWithCognito('user@example.com', 'secret')
    if (challenge.status !== 'MFA_REQUIRED') throw new Error('expected MFA_REQUIRED')

    await expect(challenge.respond('000000')).rejects.toBeInstanceOf(CognitoSignInError)
    await expect(challenge.respond('000000')).rejects.toMatchObject({ code: 'AUTH_FAILED' })
  })

  it('surfaces NEW_PASSWORD_REQUIRED and strips read-only attributes on completion', async () => {
    stubConfigured()
    authenticateUser.mockImplementation((_details, callbacks) => {
      callbacks.newPasswordRequired(
        {
          email: 'user@example.com',
          email_verified: 'true',
          phone_number_verified: 'false',
          phone_number: '+15555550100',
          custom: 'keep-me',
        },
        [],
      )
    })
    completeNewPasswordChallenge.mockImplementation((_pw, _attrs, callbacks) => {
      callbacks.onSuccess(fakeSession())
    })

    const { signInWithCognito } = await importModule()
    const challenge = await signInWithCognito('user@example.com', 'secret')

    expect(challenge.status).toBe('NEW_PASSWORD_REQUIRED')
    if (challenge.status !== 'NEW_PASSWORD_REQUIRED') throw new Error('expected NEW_PASSWORD_REQUIRED')

    const completed = await challenge.respond('NewPass123')
    expect(completed.status).toBe('SUCCESS')
    if (completed.status !== 'SUCCESS') throw new Error('expected SUCCESS')
    expect(completed.tokens.access_token).toBe('id-jwt')

    expect(completeNewPasswordChallenge).toHaveBeenCalledTimes(1)
    const passedAttributes = completeNewPasswordChallenge.mock.calls[0][1]
    expect(passedAttributes).toEqual({ custom: 'keep-me' })
    expect(passedAttributes).not.toHaveProperty('email')
    expect(passedAttributes).not.toHaveProperty('email_verified')
    expect(passedAttributes).not.toHaveProperty('phone_number')
    expect(passedAttributes).not.toHaveProperty('phone_number_verified')
  })

  it('exposes a standalone attribute sanitizer that drops the read-only keys', async () => {
    stubConfigured()
    const { sanitizeNewPasswordAttributes } = await importModule()
    expect(
      sanitizeNewPasswordAttributes({
        email: 'a@b.c',
        email_verified: 'true',
        phone_number: '+1',
        phone_number_verified: 'false',
        given_name: 'Ada',
      }),
    ).toEqual({ given_name: 'Ada' })
  })
})
