import {
  AuthenticationDetails,
  CognitoUser,
  CognitoUserPool,
  type CognitoUserSession,
  type IAuthenticationCallback,
} from 'amazon-cognito-identity-js'
import type { CognitoTokenResponse } from './cognito'

/**
 * Direct (SRP) sign-in against AWS Cognito from the app's own login form.
 *
 * This path is independent from the hosted-UI redirect flow in `./cognito`.
 * It performs USER_SRP_AUTH in the browser with the public SPA app client
 * (no client secret) and returns Cognito JWTs in the shape the auth store's
 * `completeCognitoLogin` already expects.
 *
 * Challenge handling (MFA + NEW_PASSWORD_REQUIRED) is encapsulated here: the
 * SDK answers a challenge by calling a method on the SAME `CognitoUser`
 * instance that received the challenge callback, so that instance is captured
 * in a closure and never leaked to the UI. `signInWithCognito` returns a
 * discriminated union; each challenge carries a `respond` callback that
 * resolves to another union member, so a second challenge can chain.
 */

export type CognitoSignInErrorCode =
  | 'NEW_PASSWORD_REQUIRED'
  | 'MFA_REQUIRED'
  | 'AUTH_FAILED'

/** Typed error so LoginPage can surface a clear, user-readable message. */
export class CognitoSignInError extends Error {
  readonly code: CognitoSignInErrorCode

  constructor(code: CognitoSignInErrorCode, message: string) {
    super(message)
    this.name = 'CognitoSignInError'
    this.code = code
  }
}

/** Which MFA factor Cognito challenged with, so the right completion method runs. */
export type CognitoMfaType = 'SMS_MFA' | 'SOFTWARE_TOKEN_MFA'

/**
 * Discriminated union returned by `signInWithCognito` (and by each challenge's
 * `respond`). `SUCCESS` carries the mapped tokens; the challenge members carry
 * a `respond` callback that answers the challenge on the captured `CognitoUser`
 * and resolves to another `CognitoSignInResult`.
 */
export type CognitoSignInResult =
  | { status: 'SUCCESS'; tokens: CognitoTokenResponse }
  | {
      status: 'MFA_REQUIRED'
      mfaType: CognitoMfaType
      respond: (code: string) => Promise<CognitoSignInResult>
    }
  | {
      status: 'NEW_PASSWORD_REQUIRED'
      respond: (newPassword: string) => Promise<CognitoSignInResult>
    }

/**
 * Attributes Cognito echoes back from `newPasswordRequired` but rejects if they
 * are passed to `completeNewPasswordChallenge`. They must be stripped before
 * the challenge is answered.
 */
const READ_ONLY_NEW_PASSWORD_ATTRIBUTES = [
  'email_verified',
  'phone_number_verified',
  'email',
  'phone_number',
] as const

function getSdkConfig() {
  const region = import.meta.env.VITE_COGNITO_REGION?.trim()
  const userPoolId = import.meta.env.VITE_COGNITO_USER_POOL_ID?.trim()
  const clientId = import.meta.env.VITE_COGNITO_CLIENT_ID?.trim()
  return { region, userPoolId, clientId }
}

/** True when region + user pool id + client id env vars are all present. */
export function isCognitoSdkConfigured(): boolean {
  const { region, userPoolId, clientId } = getSdkConfig()
  return Boolean(region && userPoolId && clientId)
}

function mapSession(session: CognitoUserSession): CognitoTokenResponse {
  const idToken = session.getIdToken()
  const nowSeconds = Math.floor(Date.now() / 1000)
  return {
    // The ID token (not the access token) is sent as the Bearer credential.
    // The backend validates both token types, but only the ID token carries the
    // verified `email`/name claims that just-in-time provisioning needs to
    // create an internal user on first login. The access token has no email,
    // so sending it would 401 any not-yet-provisioned Cognito user.
    access_token: idToken.getJwtToken(),
    refresh_token: session.getRefreshToken().getToken(),
    id_token: idToken.getJwtToken(),
    token_type: 'Bearer',
    expires_in: Math.max(idToken.getExpiration() - nowSeconds, 0),
  }
}

/**
 * Remove the read-only attributes Cognito rejects (`email_verified`,
 * `phone_number_verified`, `email`, `phone_number`) from the attribute map it
 * supplied via `newPasswordRequired`, leaving only attributes safe to set when
 * completing the challenge.
 */
export function sanitizeNewPasswordAttributes(
  userAttributes: Record<string, string> | null | undefined,
): Record<string, string> {
  const sanitized: Record<string, string> = { ...(userAttributes ?? {}) }
  for (const key of READ_ONLY_NEW_PASSWORD_ATTRIBUTES) {
    delete sanitized[key]
  }
  return sanitized
}

function authFailure(err: unknown, fallback: string): CognitoSignInError {
  const message = err instanceof Error && err.message ? err.message : fallback
  return new CognitoSignInError('AUTH_FAILED', message)
}

/**
 * Build the authentication callbacks for an in-flight `CognitoUser`. The same
 * shape is reused for the initial `authenticateUser` and for
 * `completeNewPasswordChallenge`, so a challenge that chains into another
 * challenge resolves to the correct union member.
 */
function buildChallengeCallbacks(
  cognitoUser: CognitoUser,
  resolve: (result: CognitoSignInResult) => void,
  reject: (error: CognitoSignInError) => void,
): IAuthenticationCallback {
  const mfaMember = (mfaType: CognitoMfaType): CognitoSignInResult => ({
    status: 'MFA_REQUIRED',
    mfaType,
    respond: (code: string) =>
      new Promise<CognitoSignInResult>((resolveMfa, rejectMfa) => {
        cognitoUser.sendMFACode(
          code,
          {
            onSuccess: (session) => resolveMfa({ status: 'SUCCESS', tokens: mapSession(session) }),
            onFailure: (err) => rejectMfa(authFailure(err, 'Invalid verification code.')),
          },
          mfaType === 'SOFTWARE_TOKEN_MFA' ? 'SOFTWARE_TOKEN_MFA' : undefined,
        )
      }),
  })

  return {
    onSuccess: (session) => {
      resolve({ status: 'SUCCESS', tokens: mapSession(session) })
    },
    onFailure: (err) => {
      reject(authFailure(err, 'Invalid email or password.'))
    },
    mfaRequired: (challengeName) => {
      resolve(mfaMember(challengeName === 'SOFTWARE_TOKEN_MFA' ? 'SOFTWARE_TOKEN_MFA' : 'SMS_MFA'))
    },
    totpRequired: () => {
      resolve(mfaMember('SOFTWARE_TOKEN_MFA'))
    },
    newPasswordRequired: (userAttributes: Record<string, string>) => {
      resolve({
        status: 'NEW_PASSWORD_REQUIRED',
        respond: (newPassword: string) =>
          new Promise<CognitoSignInResult>((resolveNew, rejectNew) => {
            cognitoUser.completeNewPasswordChallenge(
              newPassword,
              sanitizeNewPasswordAttributes(userAttributes),
              buildChallengeCallbacks(cognitoUser, resolveNew, rejectNew),
            )
          }),
      })
    },
  }
}

/**
 * Authenticate with email + password via SRP and resolve a sign-in result.
 *
 * On the happy path the result is `{ status: 'SUCCESS', tokens }` where the
 * ACCESS token (not the id token) is mapped to `access_token` because the
 * backend validates access tokens by `client_id` and the auth store sends
 * `access_token` as the Bearer credential. When Cognito issues a challenge the
 * result is an `MFA_REQUIRED` / `NEW_PASSWORD_REQUIRED` member whose `respond`
 * completes the challenge on the same `CognitoUser` instance. Genuine failures
 * reject with a `CognitoSignInError`.
 */
export async function signInWithCognito(
  email: string,
  password: string,
): Promise<CognitoSignInResult> {
  const { userPoolId, clientId } = getSdkConfig()
  if (!userPoolId || !clientId) {
    throw new CognitoSignInError('AUTH_FAILED', 'Cognito sign-in is not configured')
  }

  const userPool = new CognitoUserPool({ UserPoolId: userPoolId, ClientId: clientId })
  const cognitoUser = new CognitoUser({ Username: email, Pool: userPool })
  const authenticationDetails = new AuthenticationDetails({ Username: email, Password: password })

  return new Promise<CognitoSignInResult>((resolve, reject) => {
    cognitoUser.authenticateUser(
      authenticationDetails,
      buildChallengeCallbacks(cognitoUser, resolve, reject),
    )
  })
}
