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

const acceptInvitationSchema = z
  .object({
    first_name: z.string().min(1, 'First name is required'),
    last_name: z.string().min(1, 'Last name is required'),
    password: z.string().min(8, 'Password must be at least 8 characters'),
    confirmPassword: z.string().min(1, 'Please confirm your password'),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: 'Passwords do not match',
    path: ['confirmPassword'],
  })

type AcceptInvitationFormData = z.infer<typeof acceptInvitationSchema>

export function AcceptInvitationPage() {
  const search = useSearch({ strict: false }) as { token?: string }
  const token = search.token ?? ''

  const [success, setSuccess] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<AcceptInvitationFormData>({
    resolver: zodResolver(acceptInvitationSchema),
  })

  const onSubmit = async (data: AcceptInvitationFormData) => {
    if (!token) {
      setError('Invalid or missing invitation token.')
      return
    }
    setError(null)
    setIsLoading(true)
    try {
      await api.post('/auth/invite/accept', {
        token,
        password: data.password,
        first_name: data.first_name,
        last_name: data.last_name,
      })
      setSuccess(true)
    } catch {
      setError('Unable to accept invitation. The link may have expired.')
    } finally {
      setIsLoading(false)
    }
  }

  if (!token) {
    return (
      <AuthPageLayout title="Invalid Invitation" description="This invitation link is invalid or has expired.">
        <Alert variant="warning">
          <AlertDescription>
            This invitation link is invalid or has expired. Please contact your administrator.
          </AlertDescription>
        </Alert>
      </AuthPageLayout>
    )
  }

  return (
    <AuthPageLayout
      title="Accept Invitation"
      description="Set up your account to access the Clinical EDC System."
    >
      {error ? (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      ) : null}

      {success ? (
        <div className="space-y-4">
          <Alert variant="success">
            <AlertDescription>Account created successfully. You can now sign in.</AlertDescription>
          </Alert>
          <div className="text-center">
            <a href="/login" className="text-sm text-primary underline-offset-4 hover:underline">
              Go to Sign In
            </a>
          </div>
        </div>
      ) : (
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="grid gap-4 sm:grid-cols-2">
            <FormField label="First Name" id="first_name" name="first_name" error={errors.first_name} required>
              <Input type="text" autoComplete="given-name" {...register('first_name')} />
            </FormField>
            <FormField label="Last Name" id="last_name" name="last_name" error={errors.last_name} required>
              <Input type="text" autoComplete="family-name" {...register('last_name')} />
            </FormField>
          </div>
          <FormField label="Password" id="password" name="password" error={errors.password} required>
            <Input type="password" autoComplete="new-password" placeholder="••••••••" {...register('password')} />
          </FormField>
          <FormField label="Confirm Password" id="confirmPassword" name="confirmPassword" error={errors.confirmPassword} required>
            <Input type="password" autoComplete="new-password" placeholder="••••••••" {...register('confirmPassword')} />
          </FormField>
          <Button type="submit" className="w-full" pending={isLoading} loadingText="Creating Account…">
            Create Account
          </Button>
        </form>
      )}
    </AuthPageLayout>
  )
}
