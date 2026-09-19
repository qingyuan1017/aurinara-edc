import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { useState } from 'react'
import { api } from '@/lib/api'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { FormField } from '@/components/patterns/FormField'
import { AuthPageLayout } from './AuthPageLayout'

const forgotPasswordSchema = z.object({
  email: z.email('Please enter a valid email address'),
})

type ForgotPasswordFormData = z.infer<typeof forgotPasswordSchema>

export function ForgotPasswordPage() {
  const [submitted, setSubmitted] = useState(false)
  const [isLoading, setIsLoading] = useState(false)

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ForgotPasswordFormData>({
    resolver: zodResolver(forgotPasswordSchema),
  })

  const onSubmit = async (data: ForgotPasswordFormData) => {
    setIsLoading(true)
    try {
      await api.post('/auth/forgot-password', { email: data.email })
    } catch {
      // Show success regardless to prevent email enumeration
    } finally {
      setIsLoading(false)
      setSubmitted(true)
    }
  }

  return (
    <AuthPageLayout
      title="Forgot Password"
      description="Enter your email and we'll send you a reset link."
      footer={
        <a href="/login" className="text-sm text-primary underline-offset-4 hover:underline">
          Back to Sign In
        </a>
      }
    >
      {submitted ? (
        <Alert variant="success">
          <AlertDescription>
            If an account with that email exists, a password reset link has been sent. Please check
            your inbox.
          </AlertDescription>
        </Alert>
      ) : (
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <FormField label="Email" id="email" name="email" error={errors.email} required>
            <Input
              type="email"
              autoComplete="email"
              placeholder="you@example.com"
              {...register('email')}
            />
          </FormField>
          <Button type="submit" className="w-full" pending={isLoading} loadingText="Sending…">
            Send Reset Link
          </Button>
        </form>
      )}
    </AuthPageLayout>
  )
}
