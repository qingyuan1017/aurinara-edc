import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { useAuthStore } from '@/lib/auth'
import { useNavigate } from '@tanstack/react-router'
import type { AxiosError } from 'axios'
import type { ApiError } from '@/lib/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { FormField } from '@/components/patterns/FormField'
import { AuthPageLayout } from './AuthPageLayout'

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

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginFormData>({
    resolver: zodResolver(loginSchema),
  })

  const onSubmit = async (data: LoginFormData) => {
    setError(null)
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

  return (
    <AuthPageLayout
      title="Sign In"
      description="Clinical EDC System"
      footer={
        <a href="/forgot-password" className="text-sm text-primary underline-offset-4 hover:underline">
          Forgot your password?
        </a>
      }
    >
      {error ? (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

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
    </AuthPageLayout>
  )
}
