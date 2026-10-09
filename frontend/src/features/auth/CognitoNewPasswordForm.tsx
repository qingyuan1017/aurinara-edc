import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { zodResolver } from '@hookform/resolvers/zod'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { FormField } from '@/components/patterns/FormField'

const newPasswordSchema = z
  .object({
    password: z.string().min(8, 'Password must be at least 8 characters'),
    confirmPassword: z.string().min(1, 'Please confirm your password'),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: 'Passwords do not match',
    path: ['confirmPassword'],
  })

type NewPasswordFormData = z.infer<typeof newPasswordSchema>

export interface CognitoNewPasswordFormProps {
  onSubmit: (newPassword: string) => Promise<void>
  pending: boolean
}

/**
 * New-password form for the Cognito NEW_PASSWORD_REQUIRED challenge. Field-level
 * validation (match + length) is owned here; the parent LoginPage owns server
 * errors via its shared Alert.
 */
export function CognitoNewPasswordForm({ onSubmit, pending }: CognitoNewPasswordFormProps) {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<NewPasswordFormData>({
    resolver: zodResolver(newPasswordSchema),
  })

  const submit = handleSubmit((data) => onSubmit(data.password))

  return (
    <form onSubmit={submit} className="space-y-4">
      <FormField label="New Password" id="new_password" name="new_password" error={errors.password} required>
        <Input
          type="password"
          autoComplete="new-password"
          placeholder="••••••••"
          {...register('password')}
        />
      </FormField>
      <FormField
        label="Confirm Password"
        id="confirm_new_password"
        name="confirm_new_password"
        error={errors.confirmPassword}
        required
      >
        <Input
          type="password"
          autoComplete="new-password"
          placeholder="••••••••"
          {...register('confirmPassword')}
        />
      </FormField>
      <Button type="submit" className="w-full" pending={pending} loadingText="Updating…">
        Set New Password
      </Button>
    </form>
  )
}
