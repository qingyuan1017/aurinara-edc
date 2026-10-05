import { useEffect, useState } from 'react'
import { useNavigate } from '@tanstack/react-router'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { AuthPageLayout } from './AuthPageLayout'
import { useAuthStore } from '@/lib/auth'
import { consumeCognitoCallbackState, exchangeCognitoCode } from '@/lib/cognito'

export function CognitoCallbackPage() {
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    const complete = async () => {
      const params = new URLSearchParams(window.location.search)
      const providerError = params.get('error_description') || params.get('error')
      if (providerError) {
        throw new Error('Cognito sign-in was cancelled')
      }
      const code = params.get('code')
      if (!code) throw new Error('Cognito callback did not include an authorization code')
      const verifier = consumeCognitoCallbackState(params.get('state'))
      const tokens = await exchangeCognitoCode(code, verifier)
      await useAuthStore.getState().completeCognitoLogin(tokens)
      if (!cancelled) await navigate({ to: '/' })
    }
    void complete().catch(() => {
      if (!cancelled) setError('Hosted sign-in could not be completed. Please try again.')
    })
    return () => { cancelled = true }
  }, [navigate])

  return (
    <AuthPageLayout title="Signing you in" description="Clinical EDC System">
      {error ? (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : <p className="text-sm text-muted-foreground">Completing secure sign-in…</p>}
    </AuthPageLayout>
  )
}
