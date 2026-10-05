import axios from 'axios'

export interface CognitoTokenResponse {
  access_token: string
  refresh_token?: string
  id_token?: string
  token_type?: string
  expires_in?: number
}

const COGNITO_STATE_KEY = 'cognito_oauth_state'
const COGNITO_VERIFIER_KEY = 'cognito_pkce_verifier'

export function getCognitoConfig() {
  const domain = import.meta.env.VITE_COGNITO_DOMAIN?.trim()
  const clientId = import.meta.env.VITE_COGNITO_CLIENT_ID?.trim()
  const redirectUri = import.meta.env.VITE_COGNITO_REDIRECT_URI?.trim()
  const scopes = import.meta.env.VITE_COGNITO_SCOPES?.trim() || 'openid email'
  return { domain, clientId, redirectUri, scopes }
}

export function isCognitoConfigured(): boolean {
  const { domain, clientId, redirectUri } = getCognitoConfig()
  return Boolean(domain && clientId && redirectUri)
}

function base64Url(bytes: Uint8Array): string {
  let binary = ''
  bytes.forEach((byte) => { binary += String.fromCharCode(byte) })
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}

function randomUrlSafe(length = 32): string {
  const bytes = new Uint8Array(length)
  crypto.getRandomValues(bytes)
  return base64Url(bytes)
}

async function createChallenge(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))
  return base64Url(new Uint8Array(digest))
}

export async function buildCognitoAuthorizeUrl(): Promise<string> {
  const { domain, clientId, redirectUri, scopes } = getCognitoConfig()
  if (!domain || !clientId || !redirectUri) {
    throw new Error('Cognito authentication is not configured')
  }
  const state = randomUrlSafe()
  const verifier = randomUrlSafe(48)
  sessionStorage.setItem(COGNITO_STATE_KEY, state)
  sessionStorage.setItem(COGNITO_VERIFIER_KEY, verifier)
  const normalizedDomain = domain.replace(/\/$/, '').replace(/^https?:\/\//, '')
  const params = new URLSearchParams({
    response_type: 'code',
    client_id: clientId,
    redirect_uri: redirectUri,
    scope: scopes,
    state,
    code_challenge: await createChallenge(verifier),
    code_challenge_method: 'S256',
  })
  return `https://${normalizedDomain}/oauth2/authorize?${params.toString()}`
}

export function consumeCognitoCallbackState(state: string | null): string {
  const expectedState = sessionStorage.getItem(COGNITO_STATE_KEY)
  const verifier = sessionStorage.getItem(COGNITO_VERIFIER_KEY)
  sessionStorage.removeItem(COGNITO_STATE_KEY)
  sessionStorage.removeItem(COGNITO_VERIFIER_KEY)
  if (!state || !expectedState || state !== expectedState || !verifier) {
    throw new Error('Invalid Cognito callback state')
  }
  return verifier
}

export async function exchangeCognitoCode(
  code: string,
  codeVerifier: string,
): Promise<CognitoTokenResponse> {
  const { redirectUri } = getCognitoConfig()
  const { data } = await axios.post<CognitoTokenResponse>('/api/v1/auth/cognito/exchange', {
    code,
    code_verifier: codeVerifier,
    redirect_uri: redirectUri,
  })
  return data
}
