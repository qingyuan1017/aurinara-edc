import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useAuthStore } from '@/lib/auth'
import { buildCognitoAuthorizeUrl, isCognitoConfigured } from '@/lib/cognito'
import {
  CognitoSignInError,
  isCognitoSdkConfigured,
  signInWithCognito,
  type CognitoSignInResult,
} from '@/lib/cognito-sdk'
import { useNavigate } from '@tanstack/react-router'
import type { AxiosError } from 'axios'
import type { ApiError } from '@/lib/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { FormField } from '@/components/patterns/FormField'
import { AuthPageLayout } from './AuthPageLayout'
import { CognitoNewPasswordForm } from './CognitoNewPasswordForm'

const loginSchema = z.object({
  email: z.email('Please enter a valid email address'),
  password: z.string().min(1, 'Password is required'),
  mfa_code: z.string().optional(),
})

type LoginFormData = z.infer<typeof loginSchema>

export function LoginPage() {
  const login = useAuthStore((s) => s.login)
  const isLoading = useAuthStore((s) => s.isLoading)
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)
  const [showMfa, setShowMfa] = useState(false)
  // SDK-path Cognito challenge (MFA / NEW_PASSWORD_REQUIRED). Null when no
  // challenge is active; the email/password form is hidden while it is set.
  const [challenge, setChallenge] = useState<CognitoSignInResult | null>(null)
  const [challengePending, setChallengePending] = useState(false)
  const [mfaCode, setMfaCode] = useState('')
  const cognitoConfigured = isCognitoConfigured()
  const sdkConfigured = isCognitoSdkConfigured()

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginFormData>({
    resolver: zodResolver(loginSchema),
  })

  const startCognitoLogin = async () => {
    setError(null)
    try {
      window.location.assign(await buildCognitoAuthorizeUrl())
    } catch {
      setError('Hosted sign-in is not available.')
    }
  }

  // Drive the SDK sign-in union to its next state: finish the login on SUCCESS,
  // otherwise surface the challenge UI. Shared by the three SDK submit sites.
  const processResult = async (result: CognitoSignInResult) => {
    if (result.status === 'SUCCESS') {
      setChallenge(null)
      await useAuthStore.getState().completeCognitoLogin(result.tokens)
      await navigate({ to: '/' })
      return
    }
    setError(null)
    setMfaCode('')
    setChallenge(result)
  }

  const handleSdkError = (err: unknown) => {
    setError(err instanceof CognitoSignInError ? err.message : 'Unable to complete sign-in.')
  }

  const submitMfaCode = async () => {
    if (!challenge || challenge.status !== 'MFA_REQUIRED') return
    setError(null)
    setChallengePending(true)
    try {
      await processResult(await challenge.respond(mfaCode))
    } catch (err) {
      handleSdkError(err)
    } finally {
      setChallengePending(false)
    }
  }

  const submitNewPassword = async (newPassword: string) => {
    if (!challenge || challenge.status !== 'NEW_PASSWORD_REQUIRED') return
    setError(null)
    setChallengePending(true)
    try {
      await processResult(await challenge.respond(newPassword))
    } catch (err) {
      handleSdkError(err)
    } finally {
      setChallengePending(false)
    }
  }

  const onSubmit = async (data: LoginFormData) => {
    setError(null)
    if (sdkConfigured) {
      try {
        await processResult(await signInWithCognito(data.email, data.password))
      } catch (err) {
        setError(err instanceof CognitoSignInError ? err.message : 'Invalid email or password.')
      }
      return
    }

    try {
      await login(data.email, data.password, data.mfa_code)
      await navigate({ to: '/' })
    } catch (err) {
      const axiosError = err as AxiosError<ApiError>
      const detail = axiosError.response?.data?.detail
      if (detail?.toLowerCase().includes('mfa')) {
        setShowMfa(true)
        setError('Please enter your MFA code.')
      } else {
        setError(detail ?? 'Invalid email or password.')
      }
    }
  }

  const mfaChallenge = challenge?.status === 'MFA_REQUIRED' ? challenge : null
  const newPasswordChallenge = challenge?.status === 'NEW_PASSWORD_REQUIRED' ? challenge : null
  const mfaLabel = mfaChallenge?.mfaType === 'SOFTWARE_TOKEN_MFA' ? 'Authenticator code' : 'SMS code'

  return (
    <AuthPageLayout
      title="Sign In"
      description="Clinical EDC System"
      footer={
        !sdkConfigured && !cognitoConfigured ? (
          <a href="/forgot-password" className="text-sm text-primary underline-offset-4 hover:underline">
            Forgot your password?
          </a>
        ) : undefined
      }
    >
      {error ? (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {mfaChallenge ? (
        <form
          onSubmit={(event) => {
            event.preventDefault()
            void submitMfaCode()
          }}
          className="space-y-4"
        >
          <FormField label={mfaLabel} id="cognito_mfa_code" name="cognito_mfa_code">
            <Input
              type="text"
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="123456"
              value={mfaCode}
              onChange={(event) => setMfaCode(event.target.value)}
            />
          </FormField>
          <Button type="submit" className="w-full" pending={challengePending} loadingText="Verifying…">
            Verify Code
          </Button>
        </form>
      ) : newPasswordChallenge ? (
        <CognitoNewPasswordForm pending={challengePending} onSubmit={submitNewPassword} />
      ) : (
        <>
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <FormField
              label="Email"
              id="email"
              name="email"
              error={errors.email}
              required
            >
              <Input
                type="email"
                autoComplete="email"
                placeholder="you@example.com"
                {...register('email')}
              />
            </FormField>

            <FormField
              label="Password"
              id="password"
              name="password"
              error={errors.password}
              required
            >
              <Input
                type="password"
                autoComplete="current-password"
                placeholder="••••••••"
                {...register('password')}
              />
            </FormField>

            {showMfa ? (
              <FormField label="MFA Code" id="mfa_code" name="mfa_code">
                <Input
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  placeholder="123456"
                  {...register('mfa_code')}
                />
              </FormField>
            ) : null}

            <Button type="submit" className="w-full" pending={isLoading} loadingText="Signing in…">
              Sign In
            </Button>
          </form>
          {cognitoConfigured ? (
            <Button type="button" variant="outline" className="w-full" onClick={() => void startCognitoLogin()}>
              Sign in with Cognito
            </Button>
          ) : null}
        </>
      )}
    </AuthPageLayout>
  )
}
