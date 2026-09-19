import { useNavigate } from '@tanstack/react-router'
import { Building2, ClipboardList, Lock } from 'lucide-react'
import { useAuthStore } from '@/lib/auth'
import { usePermission, PERMISSIONS } from '@/lib/permissions'
import { useCTMSCapabilityState } from '@/features/ctms'
import { useModuleStore, type AppModule } from '@/lib/module-context'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'

interface ModuleOption {
  readonly id: AppModule
  readonly title: string
  readonly description: string
  readonly icon: typeof Building2
  readonly available: boolean
  readonly unavailableReason?: string
}

/**
 * ModuleSelectPage — post-login landing where the user chooses which product
 * module to work in (EDC or CTMS). The sidebar is then scoped to that module.
 *
 * CTMS availability mirrors the same authority gates used by the shell: the
 * server capability manifest must report the module as ready AND the user must
 * hold the CTMS read permission. Selection is convenience only; every route
 * remains server-authorized.
 */
export function ModuleSelectPage() {
  const navigate = useNavigate()
  const user = useAuthStore((s) => s.user)
  const setModule = useModuleStore((s) => s.setModule)
  const ctmsState = useCTMSCapabilityState()
  const canReadCTMS = usePermission(PERMISSIONS.CTMS_OPERATIONAL_DATA_READ)

  const ctmsAvailable = ctmsState.status === 'ready' && canReadCTMS
  const ctmsReason =
    ctmsState.status !== 'ready'
      ? 'CTMS is not enabled for this environment.'
      : !canReadCTMS
        ? 'Your account does not have CTMS access.'
        : undefined

  const options: readonly ModuleOption[] = [
    {
      id: 'edc',
      title: 'EDC',
      description: 'Electronic Data Capture — studies, subjects, forms, queries, and data quality.',
      icon: ClipboardList,
      available: true,
    },
    {
      id: 'ctms',
      title: 'CTMS',
      description: 'Clinical Trial Management — operational studies, sites, enrollment, and monitoring.',
      icon: Building2,
      available: ctmsAvailable,
      unavailableReason: ctmsReason,
    },
  ]

  const choose = (module: AppModule) => {
    setModule(module)
    navigate({ to: module === 'ctms' ? '/ctms' : '/' })
  }

  const displayName = user ? `${user.first_name} ${user.last_name}` : 'there'

  return (
    <div className="mx-auto flex min-h-screen w-full max-w-3xl flex-col justify-center gap-8 px-4 py-12">
      <div className="space-y-2 text-center">
        <h1 className="text-3xl font-bold tracking-tight text-foreground">Welcome, {displayName}</h1>
        <p className="text-muted-foreground">Choose a module to get started. You can switch modules anytime from the header.</p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        {options.map((option) => {
          const Icon = option.icon
          const disabled = !option.available
          return (
            <Card
              key={option.id}
              role="button"
              tabIndex={disabled ? -1 : 0}
              aria-disabled={disabled}
              data-testid={`module-card-${option.id}`}
              onClick={disabled ? undefined : () => choose(option.id)}
              onKeyDown={
                disabled
                  ? undefined
                  : (event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        choose(option.id)
                      }
                    }
              }
              className={cn(
                'group relative transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2',
                disabled
                  ? 'cursor-not-allowed opacity-60'
                  : 'cursor-pointer hover:border-primary hover:shadow-md',
              )}
            >
              <CardHeader>
                <div className="mb-2 flex size-12 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  {disabled ? <Lock className="size-6" aria-hidden="true" /> : <Icon className="size-6" aria-hidden="true" />}
                </div>
                <CardTitle>{option.title}</CardTitle>
                <CardDescription>{option.description}</CardDescription>
              </CardHeader>
              {disabled && option.unavailableReason ? (
                <CardContent>
                  <p className="text-xs text-muted-foreground">{option.unavailableReason}</p>
                </CardContent>
              ) : null}
            </Card>
          )
        })}
      </div>
    </div>
  )
}
