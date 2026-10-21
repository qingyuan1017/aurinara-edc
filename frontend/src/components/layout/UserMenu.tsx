import { useRef } from 'react'
import { ChevronDown, LogOut } from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

export interface UserMenuProps {
  displayName: string
  email?: string
  onSignOut: () => void | Promise<void>
}

function initials(value: string): string {
  const words = value.trim().split(/\s+/).filter(Boolean)
  return (words.length > 1 ? `${words[0][0]}${words.at(-1)?.[0] ?? ''}` : value.slice(0, 2)).toUpperCase() || 'AU'
}

/** Account controls retain the authenticated shell's existing logout callback. */
export function UserMenu({ displayName, email, onSignOut }: UserMenuProps) {
  const triggerRef = useRef<HTMLButtonElement>(null)

  return (
    <div className="relative shrink-0">
      <DropdownMenu
        onOpenChange={(open) => {
          if (!open) {
            triggerRef.current?.focus()
          }
        }}
      >
        <DropdownMenuTrigger
          ref={triggerRef}
          aria-label={`Open user menu for ${displayName}`}
          className="inline-flex h-10 max-w-56 items-center gap-2 rounded-md px-2 text-foreground transition-colors hover:bg-accent hover:text-accent-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        >
          <span className="flex size-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary" aria-hidden="true">{initials(displayName)}</span>
          <span className="hidden min-w-0 flex-1 text-left leading-tight lg:block">
            <span className="block truncate text-sm font-medium">{displayName}</span>
            <span className="block truncate text-[11px] font-normal text-muted-foreground">{email ?? 'Account'}</span>
          </span>
          <ChevronDown className="hidden size-3.5 text-muted-foreground lg:block" aria-hidden="true" />
        </DropdownMenuTrigger>
        <DropdownMenuContent className="right-0 top-[calc(100%+8px)] w-60">
          <DropdownMenuLabel className="font-normal"><span className="block truncate text-sm font-medium">{displayName}</span><span className="block truncate text-xs text-muted-foreground">{email ?? 'Signed in'}</span></DropdownMenuLabel>
          <DropdownMenuSeparator />
          <DropdownMenuItem className="text-destructive focus:bg-destructive/10 focus:text-destructive" onClick={() => void onSignOut()}>
            <LogOut className="mr-2 size-4" aria-hidden="true" />
            Sign out
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  )
}
