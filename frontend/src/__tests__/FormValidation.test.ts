import { describe, it, expect } from 'vitest'
import { z } from 'zod'

/**
 * Re-define the Zod schemas as they appear in the auth feature pages.
 * Tests verify the validation logic for login, reset-password, and accept-invitation forms.
 */

const loginSchema = z.object({
  email: z.email('Please enter a valid email address'),
  password: z.string().min(1, 'Password is required'),
  mfa_code: z.string().optional(),
})

const resetPasswordSchema = z
  .object({
    password: z.string().min(8, 'Password must be at least 8 characters'),
    confirmPassword: z.string().min(1, 'Please confirm your password'),
  })
  .refine((data) => data.password === data.confirmPassword, {
    message: 'Passwords do not match',
    path: ['confirmPassword'],
  })

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

describe('Login schema validation', () => {
  it('accepts valid credentials', () => {
    const result = loginSchema.safeParse({
      email: 'user@example.com',
      password: 'secret123',
    })
    expect(result.success).toBe(true)
  })

  it('accepts credentials with optional mfa_code', () => {
    const result = loginSchema.safeParse({
      email: 'user@example.com',
      password: 'secret123',
      mfa_code: '123456',
    })
    expect(result.success).toBe(true)
  })

  it('rejects invalid email', () => {
    const result = loginSchema.safeParse({
      email: 'not-an-email',
      password: 'secret123',
    })
    expect(result.success).toBe(false)
    if (!result.success) {
      const emailError = result.error.issues.find((i) => i.path.includes('email'))
      expect(emailError).toBeDefined()
    }
  })

  it('rejects empty password', () => {
    const result = loginSchema.safeParse({
      email: 'user@example.com',
      password: '',
    })
    expect(result.success).toBe(false)
    if (!result.success) {
      const passwordError = result.error.issues.find((i) => i.path.includes('password'))
      expect(passwordError).toBeDefined()
    }
  })

  it('rejects missing email field', () => {
    const result = loginSchema.safeParse({
      password: 'secret123',
    })
    expect(result.success).toBe(false)
  })
})

describe('Reset password schema validation', () => {
  it('accepts matching passwords of sufficient length', () => {
    const result = resetPasswordSchema.safeParse({
      password: 'StrongPass1',
      confirmPassword: 'StrongPass1',
    })
    expect(result.success).toBe(true)
  })

  it('rejects passwords shorter than 8 characters', () => {
    const result = resetPasswordSchema.safeParse({
      password: 'short',
      confirmPassword: 'short',
    })
    expect(result.success).toBe(false)
    if (!result.success) {
      const passwordError = result.error.issues.find((i) => i.path.includes('password'))
      expect(passwordError).toBeDefined()
    }
  })

  it('rejects when passwords do not match', () => {
    const result = resetPasswordSchema.safeParse({
      password: 'StrongPass1',
      confirmPassword: 'DifferentPass',
    })
    expect(result.success).toBe(false)
    if (!result.success) {
      const confirmError = result.error.issues.find((i) => i.path.includes('confirmPassword'))
      expect(confirmError).toBeDefined()
      expect(confirmError?.message).toBe('Passwords do not match')
    }
  })

  it('rejects empty confirmPassword', () => {
    const result = resetPasswordSchema.safeParse({
      password: 'StrongPass1',
      confirmPassword: '',
    })
    expect(result.success).toBe(false)
  })
})

describe('Accept invitation schema validation', () => {
  it('accepts valid invitation data', () => {
    const result = acceptInvitationSchema.safeParse({
      first_name: 'Jane',
      last_name: 'Doe',
      password: 'SecurePass1',
      confirmPassword: 'SecurePass1',
    })
    expect(result.success).toBe(true)
  })

  it('rejects empty first_name', () => {
    const result = acceptInvitationSchema.safeParse({
      first_name: '',
      last_name: 'Doe',
      password: 'SecurePass1',
      confirmPassword: 'SecurePass1',
    })
    expect(result.success).toBe(false)
    if (!result.success) {
      const firstNameError = result.error.issues.find((i) => i.path.includes('first_name'))
      expect(firstNameError).toBeDefined()
    }
  })

  it('rejects empty last_name', () => {
    const result = acceptInvitationSchema.safeParse({
      first_name: 'Jane',
      last_name: '',
      password: 'SecurePass1',
      confirmPassword: 'SecurePass1',
    })
    expect(result.success).toBe(false)
    if (!result.success) {
      const lastNameError = result.error.issues.find((i) => i.path.includes('last_name'))
      expect(lastNameError).toBeDefined()
    }
  })

  it('rejects short password', () => {
    const result = acceptInvitationSchema.safeParse({
      first_name: 'Jane',
      last_name: 'Doe',
      password: 'Abc1',
      confirmPassword: 'Abc1',
    })
    expect(result.success).toBe(false)
    if (!result.success) {
      const passwordError = result.error.issues.find((i) => i.path.includes('password'))
      expect(passwordError).toBeDefined()
    }
  })

  it('rejects non-matching passwords', () => {
    const result = acceptInvitationSchema.safeParse({
      first_name: 'Jane',
      last_name: 'Doe',
      password: 'SecurePass1',
      confirmPassword: 'DifferentPass',
    })
    expect(result.success).toBe(false)
    if (!result.success) {
      const confirmError = result.error.issues.find((i) => i.path.includes('confirmPassword'))
      expect(confirmError).toBeDefined()
      expect(confirmError?.message).toBe('Passwords do not match')
    }
  })
})
