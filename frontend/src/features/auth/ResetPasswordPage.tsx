import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { api } from '@/lib/api'
import { useSearch } from '@tanstack/react-router'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { FormField } from '@/components/patterns/FormField'
import { AuthPageLayout } from './AuthPageLayout'

const resetPasswordSchema = z
  .object({
    password: z.string().min(8, 'Password must be at least 8 characters'),
    confirmPassword: z.string().min(1, 'Please confirm your password'),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: 'Passwords do not match',
    path: ['confirmPassword'],
  })

type ResetPasswordFormData = z.infer<typeof resetPasswordSchema>

export function ResetPasswordPage() {
  const search = useSearch({ strict: false }) as { token?: string }
  const token = search.token ?? ''

  const [success, setSuccess] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ResetPasswordFormData>({
    resolver: zodResolver(resetPasswordSchema),
  })

  const onSubmit = async (data: ResetPasswordFormData) => {
    if (!token) {
      setError('Invalid or missing reset token.')
      return
    }
    setError(null)
    setIsLoading(true)
    try {
      await api.post('/auth/reset-password', {
        token,
        new_password: data.password,
      })
      setSuccess(true)
    } catch {
      setError('Unable to reset password. The link may have expired.')
    } finally {
      setIsLoading(false)
    }
  }

  if (!token) {
    return (
      <AuthPageLayout title="Invalid Link" description="This password reset link is invalid or has expired.">
        <Alert variant="warning">
          <AlertDescription>
            This password reset link is invalid or has expired.
          </AlertDescription>
        </Alert>
        <a href="/forgot-password" className="block text-center text-sm text-primary underline-offset-4 hover:underline">
          Request a new reset link
        </a>
      </AuthPageLayout>
    )
  }

  return (
    <AuthPageLayout title="Reset Password" description="Enter your new password below.">
      {error ? (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {success ? (
        <div className="space-y-4">
          <Alert variant="success">
            <AlertDescription>Password has been reset successfully.</AlertDescription>
          </Alert>
          <div className="text-center">
            <a href="/login" className="text-sm text-primary underline-offset-4 hover:underline">
              Go to Sign In
            </a>
          </div>
        </div>
      ) : (
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <FormField label="New Password" id="password" name="password" error={errors.password} required>
            <Input
              type="password"
              autoComplete="new-password"
              placeholder="••••••••"
              {...register('password')}
            />
          </FormField>
          <FormField label="Confirm Password" id="confirmPassword" name="confirmPassword" error={errors.confirmPassword} required>
            <Input
              type="password"
              autoComplete="new-password"
              placeholder="••••••••"
              {...register('confirmPassword')}
            />
          </FormField>
          <Button type="submit" className="w-full" pending={isLoading} loadingText="Resetting…">
            Reset Password
          </Button>
        </form>
      )}
    </AuthPageLayout>
  )
}
